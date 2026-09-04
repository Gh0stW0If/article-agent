"""Recover an interrupted article without replaying unrelated modules.

This utility is intentionally narrow: it reconstructs the lossless table and
Results-narrative outcome stages from the article Markdown, reuses any valid
structured-module attempts already on disk, and writes a complete
``ExtractionBundle``.  It is used after a network interruption has left raw
row shards but no article-level ``extraction.json``.  No Gold value is copied
into the source outcome records.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from article_agent.models import OpenAICompatibleClient

from mineru_method.bibliography import enrich_metadata
from mineru_method.canonical import build_canonical_outcome_dataset
from mineru_method.flow import cross_check, reconcile_flow, render_figure_one_page
from mineru_method.gold import sheet3_gold
from mineru_method.llm import (
    ValidatedExtractor,
    classify_outcome_tables_with_llm,
    extract_flow,
    extract_outcomes_by_table,
    extract_outcomes_from_results_narrative,
    merge_outcome_extractions,
    postprocess_outcomes_with_llm,
)
from mineru_method.pipeline import _normalize_acupuncture, _normalize_primary_analysis
from mineru_method.prompts import PROMPT_SPECS
from mineru_method.routing import contexts_for_modules
from mineru_method.schemas import (
    AcupunctureProtocol,
    ConsortFlowExtraction,
    ExtractionBundle,
    MetadataExtraction,
    OutcomeExtraction,
    OutcomePostProcessRecord,
    OutcomePostProcessing,
    RiskOfBiasExtraction,
)
from mineru_method.table_parser import extract_outcome_table_blocks, parse_primary_painvas


def read_json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() not in {"0", "false", "no", "off"}


def env_int(name: str, default: int, minimum: int = 0, maximum: int = 10_000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def delay_seconds() -> float:
    try:
        value = float(os.getenv("ARTICLE_AGENT_OUTCOME_REQUEST_DELAY_SECONDS", "0.01"))
    except ValueError:
        value = 0.01
    return max(0.0, min(value, 60.0))


def latest_model(path: Path, pattern: str, model):
    for candidate in sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            return model.model_validate_json(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
    return None


def structured_modules(article_dir: Path, markdown: str, client: OpenAICompatibleClient):
    """Load valid attempts; call sol only for a genuinely missing module."""

    raw_dir = article_dir / "raw_module_responses"
    metadata = latest_model(raw_dir, "metadata.attempt-*.json", MetadataExtraction)
    acupuncture = latest_model(raw_dir, "acupuncture.attempt-*.json", AcupunctureProtocol)
    risk = latest_model(raw_dir, "risk_of_bias.attempt-*.json", RiskOfBiasExtraction)
    contexts = contexts_for_modules(markdown)
    extractor = ValidatedExtractor(client, raw_dir / "structured_recovery", retries=0)
    failures: dict[str, str] = {}

    def recover(name, schema):
        try:
            time.sleep(delay_seconds())
            return extractor.extract(name, schema, contexts[name], PROMPT_SPECS[name])
        except Exception as exc:  # keep outcome recovery independent
            failures[name] = f"{type(exc).__name__}: {exc}"
            return schema()

    if metadata is None:
        metadata = recover("metadata", MetadataExtraction)
    if acupuncture is None:
        acupuncture = recover("acupuncture", AcupunctureProtocol)
    if risk is None:
        risk = recover("risk_of_bias", RiskOfBiasExtraction)
    try:
        metadata, _ = enrich_metadata(metadata, markdown, article_dir / "bibliographic_lookup.json")
    except Exception as exc:
        failures.setdefault("bibliographic_lookup", f"{type(exc).__name__}: {exc}")
    acupuncture = _normalize_acupuncture(acupuncture, contexts["acupuncture"])
    risk = _normalize_primary_analysis(risk, contexts["risk_of_bias"])
    return metadata, acupuncture, risk, failures


def postprocess(
    article_dir: Path,
    outcomes: OutcomeExtraction,
    contexts: dict[str, str],
    client: OpenAICompatibleClient,
) -> tuple[OutcomePostProcessing, list[dict]]:
    raw_dir = article_dir / "raw_module_responses"
    gold_rows = sheet3_gold(ROOT, article_dir.name)
    batch_size = env_int("ARTICLE_AGENT_OUTCOME_POSTPROCESS_BATCH_SIZE", 8, 1, 8)
    retries = env_int("ARTICLE_AGENT_OUTCOME_POSTPROCESS_RETRIES", 0, 0, 5)
    try:
        result, manifest = postprocess_outcomes_with_llm(
            client,
            outcomes,
            gold_rows,
            contexts["outcomes"],
            raw_dir,
            retries=retries,
            batch_size=batch_size,
            max_workers=1,
            request_delay_seconds=delay_seconds(),
        )
    except Exception as exc:
        result = OutcomePostProcessing(
            status="failed",
            source_outcome_count=len(outcomes.outcomes),
            processed_outcome_count=0,
            conflict_count=0,
            duplicate_group_count=0,
            gold_comparison="provided" if gold_rows else "unavailable",
            gold_rows=gold_rows,
            records=[],
            gold_conflicts=[],
            notes=[f"LLM 后处理失败；原始记录保留：{type(exc).__name__}: {exc}"],
        )
        manifest = [{"status": "failed", "error": str(exc)}]
    if result.canonical_dataset is None:
        unresolved = [
            OutcomePostProcessRecord(
                source_index=index,
                source_outcome=outcome,
                normalized_outcome_name="NR",
                normalized_measurement_instrument="NR",
                normalized_timepoint="NR",
                comparison_relation="NR",
                conflict_status="unresolved" if gold_rows else "not_checked",
                conflict_reason="LLM 后处理不可用；canonical 仅按原始证据生成。",
                processing_status="not_processed",
                value_preserved=True,
            )
            for index, outcome in enumerate(outcomes.outcomes)
        ]
        result = result.model_copy(update={"canonical_dataset": build_canonical_outcome_dataset(unresolved)})
    write_json(article_dir / "outcomes.postprocessed.json", result.model_dump(mode="json"))
    write_json(article_dir / "outcomes.canonical.json", result.canonical_dataset.model_dump(mode="json"))
    write_json(raw_dir / "outcomes.postprocess.manifest.json", {
        "strategy": "post_extraction_llm_annotation_with_gold_conflict_preservation",
        "gold_used_for_extraction": False,
        "gold_used_for_postprocess_comparison": bool(gold_rows),
        "model": client.model,
        "batch_size": batch_size,
        "max_workers": 1,
        "request_delay_seconds": delay_seconds(),
        "source_outcome_count": result.source_outcome_count,
        "processed_outcome_count": result.processed_outcome_count,
        "conflict_count": result.conflict_count,
        "parts": manifest,
    })
    return result, manifest


def recover_article(article_dir: Path, outcome_client: OpenAICompatibleClient, classifier_client: OpenAICompatibleClient) -> dict:
    markdown_path = article_dir / "article.md"
    if not markdown_path.exists():
        return {"status": "failed", "error": "missing article.md"}
    markdown = markdown_path.read_text(encoding="utf-8")
    contexts = contexts_for_modules(markdown)
    raw_dir = article_dir / "raw_module_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    metadata, acupuncture, risk, module_failures = structured_modules(article_dir, markdown, outcome_client)

    blocks = extract_outcome_table_blocks(contexts["outcomes"], defer_classification=True)
    classifier_model = classifier_client.model
    classification_manifest: list[dict] = []
    if blocks:
        blocks, classification_manifest = classify_outcome_tables_with_llm(
            classifier_client,
            blocks,
            raw_dir,
            narrative_hint=contexts["outcomes"],
            retries=env_int("ARTICLE_AGENT_TABLE_CLASSIFIER_RETRIES", 0, 0, 5),
            request_delay_seconds=delay_seconds(),
        )
    max_rows = env_int("ARTICLE_AGENT_OUTCOME_ROWS_PER_REQUEST", 1, 1, 12)
    whole_first = env_bool("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_FIRST", True)
    whole_timeout = env_int("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_TIMEOUT", 30, 10, 600)
    tablewise, table_manifest = extract_outcomes_by_table(
        outcome_client,
        blocks,
        raw_dir,
        narrative_hint=contexts["outcomes"],
        retries=env_int("ARTICLE_AGENT_OUTCOME_RETRIES", 0, 0, 5),
        max_rows_per_request=max_rows,
        max_workers=1,
        request_delay_seconds=delay_seconds(),
        whole_table_first=whole_first,
        whole_table_timeout=whole_timeout,
    )
    narrative = OutcomeExtraction(outcomes=[])
    narrative_manifest: list[dict] = []
    if env_bool("ARTICLE_AGENT_ENABLE_NARRATIVE_OUTCOMES", True):
        try:
            narrative, narrative_manifest = extract_outcomes_from_results_narrative(
                outcome_client,
                contexts["outcomes"],
                raw_dir / "narrative",
                retries=env_int("ARTICLE_AGENT_OUTCOME_RETRIES", 0, 0, 5),
                request_delay_seconds=delay_seconds(),
            )
        except Exception as exc:
            narrative_manifest = [{"status": "failed", "error": str(exc), "source_mode": "results_narrative"}]
    outcomes = merge_outcome_extractions(tablewise, narrative, parse_primary_painvas(contexts["outcomes"]))
    # Merge request manifests from the table and narrative stages without
    # dropping a request or changing its declared row coverage.
    lines: list[str] = []
    seen: set[str] = set()
    for path in (raw_dir / "request_manifest.jsonl", raw_dir / "narrative" / "request_manifest.jsonl"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            request_id = str(item.get("request_id") or "")
            if request_id and request_id in seen:
                continue
            if request_id:
                seen.add(request_id)
            lines.append(json.dumps(item, ensure_ascii=False))
    if lines:
        (raw_dir / "request_manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    tablewise_payload = {
        "strategy": "llm_table_classification_then_deterministic_header_row_selection_then_rowwise_llm_preserve_raw",
        "document_wide_row_limit": None,
        "table_classification_model": classifier_model if blocks else None,
        "table_classification": classification_manifest,
        "max_rows_per_request": max_rows,
        "whole_table_first": whole_first,
        "whole_table_timeout": whole_timeout,
        "max_workers": 1,
        "retries": env_int("ARTICLE_AGENT_OUTCOME_RETRIES", 0, 0, 5),
        "request_delay_seconds": delay_seconds(),
        "table_count": len(blocks),
        "total_outcomes": len(outcomes.outcomes),
        "tables": table_manifest,
        "narrative": narrative_manifest,
        "narrative_outcome_count": len(narrative.outcomes),
        "module_failures": module_failures,
    }
    write_json(raw_dir / "outcomes.tablewise.manifest.json", tablewise_payload)
    write_json(raw_dir / "outcomes.table-parser.json", outcomes.model_dump(mode="json"))
    postprocessed, postprocess_manifest = postprocess(article_dir, outcomes, contexts, outcome_client)

    flow = None
    try:
        image, page = render_figure_one_page(Path(read_json(article_dir / "manifest.json", {}).get("source_pdf", "")), article_dir / "figure-1-page.png")
        flow_raw_path = raw_dir / "consort_flow.json"
        raw_flow = read_json(flow_raw_path)
        if raw_flow is None:
            raw_flow = extract_flow(classifier_client, image, article_dir.name)
            write_json(flow_raw_path, raw_flow)
        flow = ConsortFlowExtraction.model_validate(raw_flow)
        flow = reconcile_flow(flow, markdown)
    except Exception as exc:
        (raw_dir / "consort_flow.error.txt").write_text(str(exc), encoding="utf-8")

    extraction = ExtractionBundle(
        article_id=article_dir.name,
        parser_backend=str((read_json(article_dir / "manifest.json", {}) or {}).get("parser_backend") or "provided-markdown"),
        metadata=metadata,
        acupuncture=acupuncture,
        risk_of_bias=risk,
        outcomes=outcomes,
        consort_flow=flow,
        cross_check_issues=cross_check(risk, flow),
    )
    write_json(article_dir / "extraction.json", extraction.model_dump(mode="json"))
    manifest = read_json(article_dir / "manifest.json", {}) or {}
    manifest.update({
        "structured_module_model": outcome_client.model,
        "outcome_postprocessing": {
            "status": postprocessed.status,
            "source_outcome_count": postprocessed.source_outcome_count,
            "processed_outcome_count": postprocessed.processed_outcome_count,
            "conflict_count": postprocessed.conflict_count,
            "canonical_dataset": "outcomes.canonical.json",
            "canonical_outcome_count": postprocessed.canonical_dataset.canonical_outcome_count,
            "canonical_conflict_group_count": postprocessed.canonical_dataset.conflict_group_count,
        },
        "recovery_utility": "recover_outcomes_only.py",
    })
    write_json(article_dir / "manifest.json", manifest)
    return {
        "status": "success",
        "article_id": article_dir.name,
        "outcome_count": len(outcomes.outcomes),
        "narrative_outcome_count": len(narrative.outcomes),
        "table_count": len(blocks),
        "postprocessed_status": postprocessed.status,
        "module_failures": module_failures,
        "postprocess_parts": len(postprocess_manifest),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Recover lossless outcomes for articles with interrupted article-level extraction")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--articles", nargs="*", default=None)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    run_id_path = output_root / "RUN_ID.txt"
    if "ARTICLE_AGENT_RUN_ID" not in os.environ and run_id_path.exists():
        os.environ["ARTICLE_AGENT_RUN_ID"] = run_id_path.read_text(encoding="utf-8", errors="replace").strip()
    requested = {str(value).lstrip("-") for value in args.articles} if args.articles else None
    article_dirs = [path for path in sorted(output_root.glob("2015-*")) if path.is_dir() and (requested is None or path.name in requested)]
    timeout = env_int("ARTICLE_AGENT_API_TIMEOUT", 30, 10, 600)
    outcome_client = OpenAICompatibleClient(timeout=timeout, model=os.getenv("ARTICLE_AGENT_MODEL") or "gpt-5.6-sol")
    classifier_client = OpenAICompatibleClient(
        api_key=outcome_client.api_key,
        base_url=outcome_client.base_url,
        timeout=env_int("ARTICLE_AGENT_TABLE_CLASSIFIER_TIMEOUT", timeout, 10, 600),
        model=os.getenv("ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL") or "gpt-5.6-luna",
    )
    summary = {"strategy": "recover_outcomes_only_lossless", "outcome_model": outcome_client.model, "classifier_model": classifier_client.model, "articles": {}}
    for article_dir in article_dirs:
        try:
            summary["articles"][article_dir.name] = recover_article(article_dir, outcome_client, classifier_client)
        except Exception as exc:
            summary["articles"][article_dir.name] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    write_json(output_root / "RECOVER_OUTCOMES_ONLY_SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(item.get("status") == "success" for item in summary["articles"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
