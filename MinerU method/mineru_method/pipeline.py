from __future__ import annotations

import json
import os
import re
from pathlib import Path

from article_agent.models import OpenAICompatibleClient
from article_agent.evidence_engine import BibliographicMetadata, MetadataResolver, inject_metadata_into_contexts
from article_agent.document_pipeline import chunks_from_normalized_document, normalize_markdown_document, write_normalized_document

from .bibliography import enrich_metadata
from .canonical import build_canonical_outcome_dataset
from .flow import cross_check, reconcile_flow, render_figure_one_page
from .gold import sheet3_gold
from .llm import (
    ValidatedExtractor,
    classify_outcome_tables_with_llm,
    extract_flow,
    extract_outcomes_from_table,
    extract_outcomes_from_results_narrative,
    extract_outcomes_by_table,
    merge_outcome_extractions,
    postprocess_outcomes_with_llm,
)
from .parser import hybrid_to_markdown, mineru_to_markdown, pymupdf_to_markdown
from .prompts import PROMPT_SPECS
from .registry import canonical_ids, load_bindings, model_field_ids, relevant_bindings
from .routing import contexts_for_modules
from .schemas import (
    AcupunctureProtocol, ConsortFlowExtraction, EvidenceQuote, ExtractionBundle, MetadataExtraction,
    OutcomeExtraction, OutcomePostProcessRecord, OutcomePostProcessing, OutcomeStatistic, RiskOfBiasExtraction, ShamType,
)
from .table_parser import extract_outcome_table_blocks, parse_primary_painvas


def _article_id(pdf: Path) -> str:
    match = re.search(r"(20\d{2}-\d+)", pdf.stem)
    return match.group(1) if match else pdf.stem.lstrip("-")


def _normalize_acupuncture(acupuncture: AcupunctureProtocol, context: str) -> AcupunctureProtocol:
    updates = {}
    evidence = list(acupuncture.evidence)
    if (
        acupuncture.treatment_duration_value is None
        and acupuncture.total_sessions is not None
        and acupuncture.treatment_frequency_value not in (None, 0)
        and acupuncture.treatment_frequency_unit == 2
    ):
        weeks = acupuncture.total_sessions / acupuncture.treatment_frequency_value
        quote_match = re.search(r"[^\n.]*\b(?:sessions?|treatments?)[^\n.]*\bper\s+week[^\n.]*", context, re.I)
        quote = quote_match.group(0).strip() if quote_match else f"{acupuncture.total_sessions} sessions; {acupuncture.treatment_frequency_value} per week"
        updates.update({
            "treatment_duration_raw": f"derived from {acupuncture.total_sessions} sessions at {acupuncture.treatment_frequency_value:g} per week",
            "treatment_duration_value": weeks,
            "treatment_duration_unit": 2,
        })
        evidence.append(EvidenceQuote(
            field_id="treatment_duration_value",
            quote=quote,
            source="markdown",
            support_type="derived",
            derivation=f"course_weeks = total_sessions / sessions_per_week = {acupuncture.total_sessions} / {acupuncture.treatment_frequency_value:g} = {weeks:g}",
        ))
    components = list(acupuncture.control_type_components)
    if acupuncture.control_type_transformed is not None and acupuncture.control_type_transformed not in components:
        components.append(acupuncture.control_type_transformed)
    if re.search(r"(?:usual|standard)\s+(?:drug|pharmacological|medical)\s+treatment", context, re.I) and ShamType.USUAL_CARE_NO_SHAM not in components:
        components.append(ShamType.USUAL_CARE_NO_SHAM)
    if components != acupuncture.control_type_components:
        updates["control_type_components"] = components
    experience = re.search(r"(?:over|more than)\s+(\d+(?:\.\d+)?)\s+years?[^\n.]{0,40}(?:experience|practical)", context, re.I)
    if experience:
        updates.update({
            "practitioner_experience_raw": experience.group(0).strip(),
            "practitioner_experience_years": float(experience.group(1)),
            "practitioner_experience_comparator": ">",
        })
    return acupuncture.model_copy(update={**updates, "evidence": evidence}) if updates else acupuncture


