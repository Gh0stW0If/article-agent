from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langgraph.graph import END, StateGraph

from .api_extract import api_refine_study
from .arms_agent import extract_arms
from .evaluation import build_evaluation_rows, write_evaluation_summary
from .excel import write_workbook
from .extract import build_acupuncture_record, build_method_record, build_review, collect_evidence, derive_related_records, extract_study
from .paths import ARTICLES_DIR, OUTPUTS_DIR, TEMPLATE_PATH
from .legacy_sheet1 import build_legacy_sheet1_records_from_optimized, find_legacy_sheet1_template, write_legacy_sheet1
from .metadata import enrich_study_metadata
from .pdf import infer_study_id, parse_pdf
from .document_pipeline import parse_pdf_hybrid
from .reports import write_evidence_report, write_json, write_run_log
from .schemas import RunState
from .storage import write_log, write_record, write_run
from .study_metadata_agent import complete_study_metadata


def discover_articles(state: RunState) -> RunState:
    if state.article_id:
        candidates = list(ARTICLES_DIR.glob(f"**/*{state.article_id}*.pdf"))
    elif state.year:
        candidates = sorted((ARTICLES_DIR / state.year).glob("*.pdf"))
    else:
        candidates = sorted(ARTICLES_DIR.glob("**/*.pdf"))[:1]
    state.pdf_paths = [p for p in candidates if p.is_file()]
    state.logs.append({"event": "discover_articles", "count": len(state.pdf_paths), "article_id": state.article_id, "year": state.year})
    return state


def parse_documents(state: RunState) -> RunState:
    for path in state.pdf_paths:
        if state.document_backend == "pymupdf":
            parsed = parse_pdf(path, use_vision=state.use_api)
        else:
            forced = state.document_backend if state.document_backend in {"docling", "mineru"} else None
            parsed, route, normalized = parse_pdf_hybrid(
                path,
                force_backend=forced,
                use_vision=state.use_api,
                output_dir=OUTPUTS_DIR / "hybrid_documents" / infer_study_id(path),
            )
            state.document_routes.append(route.model_dump(mode="json"))
            state.normalized_documents.append(normalized.model_dump(mode="json"))
            state.logs.append({
                "event": "document_route",
                "study_id": parsed.study_id,
                "preferred_backend": route.preferred_backend,
                "effective_backend": route.effective_backend,
                "fallback_used": route.fallback_used,
                "reason_codes": route.reason_codes,
                "optional_backends": route.optional_backends,
            })
        state.parsed_documents.append(parsed)
        state.logs.append({"event": "parse_document", "study_id": parsed.study_id, "pages": parsed.page_count, "chunks": len(parsed.chunks), "warnings": parsed.warnings, "document_backend": state.document_backend})
    return state


def extract_records(state: RunState) -> RunState:
    for doc in state.parsed_documents:
        study = extract_study(doc)
        api_info = {"api_status": "not_requested"}
        if state.use_api:
            try:
                study, api_info = api_refine_study(doc, study)
                api_info["api_status"] = "api_used"
                state.api_status = "api_used"
            except Exception as exc:
                api_info = {"api_status": "api_error", "error": str(exc)}
                state.api_status = "api_error"
        study, metadata_info = enrich_study_metadata(doc, study, use_external=state.use_api)
        api_info.update(metadata_info)
        study, study_meta_info = complete_study_metadata(doc, study, use_api=state.use_api)
        api_info.update(study_meta_info)
        arms, arms_info = extract_arms(doc, study, use_api=state.use_api)
        api_info.update(arms_info)
        arms, comparisons, outcomes = derive_related_records(study, arms)
        methods = build_method_record(doc)
        acupuncture = build_acupuncture_record(doc, study, arms[0].arm_id if arms else f"{study.study_id}_A1")
        evidence = collect_evidence(study)
        review = build_review(study, evidence)
        state.studies.append(study)
        state.arms.extend(arms)
        state.comparisons.extend(comparisons)
        state.outcomes.extend(outcomes)
        state.methods.append(methods)
        state.acupuncture.append(acupuncture)
        state.evidence.extend(evidence)
        state.review.extend(review)
        state.logs.append({"event": "extract_records", "study_id": study.study_id, "evidence": len(evidence), "review": len(review), "methods": 1, "acupuncture": 1, **api_info})
    return state