def _reconcile_risk_with_flow(risk: RiskOfBiasExtraction, flow: ConsortFlowExtraction | None) -> RiskOfBiasExtraction:
    if flow is None or len(flow.arms) != 2:
        return risk
    intervention = next((arm for arm in flow.arms if "individual" in arm.arm_name.lower() or arm.arm_name.lower() == "ia"), flow.arms[0])
    control = next((arm for arm in flow.arms if "sham" in arm.arm_name.lower() or arm.arm_name.lower() == "sa"), flow.arms[1])
    updates = {}
    evidence = list(risk.evidence)
    mapping = {
        "randomized_sample_intervention_raw": intervention.randomized_n,
        "randomized_sample_control_raw": control.randomized_n,
        "total_randomized": flow.randomized_n,
    }
    for field_id, value in mapping.items():
        if getattr(risk, field_id) is None and value is not None:
            updates[field_id] = value
            evidence.append(EvidenceQuote(
                field_id=field_id,
                quote=f"CONSORT: {intervention.randomized_n} allocated to {intervention.arm_name}; {control.randomized_n} allocated to {control.arm_name}; {flow.randomized_n} randomised",
                source="figure",
                support_type="direct",
            ))
    return risk.model_copy(update={**updates, "evidence": evidence}) if updates else risk


def _normalize_primary_analysis(risk: RiskOfBiasExtraction, context: str) -> RiskOfBiasExtraction:
    if risk.primary_analysis != 4:
        return risk
    if not re.search(r"intention-to-treat\s+analysis\s+revealed", context, re.I):
        return risk
    if not re.search(r"primary\s+outcome", context, re.I):
        return risk
    evidence = list(risk.evidence)
    quote = next((line.strip() for line in context.splitlines() if re.search(r"intention-to-treat\s+analysis\s+revealed", line, re.I)), "Intention-to-treat analysis revealed the primary outcome result")
    evidence.append(EvidenceQuote(
        field_id="primary_analysis",
        quote=quote,
        source="markdown",
        support_type="derived",
        derivation="The abstract presents the primary-outcome result explicitly as intention-to-treat; map primary_analysis to ITT_OR_MITT=1",
    ))
    return risk.model_copy(update={"primary_analysis": 1, "evidence": evidence})


def run_experiment(
    pdf: Path,
    project_root: Path,
    output_root: Path,
    parser: str = "mineru",
    markdown_path: Path | None = None,
    use_api: bool = False,
    use_vlm: bool = True,
    force_backend: str | None = None,
) -> ExtractionBundle | None:
    article_id = _article_id(pdf)
    output_dir = output_root / article_id
    output_dir.mkdir(parents=True, exist_ok=True)
    # The batch driver sets one stable run identifier for all articles.  Keep
    # it in every article manifest so a later resume/evaluation can prove that
    # artifacts came from the same configuration rather than an old batch.
    run_id = os.getenv("ARTICLE_AGENT_RUN_ID", "") or output_root.name
    routing = None
    if markdown_path:
        markdown = markdown_path.read_text(encoding="utf-8")
        backend = "provided-markdown"
    elif parser == "auto":
        markdown, backend, routing = hybrid_to_markdown(pdf, output_dir / "hybrid", force_backend=force_backend)
    elif parser == "docling":
        markdown, backend, routing = hybrid_to_markdown(
            pdf,
            output_dir / "hybrid",
            force_backend=force_backend or "docling",
        )
    elif parser == "mineru":
        markdown, backend = mineru_to_markdown(pdf, output_dir / "mineru")
    elif parser == "pymupdf":
        markdown = pymupdf_to_markdown(pdf)
        backend = "pymupdf-explicit-fallback"
    else:
        raise ValueError(f"Unsupported parser: {parser}")
    (output_dir / "article.md").write_text(markdown, encoding="utf-8")
    normalized_document = normalize_markdown_document(
        markdown,
        study_id=article_id,
        source_pdf=pdf,
        parser_backend=backend,
    )
    write_normalized_document(normalized_document, output_dir / "normalized_document.json")

    if routing is not None:
        (output_dir / "pdf_text_layer.json").write_text(
            routing.text_layer.model_dump_json(indent=2), encoding="utf-8"
        )

    contexts = contexts_for_modules(markdown)
    (output_dir / "routed_context.json").write_text(
        json.dumps(contexts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Evidence retrieval consumes a separate, metadata-headered context.  It
    # is opt-in for network calls; a local DOI/title header is still written so
    # downstream RCS code can use the same citation identity offline.
    evidence_metadata = BibliographicMetadata()
    doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", markdown, re.I)
    title_hint = next(
        (
            line.strip().lstrip("# ").strip()
            for line in markdown.splitlines()
            if line.strip().startswith("#")
            and not re.match(r"^#+\s*(?:abstract|introduction|methods?|results?|discussion|references?)\b", line, re.I)
        ),
        "NR",
    )
    if title_hint == "NR":
        title_hint = next((line.strip() for line in markdown.splitlines() if line.strip() and not line.startswith(("|", "<"))), "NR")
    evidence_metadata.doi = doi_match.group(0).rstrip(".,;)]}").lower() if doi_match else "NR"
    evidence_metadata.title = title_hint or "NR"
    if os.getenv("ARTICLE_AGENT_ENABLE_EXTERNAL_METADATA", "0").strip().lower() in {"1", "true", "yes"}:
        try:
            evidence_metadata = MetadataResolver().resolve(title=evidence_metadata.title, doi=evidence_metadata.doi, allow_network=True)
        except Exception as exc:
            evidence_metadata.errors.append(f"resolver: {type(exc).__name__}: {exc}")
    evidence_contexts = inject_metadata_into_contexts(contexts, evidence_metadata)
    evidence_chunks = chunks_from_normalized_document(normalized_document)
    # Store an index-ready, header-injected chunk sidecar.  RCS retrieval can
    # load this file later without rerunning MinerU or touching raw extraction.
    from article_agent.evidence_engine import inject_bibliographic_metadata
    evidence_chunks = inject_bibliographic_metadata(evidence_chunks, evidence_metadata)
    (output_dir / "evidence_metadata.json").write_text(evidence_metadata.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "evidence_contexts.json").write_text(json.dumps(evidence_contexts, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "evidence_chunks.json").write_text(json.dumps([chunk.model_dump(mode="json") for chunk in evidence_chunks], ensure_ascii=False, indent=2), encoding="utf-8")

    bindings = load_bindings(project_root)
    models = [MetadataExtraction, AcupunctureProtocol, RiskOfBiasExtraction, OutcomeStatistic]
    ids = model_field_ids(models)
    unknown = ids - canonical_ids(bindings)
    if unknown:
        raise RuntimeError(f"Model fields absent from legacy Excel registry: {sorted(unknown)}")
    (output_dir / "excel_bindings.json").write_text(
        json.dumps(relevant_bindings(bindings, ids), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "run_id": run_id,
        "article_id": article_id,
        "source_pdf": str(pdf.resolve()),
        "parser_backend": backend,
        "is_mineru_result": backend.startswith("mineru:") or backend in {"magic-pdf", "provided-markdown"},
        "hybrid_route": routing.model_dump(mode="json") if routing is not None else None,
        "api_requested": use_api,
        "structured_extraction_backend": "baml" if os.getenv("ARTICLE_AGENT_STRUCTURED_BACKEND", "auto").strip().lower() == "baml" else "baml-if-configured-otherwise-pydantic",
        "baml_outcomes_enabled": os.getenv("ARTICLE_AGENT_BAML_OUTCOMES", "0").strip().lower() in {"1", "true", "yes"},
        "context_characters": {key: len(value) for key, value in contexts.items()},
        "evidence_metadata": evidence_metadata.model_dump(mode="json"),
        "evidence_contexts": "evidence_contexts.json",
        "normalized_document": "normalized_document.json",
        "normalized_tables": len(normalized_document.tables),
        "evidence_chunks": len(evidence_chunks),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not use_api:
        return None

    # Table-wise extraction can legitimately return many row objects.  Keep
    # the timeout configurable so a degraded endpoint cannot stall an entire
    # article, while callers can still raise it for slower gateways.
    try:
        api_timeout = int(os.getenv("ARTICLE_AGENT_API_TIMEOUT", "180"))
    except ValueError:
        api_timeout = 180
    client = OpenAICompatibleClient(timeout=max(10, api_timeout))
    try:
        extraction_retries = int(os.getenv("ARTICLE_AGENT_EXTRACT_RETRIES", "2"))
    except ValueError:
        extraction_retries = 2
    extraction_retries = max(0, min(extraction_retries, 5))
    extractor = ValidatedExtractor(
        client,
        output_dir / "raw_module_responses",
        retries=extraction_retries,
    )
    manifest["structured_extraction_retries"] = extraction_retries
    manifest["structured_extraction_backend"] = extractor.baml.backend_name
    # Metadata/acupuncture/risk are ordinary field-structured modules and use
    # the same correctness model as outcome extraction by default.  The
    # lighter luna model is reserved for table classification/light routing;
    # it must not silently replace the sol model for source fields.
    structured_model = (
        os.getenv("ARTICLE_AGENT_STRUCTURED_MODEL")
        or client.model
    ).strip() or client.model
    structured_client = (
        client
        if structured_model == client.model
        else OpenAICompatibleClient(
            api_key=client.api_key,
            base_url=client.base_url,
            model=structured_model,
            timeout=client.timeout,
        )
    )
    structured_extractor = ValidatedExtractor(
        structured_client,
        output_dir / "raw_module_responses",
        retries=extraction_retries,
    )
    manifest["structured_module_model"] = structured_model
    metadata = structured_extractor.extract("metadata", MetadataExtraction, contexts["metadata"], PROMPT_SPECS["metadata"])
    metadata, _ = enrich_metadata(metadata, markdown, output_dir / "bibliographic_lookup.json")
    acupuncture = structured_extractor.extract("acupuncture", AcupunctureProtocol, contexts["acupuncture"], PROMPT_SPECS["acupuncture"])
    acupuncture = _normalize_acupuncture(acupuncture, contexts["acupuncture"])
    risk = structured_extractor.extract("risk_of_bias", RiskOfBiasExtraction, contexts["risk_of_bias"], PROMPT_SPECS["risk_of_bias"])
    risk = _normalize_primary_analysis(risk, contexts["risk_of_bias"])
    outcome_raw_dir = output_dir / "raw_module_responses"
    parsed_outcomes = parse_primary_painvas(contexts["outcomes"])
    # Parse table structure first, but defer semantic table classification to
    # a dedicated LLM pass.  This prevents a fixed keyword list from silently
    # skipping tables such as 2015-05 Table 2 (Pain/Anxiety/VAS).
    table_blocks = extract_outcome_table_blocks(
        contexts["outcomes"],
        defer_classification=True,
    )
    try:
        outcome_request_delay = float(os.getenv("ARTICLE_AGENT_OUTCOME_REQUEST_DELAY_SECONDS", "0.01"))
    except ValueError:
        outcome_request_delay = 0.01
    outcome_request_delay = max(0.0, min(outcome_request_delay, 60.0))
    # The table-wise pass receives one table at a time.  The short narrative
    # hint helps map captions and time labels without re-sending all Results.
    # Table routing receives the complete Results evidence.  It is only a
    # semantic hint; structural row selection still uses the deterministic
    # column map.  Do not keep a prefix or character window here because the
    # relevant outcome narrative may occur after the first table.
    narrative_hint = contexts["outcomes"]
    table_classification_manifest: list[dict] = []
    # Semantic routing/matching is intentionally allowed to use the lighter
    # luna model.  Keep a dedicated table variable for reproducibility, while
    # ``ARTICLE_AGENT_BASIC_MATCH_MODEL`` provides one switch for any future
    # deterministic field/table matching step that is promoted to an LLM.
    table_classifier_model = (
        os.getenv("ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL")
        or os.getenv("ARTICLE_AGENT_BASIC_MATCH_MODEL")
        or "gpt-5.6-luna"
    ).strip() or "gpt-5.6-luna"
    try:
        table_classifier_retries = int(os.getenv("ARTICLE_AGENT_TABLE_CLASSIFIER_RETRIES", "1"))
    except ValueError:
        table_classifier_retries = 1
    table_classifier_retries = max(0, min(table_classifier_retries, 5))
    try:
        table_classifier_timeout = int(
            os.getenv("ARTICLE_AGENT_TABLE_CLASSIFIER_TIMEOUT", os.getenv("ARTICLE_AGENT_API_TIMEOUT", "180"))
        )
    except ValueError:
        table_classifier_timeout = 180
    table_classifier_timeout = max(10, table_classifier_timeout)
    if table_blocks:
        # Keep the extraction/evaluation model unchanged.  A separate client
        # lets routing use the explicitly configured lightweight model while
        # preserving the same API key and endpoint failover order.
        classifier_client = (
            client
            if table_classifier_model == client.model
            else OpenAICompatibleClient(
                api_key=client.api_key,
                base_url=client.base_url,
                model=table_classifier_model,
                timeout=table_classifier_timeout,
            )
        )
        table_blocks, table_classification_manifest = classify_outcome_tables_with_llm(
            classifier_client,
            table_blocks,
            outcome_raw_dir,
            narrative_hint=narrative_hint,
            retries=table_classifier_retries,
            request_delay_seconds=outcome_request_delay,
        )
    tablewise_manifest: list[dict]
    narrative_outcomes = OutcomeExtraction(outcomes=[])
    narrative_manifest: list[dict] = []
    if table_blocks:
        try:
            outcome_rows_per_request = int(os.getenv("ARTICLE_AGENT_OUTCOME_ROWS_PER_REQUEST", "3"))
        except ValueError:
            outcome_rows_per_request = 3
        outcome_rows_per_request = max(1, min(outcome_rows_per_request, 12))
        try:
            outcome_retries = int(os.getenv("ARTICLE_AGENT_OUTCOME_RETRIES", "2"))
        except ValueError:
            outcome_retries = 2
        outcome_retries = max(0, min(outcome_retries, 5))
        try:
            outcome_workers = int(os.getenv("ARTICLE_AGENT_OUTCOME_WORKERS", "1"))
        except ValueError:
            outcome_workers = 1
        outcome_workers = max(1, min(outcome_workers, 8))
        try:
            whole_table_timeout = int(os.getenv("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_TIMEOUT", "30"))
        except ValueError:
            whole_table_timeout = 30
        whole_table_timeout = max(10, whole_table_timeout)
        whole_table_first = os.getenv("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_FIRST", "1").strip().lower() not in {
            "0", "false", "no", "off",
        }
        tablewise, tablewise_manifest = extract_outcomes_by_table(
            client,
            table_blocks,
            outcome_raw_dir,
            narrative_hint=narrative_hint,
            retries=outcome_retries,
            max_rows_per_request=outcome_rows_per_request,
            max_workers=outcome_workers,
            request_delay_seconds=outcome_request_delay,
            whole_table_first=whole_table_first,
            whole_table_timeout=whole_table_timeout,
        )
        if os.getenv("ARTICLE_AGENT_ENABLE_NARRATIVE_OUTCOMES", "1").strip().lower() in {"1", "true", "yes"}:
            try:
                narrative_outcomes, narrative_manifest = extract_outcomes_from_results_narrative(
                    client,
                    contexts["outcomes"],
                    outcome_raw_dir / "narrative",
                    retries=outcome_retries,
                    request_delay_seconds=outcome_request_delay,
                )
            except Exception as exc:
                narrative_manifest = [{"status": "failed", "error": str(exc), "source_mode": "results_narrative"}]
        outcomes = merge_outcome_extractions(tablewise, narrative_outcomes, parsed_outcomes)
    else:
        # Explicit fallback for PDFs whose Results contain no reconstructable
        # table (for example a text-only appendix).  It has no document-wide
        # six-row cap; the input is still labeled as a narrative fallback.
        try:
            narrative_outcomes, narrative_manifest = extract_outcomes_from_results_narrative(
                client,
                contexts["outcomes"],
                outcome_raw_dir / "narrative",
                retries=outcome_retries if "outcome_retries" in locals() else 2,
                request_delay_seconds=outcome_request_delay,
            )
            outcomes = merge_outcome_extractions(narrative_outcomes, parsed_outcomes)
            tablewise_manifest = [{
                "table_id": "narrative-fallback",
                "caption": "NR",
                "source": "markdown",
                "row_count": 0,
                "status": "success",
                "outcome_count": len(narrative_outcomes.outcomes),
                "manifest": narrative_manifest,
            }]
        except RuntimeError as exc:
            tablewise_manifest = [{
                "table_id": "narrative-fallback",
                "caption": "NR",
                "source": "markdown",
                "row_count": 0,
                "status": "failed",
                "error": str(exc),
            }]
            outcomes = parsed_outcomes
            if not outcomes.outcomes:
                raise
    # Combine table and Results-narrative request provenance into one root
    # manifest.  Each line is lossless and can be replayed independently.
    request_manifest_paths = [
        outcome_raw_dir / "request_manifest.jsonl",
        outcome_raw_dir / "narrative" / "request_manifest.jsonl",
    ]
    request_lines: list[str] = []
    seen_request_ids: set[str] = set()
    for request_path in request_manifest_paths:
        if not request_path.exists():
            continue
        for line in request_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            request_id = str(item.get("request_id") or "")
            if request_id and request_id in seen_request_ids:
                continue
            if request_id:
                seen_request_ids.add(request_id)
            request_lines.append(json.dumps(item, ensure_ascii=False))
    if request_lines:
        (outcome_raw_dir / "request_manifest.jsonl").write_text(
            "\n".join(request_lines) + "\n", encoding="utf-8"
        )
    (outcome_raw_dir / "outcomes.tablewise.manifest.json").write_text(
        json.dumps({
            "strategy": "llm_table_classification_then_deterministic_header_row_selection_then_rowwise_llm_preserve_raw",
            "document_wide_row_limit": None,
            "table_classification_model": table_classifier_model if table_blocks else None,
            "basic_match_model": os.getenv("ARTICLE_AGENT_BASIC_MATCH_MODEL", "").strip() or None,
            "table_classification_retries": table_classifier_retries if table_blocks else None,
            "table_classification": table_classification_manifest,
            "max_rows_per_request": outcome_rows_per_request if table_blocks else None,
            "max_workers": outcome_workers if table_blocks else None,
            "retries": outcome_retries if table_blocks else None,
            "request_delay_seconds": outcome_request_delay,
            "table_count": len(table_blocks),
            "total_outcomes": len(outcomes.outcomes),
            "tables": tablewise_manifest,
            "narrative": narrative_manifest,
            "narrative_outcome_count": len(narrative_outcomes.outcomes) if "narrative_outcomes" in locals() else 0,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "raw_module_responses" / "outcomes.table-parser.json").write_text(
        outcomes.model_dump_json(indent=2), encoding="utf-8"
    )

    # Post-extraction outcome processing is intentionally separate from the
    # source extraction request.  It may compare to Sheet3 after extraction,
    # but it never overwrites the source OutcomeStatistic values; every record
    # carries a source_index and a lossless source_outcome copy.
    outcome_postprocess_raw_dir = output_dir / "raw_module_responses"
    gold_rows = sheet3_gold(project_root, article_id)
    try:
        postprocess_batch_size = int(os.getenv("ARTICLE_AGENT_OUTCOME_POSTPROCESS_BATCH_SIZE", "1"))
    except ValueError:
        postprocess_batch_size = 1
    try:
        postprocess_workers = int(os.getenv("ARTICLE_AGENT_OUTCOME_POSTPROCESS_WORKERS", "1"))
    except ValueError:
        postprocess_workers = 1
    try:
        postprocess_retries = int(os.getenv("ARTICLE_AGENT_OUTCOME_POSTPROCESS_RETRIES", "2"))
    except ValueError:
        postprocess_retries = 2
    postprocess_retries = max(0, min(postprocess_retries, 5))
    # A shard may contain several complete source records.  It is still sent
    # serially and must return every source_index in the shard; limiting the
    # postprocess stage to one record made a six-article run needlessly slow.
    postprocess_batch_size = max(1, min(postprocess_batch_size, 8))
    postprocess_workers = 1
    try:
        postprocess_timeout = int(os.getenv("ARTICLE_AGENT_OUTCOME_POSTPROCESS_TIMEOUT", str(client.timeout)))
    except ValueError:
        postprocess_timeout = client.timeout
    postprocess_timeout = max(10, min(postprocess_timeout, client.timeout))
    postprocess_client = client
    if postprocess_timeout != client.timeout:
        postprocess_client = OpenAICompatibleClient(
            api_key=client.api_key,
            base_url=client.base_url,
            model=client.model,
            timeout=postprocess_timeout,
        )
    try:
        postprocessed_outcomes, postprocess_manifest = postprocess_outcomes_with_llm(
            postprocess_client,
            outcomes,
            gold_rows,
            contexts["outcomes"],
            outcome_postprocess_raw_dir,
            retries=postprocess_retries,
            batch_size=postprocess_batch_size,
            max_workers=postprocess_workers,
            request_delay_seconds=outcome_request_delay,
        )
    except Exception as exc:  # retain raw extraction even if this optional audit fails
        postprocessed_outcomes = OutcomePostProcessing(
            status="failed",
            source_outcome_count=len(outcomes.outcomes),
            processed_outcome_count=0,
            conflict_count=0,
            duplicate_group_count=0,
            gold_comparison="provided" if gold_rows else "unavailable",
            gold_rows=gold_rows,
            records=[],
            gold_conflicts=[],
            notes=[f"LLM 后处理未完成；原始抽取结果保持不变：{type(exc).__name__}: {exc}"],
        )
        postprocess_manifest = [{"status": "failed", "error": str(exc)}]
    if postprocessed_outcomes.canonical_dataset is None:
        # Even when the optional LLM annotation fails, produce a clearly
        # unresolved evidence-only canonical view.  No source value is changed
        # and no gold value is consulted.
        unresolved_records = [OutcomePostProcessRecord(
            source_index=index,
            source_outcome=outcome,
            normalized_outcome_name="NR",
            normalized_measurement_instrument="NR",
            normalized_timepoint="NR",
            comparison_relation="NR",
            conflict_status="unresolved" if gold_rows else "not_checked",
            conflict_reason="LLM 后处理不可用；canonical 仅按原始证据生成，代表行未确认。",
            processing_status="not_processed",
            value_preserved=True,
        ) for index, outcome in enumerate(outcomes.outcomes)]
        postprocessed_outcomes = postprocessed_outcomes.model_copy(update={
            "canonical_dataset": build_canonical_outcome_dataset(unresolved_records),
        })
    canonical_dataset = postprocessed_outcomes.canonical_dataset
    (output_dir / "outcomes.canonical.json").write_text(
        canonical_dataset.model_dump_json(indent=2), encoding="utf-8"
    )
    (output_dir / "outcomes.postprocessed.json").write_text(
        postprocessed_outcomes.model_dump_json(indent=2), encoding="utf-8"
    )
    (outcome_postprocess_raw_dir / "outcomes.postprocess.manifest.json").write_text(
        json.dumps({
            "strategy": "post_extraction_llm_annotation_with_gold_conflict_preservation",
            "run_id": run_id,
            "model": postprocess_client.model,
            "gold_used_for_extraction": False,
            "gold_used_for_postprocess_comparison": bool(gold_rows),
            "retries": postprocess_retries,
            "batch_size": postprocess_batch_size,
            "max_workers": postprocess_workers,
            "request_delay_seconds": outcome_request_delay,
            "source_outcome_count": len(outcomes.outcomes),
            "processed_outcome_count": postprocessed_outcomes.processed_outcome_count,
            "conflict_count": postprocessed_outcomes.conflict_count,
            "parts": postprocess_manifest,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest["outcome_postprocessing"] = {
        "status": postprocessed_outcomes.status,
        "run_id": run_id,
        "model": postprocess_client.model,
        "source_outcome_count": postprocessed_outcomes.source_outcome_count,
        "processed_outcome_count": postprocessed_outcomes.processed_outcome_count,
        "conflict_count": postprocessed_outcomes.conflict_count,
            "gold_comparison": postprocessed_outcomes.gold_comparison,
            "canonical_dataset": "outcomes.canonical.json",
            "canonical_outcome_count": canonical_dataset.canonical_outcome_count,
            "canonical_conflict_group_count": canonical_dataset.conflict_group_count,
        }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    flow = None
    if use_vlm:
        image, page = render_figure_one_page(pdf, output_dir / "figure-1-page.png")
        try:
            cached_flow = output_dir / "raw_module_responses" / "consort_flow.json"
            raw_flow = json.loads(cached_flow.read_text(encoding="utf-8")) if cached_flow.exists() else extract_flow(client, image, article_id)
            (output_dir / "raw_module_responses" / "consort_flow.json").write_text(
                json.dumps(raw_flow, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            flow = ConsortFlowExtraction.model_validate(raw_flow)
            for evidence in flow.evidence:
                evidence.page = evidence.page or page
            flow = reconcile_flow(flow, markdown)
        except (RuntimeError, ValueError) as exc:
            (output_dir / "raw_module_responses" / "consort_flow.error.txt").write_text(str(exc), encoding="utf-8")

    risk = _reconcile_risk_with_flow(risk, flow)

    bundle = ExtractionBundle(
        article_id=article_id,
        parser_backend=backend,
        metadata=metadata,
        acupuncture=acupuncture,
        risk_of_bias=risk,
        outcomes=outcomes,
        consort_flow=flow,
        cross_check_issues=cross_check(risk, flow),
    )
    (output_dir / "extraction.json").write_text(
        bundle.model_dump_json(indent=2), encoding="utf-8"
    )
    return bundle