def write_outputs(state: RunState) -> RunState:
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out = OUTPUTS_DIR / run_id
    state.output_dir = out
    out.mkdir(parents=True, exist_ok=True)
    parsed_path = out / "parsed_document.json"
    parsed_path.write_text(json.dumps([doc.model_dump(mode="json") for doc in state.parsed_documents], ensure_ascii=False, indent=2), encoding="utf-8")
    if state.document_routes:
        (out / "document_routes.json").write_text(json.dumps(state.document_routes, ensure_ascii=False, indent=2), encoding="utf-8")
    if state.normalized_documents:
        (out / "normalized_documents.json").write_text(json.dumps(state.normalized_documents, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path = write_json(out / "extracted_structured.json", state.studies, state.evidence, state.review)
    report_path = write_evidence_report(out / "evidence_report.md", state.studies)
    evaluation_rows = build_evaluation_rows(state)
    evaluation_path = write_evaluation_summary(out / "evaluation_framework.json", state, evaluation_rows)
    excel_path = write_workbook(TEMPLATE_PATH, out / "extracted.xlsx", state.studies, state.arms, state.comparisons, state.outcomes, state.evidence, state.review, state.methods, state.acupuncture, evaluation_rows)
    legacy_records = build_legacy_sheet1_records_from_optimized(excel_path)
    state.legacy_sheet1 = legacy_records
    legacy_template = find_legacy_sheet1_template(state.year or (state.studies[0].study_id[:4] if state.studies else None))
    legacy_path = write_legacy_sheet1(legacy_template, out / "legacy_sheet1_auto.xlsx", legacy_records)
    log_path = write_run_log(out / "run_log.jsonl", state.logs)
    db_path = out / "article_agent.sqlite"
    db_status = "ok"
    try:
        write_run(db_path, run_id, state.created_at.isoformat(), "completed", {"article_count": len(state.studies)})
        for s in state.studies:
            write_record(db_path, run_id, "study", s.study_id, s.model_dump(mode="json"))
        for ev in state.evidence:
            write_record(db_path, run_id, "evidence", ev.evidence_id, ev.model_dump(mode="json"))
        for row in state.logs:
            write_log(db_path, run_id, row)
    except Exception as exc:
        db_status = f"failed: {exc}"
    state.logs.append({"event": "write_outputs", "output_dir": str(out), "parsed_document": str(parsed_path), "json": str(json_path), "evidence_report": str(report_path), "excel": str(excel_path), "evaluation": str(evaluation_path), "evaluation_rows": len(evaluation_rows), "legacy_sheet1": str(legacy_path), "legacy_sheet1_records": len(legacy_records), "log": str(log_path), "db": str(db_path), "db_status": db_status})
    write_run_log(out / "run_log.jsonl", state.logs)
    return state


def build_graph():
    graph = StateGraph(RunState)
    graph.add_node("discover_articles", discover_articles)
    graph.add_node("parse_documents", parse_documents)
    graph.add_node("extract_records", extract_records)
    graph.add_node("write_outputs", write_outputs)
    graph.set_entry_point("discover_articles")
    graph.add_edge("discover_articles", "parse_documents")
    graph.add_edge("parse_documents", "extract_records")
    graph.add_edge("extract_records", "write_outputs")
    graph.add_edge("write_outputs", END)
    return graph.compile()


def run_pipeline(
    year: str | None = None,
    article_id: str | None = None,
    use_api: bool = False,
    document_backend: str = "pymupdf",
) -> RunState:
    app = build_graph()
    initial = RunState(year=year, article_id=article_id, use_api=use_api, document_backend=document_backend)
    result = app.invoke(initial)
    return RunState.model_validate(result)



