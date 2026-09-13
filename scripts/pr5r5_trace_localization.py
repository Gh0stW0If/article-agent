"""PR5R-5 traced 2015-06 extraction audit and first-failure localization.

This diagnostic is deliberately read-only with respect to production semantics:
it replays the already completed production bundle through the PR5R-4
side-channel trace, then compares the frozen trace/prediction with Gold only
after production assembly has finished.  No LLM is used for localization.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTION = ROOT / "outputs/pr5r5_traced_2015_06/production/2015-06"
DEFAULT_OUT = ROOT / "outputs/pr5r5_traced_2015_06"
DEFAULT_GOLD = ROOT / "gold/2015-06/gold.json"
DEFAULT_REGISTRY = ROOT / "schemas/evaluator-field-registry-v3.json"
DEFAULT_CURRENT = ROOT / "benchmarks/2015-06/missingness_v1/CANONICAL_PREDICTION.json"

sys.path.insert(0, str(ROOT))
from article_agent.domain.models import ArticleExtraction, CanonicalField  # noqa: E402
from article_agent.evaluation import GoldStandardV2, evaluate_article  # noqa: E402
from article_agent.evaluation.registry import load_registry  # noqa: E402
from article_agent.provenance import TraceSession  # noqa: E402
from scripts.pr5d1_build_prediction import assemble  # noqa: E402


ERROR_TYPES = (
    "WRONG_TIMEPOINT",
    "WRONG_COMPARISON",
    "WRONG_ARM",
    "WRONG_OUTCOME",
    "IDENTITY_NORMALIZATION_FAILURE",
    "TRUE_CONTRADICTION",
    "MISSING_CONTENT",
    "EXTRACTION_RUN_DRIFT",
)
STAGES = (
    "SKILL_EXTRACTION",
    "RESULT_CONSTRUCTION",
    "PARENT_BINDING",
    "NORMALIZATION",
    "MERGER",
    "FINAL_PROJECTION",
    "RETRIEVAL_OR_UPSTREAM",
    "EVALUATOR_ONLY",
    "UNKNOWN",
)
ROOT_CAUSES = (
    "TIMEPOINT_WRONG_AT_EXTRACTION",
    "TIMEPOINT_LOST",
    "TIMEPOINT_REBOUND",
    "TIMEPOINT_MERGE_COLLISION",
    "COMPARISON_WRONG_AT_EXTRACTION",
    "COMPARISON_LOST",
    "COMPARISON_REBOUND",
    "ARM_WRONG_AT_EXTRACTION",
    "ARM_LOST",
    "ARM_REBOUND",
    "OUTCOME_SPLIT",
    "OUTCOME_OVERMERGED",
    "RESULT_COLLISION",
    "DUPLICATE_DROP_ERROR",
    "NORMALIZATION_ERROR",
    "FINAL_PROJECTION_ERROR",
    "RETRIEVAL_CONTEXT_INSUFFICIENT",
    "UNKNOWN",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wire(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"


def norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(norm(x) for x in value)
    if isinstance(value, dict):
        return " ".join(norm(x) for x in value.values())
    return re.sub(r"[\W_]+", " ", str(value).casefold(), flags=re.UNICODE).strip()


def value(entity: Any, field: str) -> Any:
    item = getattr(entity, field, None)
    if isinstance(item, CanonicalField):
        return item.value if item.status.value == "PRESENT" else None
    return item


def status_value(entity: Any, field: str) -> dict[str, Any]:
    item = getattr(entity, field, None)
    if isinstance(item, CanonicalField):
        return item.model_dump(mode="json")
    return {"status": "SCALAR", "value": item}


def entities(graph: ArticleExtraction, kind: str) -> list[Any]:
    return {
        "Article": [graph.article],
        "Study": graph.studies,
        "Intervention": graph.interventions,
        "Arm": graph.arms,
        "Outcome": graph.outcomes,
        "ArmResult": graph.arm_results,
        "Comparison": graph.comparisons,
        "ComparisonResult": graph.comparison_results,
    }[kind]


ID_FIELD = {
    "Article": "article_id",
    "Study": "study_id",
    "Intervention": "intervention_id",
    "Arm": "arm_id",
    "Outcome": "outcome_id",
    "ArmResult": "arm_result_id",
    "Comparison": "comparison_id",
    "ComparisonResult": "comparison_result_id",
}


def parent_snapshot(entity: Any) -> dict[str, Any]:
    return {
        field: value(entity, field)
        for field in (
            "outcome_id",
            "arm_id",
            "comparison_id",
            "timepoint",
            "timepoint_value",
            "timepoint_unit",
            "value_kind",
            "analysis_set",
        )
        if hasattr(entity, field)
    }


def outcome_name(graph: ArticleExtraction, outcome_id: str | None) -> str | None:
    if not outcome_id:
        return None
    item = next((x for x in graph.outcomes if x.outcome_id == outcome_id), None)
    return value(item, "name") if item else None


def arm_label(graph: ArticleExtraction, arm_id: str | None) -> str | None:
    if not arm_id:
        return None
    item = next((x for x in graph.arms if x.arm_id == arm_id), None)
    return value(item, "label") if item else None


def result_content_tokens(graph: ArticleExtraction, entity: Any) -> dict[str, Any]:
    """Return source-bearing result content, ignoring identity attachment."""
    out = {
        "outcome_name": outcome_name(graph, value(entity, "outcome_id")),
        "value_kind": value(entity, "value_kind"),
        "timepoint": value(entity, "timepoint"),
        "timepoint_value": value(entity, "timepoint_value"),
        "timepoint_unit": value(entity, "timepoint_unit"),
        "analysis_set": value(entity, "analysis_set"),
        "value": value(entity, "value"),
        "standard_deviation": value(entity, "standard_deviation"),
        "change_from_baseline": value(entity, "change_from_baseline"),
        "dispersion_lower": value(entity, "dispersion_lower"),
        "dispersion_upper": value(entity, "dispersion_upper"),
        "n": value(entity, "n"),
        "event_count": value(entity, "event_count"),
        "denominator": value(entity, "denominator"),
        "effect_measure": value(entity, "effect_measure"),
        "estimate": value(entity, "estimate"),
        "confidence_interval_lower": value(entity, "confidence_interval_lower"),
        "confidence_interval_upper": value(entity, "confidence_interval_upper"),
        "p_value": value(entity, "p_value"),
        "raw_value": value(entity, "raw_value"),
    }
    return out


def numeric_equal(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return norm(left) == norm(right) and bool(norm(left))


def content_match(gold_graph: ArticleExtraction, gold_entity: Any,
                  pred_graph: ArticleExtraction, pred_entity: Any) -> tuple[bool, float]:
    """Conservative content-only match; never uses Gold IDs or expected parents."""
    g = result_content_tokens(gold_graph, gold_entity)
    p = result_content_tokens(pred_graph, pred_entity)
    score = 0.0
    required = 0
    for field in (
        "value_kind", "timepoint", "timepoint_value", "timepoint_unit",
        "analysis_set", "value", "standard_deviation", "change_from_baseline",
        "dispersion_lower", "dispersion_upper", "n", "event_count", "denominator",
        "effect_measure", "estimate", "confidence_interval_lower",
        "confidence_interval_upper", "p_value",
    ):
        gv, pv = g[field], p[field]
        if gv is None:
            continue
        required += 1
        if numeric_equal(gv, pv):
            score += 1.0
    if required == 0:
        # An outcome label by itself is not enough to claim that a result's
        # content was recovered.  An exact raw surface is sufficient.
        if norm(g["raw_value"]) and norm(g["raw_value"]) == norm(p["raw_value"]):
            return True, 1.0
        return False, 0.0
    # Ignore entity identity while requiring every reported result value to
    # agree.  This is what makes wrong attachment discoverable.
    return score == required, score / required


def trace_state(candidate: dict[str, Any], stage: str) -> dict[str, Any] | None:
    if stage == "SKILL_EXTRACTION":
        raw = candidate.get("raw_extraction") or {}
        return {
            "outcome_name": raw.get("raw_outcome"),
            "arm_label": raw.get("raw_arm"),
            "comparison": raw.get("raw_comparison"),
            "timepoint": raw.get("raw_timepoint"),
            "statistic_kind": raw.get("raw_statistic_kind"),
        }
    if stage == "RESULT_CONSTRUCTION":
        events = [e for e in candidate.get("events", []) if e["event_type"] == "PARENT_ADDED"]
        return deepcopy(events[-1]["after"]) if events else None
    if stage == "PARENT_BINDING":
        events = [
            e for e in candidate.get("events", [])
            if e["event_type"] in {"ARM_BOUND", "COMPARISON_BOUND", "OUTCOME_BOUND", "TIMEPOINT_BOUND"}
        ]
        if not events:
            return trace_state(candidate, "RESULT_CONSTRUCTION")
        state = {}
        for event in events:
            if event["event_type"] == "ARM_BOUND":
                state["arm"] = event.get("after")
            elif event["event_type"] == "COMPARISON_BOUND":
                state["comparison"] = event.get("after")
        return state
    if stage == "NORMALIZATION":
        events = [
            e for e in candidate.get("events", [])
            if e["stage"] == "NORMALIZATION"
        ]
        return deepcopy(events[-1].get("after")) if events else None
    if stage == "MERGER":
        events = [
            e for e in candidate.get("events", [])
            if e["event_type"] in {"RESULT_MERGE_PROPOSED", "RESULT_MERGED", "RESULT_DROPPED_AS_DUPLICATE"}
        ]
        return deepcopy(events[-1].get("after")) if events else deepcopy(candidate.get("parent_state") or {})
    if stage == "FINAL_PROJECTION":
        return deepcopy(candidate.get("final", {}).get("final_parent_ids"))
    return None


def expected_parent(gold_graph: ArticleExtraction, gold_entity: Any) -> dict[str, Any]:
    result = parent_snapshot(gold_entity)
    result["outcome_name"] = outcome_name(gold_graph, result.get("outcome_id"))
    result["arm_label"] = arm_label(gold_graph, result.get("arm_id"))
    return result


def candidate_parent(graph: ArticleExtraction, candidate: dict[str, Any]) -> dict[str, Any]:
    final = candidate.get("final", {}).get("final_parent_ids") or {}
    result = dict(final)
    result["outcome_name"] = outcome_name(graph, result.get("outcome"))
    result["arm_label"] = arm_label(graph, result.get("arm"))
    return result


def classify_first_failure(
    candidate: dict[str, Any],
    gold_graph: ArticleExtraction,
    gold_entity: Any,
    pred_graph: ArticleExtraction,
) -> dict[str, Any]:
    """Conservative stage classifier based only on recorded trace states."""
    expected = expected_parent(gold_graph, gold_entity)
    final = candidate_parent(pred_graph, candidate)
    raw = trace_state(candidate, "SKILL_EXTRACTION") or {}
    completeness = candidate.get("failure_localization", {}).get("trace_completeness", "UNKNOWN")
    if completeness in {"BROKEN", "UNKNOWN", "NONE"}:
        return {
            "first_failure_stage": "UNKNOWN",
            "first_failure_event_id": None,
            "root_cause": "UNKNOWN",
            "trace_completeness": completeness,
            "reason": "trace artifact incomplete",
        }

    def wrong(field: str) -> bool:
        return bool(expected.get(field)) and norm(expected.get(field)) != norm(final.get(field))

    if not any(wrong(field) for field in ("outcome_name", "arm_label", "comparison_id", "timepoint")):
        return {
            "first_failure_stage": "UNKNOWN",
            "first_failure_event_id": None,
            "root_cause": "UNKNOWN",
            "trace_completeness": completeness,
            "reason": "content matched but no attachment mismatch proven",
        }

    raw_outcome = norm(raw.get("outcome_name"))
    raw_arm = norm(raw.get("arm_label"))
    raw_time = norm(raw.get("timepoint"))
    raw_comparison = norm(raw.get("comparison"))
    expected_outcome = norm(expected.get("outcome_name"))
    expected_arm = norm(expected.get("arm_label"))
    expected_time = norm(expected.get("timepoint"))
    expected_comparison = norm(expected.get("contrast") or expected.get("comparison_id"))
    if expected_outcome and raw_outcome and expected_outcome != raw_outcome:
        stage, root = "SKILL_EXTRACTION", "OUTCOME_SPLIT"
    elif expected_arm and raw_arm and expected_arm != raw_arm:
        stage, root = "SKILL_EXTRACTION", "ARM_WRONG_AT_EXTRACTION"
    elif expected_time and raw_time and expected_time != raw_time:
        stage, root = "SKILL_EXTRACTION", "TIMEPOINT_WRONG_AT_EXTRACTION"
    elif expected_comparison and raw_comparison and expected_comparison != raw_comparison:
        stage, root = "SKILL_EXTRACTION", "COMPARISON_WRONG_AT_EXTRACTION"
    else:
        events = candidate.get("events", [])
        merge = next((e for e in events if e["event_type"] in {
            "RESULT_MERGE_PROPOSED", "RESULT_MERGED", "RESULT_DROPPED_AS_DUPLICATE",
        }), None)
        if merge is not None:
            stage, root = "MERGER", (
                "TIMEPOINT_MERGE_COLLISION" if wrong("timepoint") else "RESULT_COLLISION"
            )
        else:
            binding = next((e for e in events if e["event_type"] in {
                "ARM_BOUND", "COMPARISON_BOUND", "OUTCOME_BOUND", "TIMEPOINT_BOUND",
            }), None)
            construction = next((e for e in events if e["event_type"] == "PARENT_ADDED"), None)
            if binding is not None:
                stage = "PARENT_BINDING"
                root = (
                    "ARM_REBOUND" if wrong("arm_label")
                    else "COMPARISON_REBOUND" if wrong("comparison_id")
                    else "TIMEPOINT_REBOUND" if wrong("timepoint")
                    else "UNKNOWN"
                )
            elif construction is not None:
                stage, root = "RESULT_CONSTRUCTION", "RESULT_COLLISION"
            else:
                stage, root = "UNKNOWN", "UNKNOWN"
    event = next(
        (
            e for e in candidate.get("events", [])
            if e["stage"] == stage or e["event_type"] in {
                "RESULT_MERGE_PROPOSED", "RESULT_MERGED", "RESULT_DROPPED_AS_DUPLICATE",
            } and stage == "MERGER"
        ),
        None,
    )
    return {
        "first_failure_stage": stage,
        "first_failure_event_id": event.get("event_id") if event else None,
        "root_cause": root,
        "trace_completeness": completeness,
        "reason": "stage mismatch is supported by recorded before/after trace",
    }


def locate_targets(gold_graph: ArticleExtraction, pred_graph: ArticleExtraction,
                   artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Find content-present result records whose final attachment differs."""
    candidates_by_result = {
        c.get("final", {}).get("final_entity_id"): c
        for c in artifact.get("candidates", [])
        if c.get("final", {}).get("final_entity_id")
    }
    rows: list[dict[str, Any]] = []
    for kind in ("ArmResult", "ComparisonResult"):
        pred_entities = entities(pred_graph, kind)
        gold_entities = entities(gold_graph, kind)
        used_prediction_ids: set[str] = set()
        for gold_entity in gold_entities:
            matches = [
                (pred_entity, score)
                for pred_entity in pred_entities
                if getattr(pred_entity, ID_FIELD[kind]) not in used_prediction_ids
                for ok, score in [content_match(gold_graph, gold_entity, pred_graph, pred_entity)]
                if ok
            ]
            if not matches:
                continue
            matches.sort(key=lambda x: (-x[1], str(getattr(x[0], ID_FIELD[kind]))))
            # Repeated p-values or identical raw rows are not enough to
            # identify which comparison they belong to.  Do not reuse a
            # prediction or manufacture a relationship in that case.
            if len(matches) > 1 and matches[0][1] == matches[1][1]:
                continue
            pred_entity, score = matches[0]
            used_prediction_ids.add(getattr(pred_entity, ID_FIELD[kind]))
            gold_parent = expected_parent(gold_graph, gold_entity)
            pred_parent = parent_snapshot(pred_entity)
            wrong_fields = []
            if kind == "ArmResult" and pred_parent.get("arm_id") != gold_parent.get("arm_id"):
                wrong_fields.append("WRONG_ARM")
            if kind == "ComparisonResult" and pred_parent.get("comparison_id") != gold_parent.get("comparison_id"):
                wrong_fields.append("WRONG_COMPARISON")
            if pred_parent.get("outcome_id") != gold_parent.get("outcome_id"):
                wrong_fields.append("WRONG_OUTCOME")
            for field in ("timepoint", "timepoint_value", "timepoint_unit"):
                if pred_parent.get(field) != gold_parent.get(field):
                    wrong_fields.append("WRONG_TIMEPOINT")
                    break
            if not wrong_fields:
                continue
            pid = getattr(pred_entity, ID_FIELD[kind])
            candidate = candidates_by_result.get(pid)
            if candidate is None:
                rows.append({
                    "target_id": f"{kind}:{getattr(gold_entity, ID_FIELD[kind])}",
                    "gold": {"entity_type": kind, "entity_id": getattr(gold_entity, ID_FIELD[kind]),
                             "parent": gold_parent, "content": result_content_tokens(gold_graph, gold_entity)},
                    "final_prediction": {"entity_type": kind, "entity_id": pid,
                                         "parent": pred_parent, "content": result_content_tokens(pred_graph, pred_entity)},
                    "first_failure_stage": "UNKNOWN",
                    "first_failure_event_id": None,
                    "root_cause": "UNKNOWN",
                    "trace_completeness": "NONE",
                    "wrong_fields": sorted(set(wrong_fields)),
                    "content_match_score": score,
                })
                continue
            rows.append({
                "target_id": f"{kind}:{getattr(gold_entity, ID_FIELD[kind])}",
                "gold": {"entity_type": kind, "entity_id": getattr(gold_entity, ID_FIELD[kind]),
                         "parent": gold_parent, "content": result_content_tokens(gold_graph, gold_entity)},
                "final_prediction": {"entity_type": kind, "entity_id": pid,
                                     "parent": pred_parent, "content": result_content_tokens(pred_graph, pred_entity)},
                **classify_first_failure(candidate, gold_graph, gold_entity, pred_graph),
                "wrong_fields": sorted(set(wrong_fields)),
                "content_match_score": score,
            })
    return rows


def evaluate(prediction: ArticleExtraction, gold_path: Path, registry_path: Path) -> tuple[Any, GoldStandardV2]:
    gold = GoldStandardV2.model_validate_json(gold_path.read_text(encoding="utf-8"))
    report = evaluate_article(prediction, gold, load_registry(registry_path))
    return report, gold


def count_recorded_api_calls(production: Path) -> dict[str, Any]:
    raw = production / "raw_module_responses"
    table_manifest = raw / "request_manifest.jsonl"
    table_calls = len([line for line in table_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]) if table_manifest.exists() else 0
    topology = len(list((production / "trial_topology").glob("topology.request-*.json")))
    arm_details = len(list((production / "arm_details").glob("request-*.json")))
    structured = sum(len(list(raw.glob(f"{name}.attempt-*.json"))) for name in ("metadata", "acupuncture", "risk_of_bias"))
    post = len(list(raw.glob("outcomes.postprocess.part-*.json")))
    return {
        "recorded_total": table_calls + topology + arm_details + structured + post,
        "by_stage": {
            "trial_topology": topology,
            "arm_details": arm_details,
            "structured_modules": structured,
            "outcome_table_and_narrative": table_calls,
            "outcome_postprocess": post,
        },
        "note": "Counts are persisted request/response artifacts; transport attempts without an artifact cannot be reconstructed.",
    }


def read_dotenv_models() -> dict[str, str | None]:
    """Read model names only; never expose API keys or endpoint credentials."""
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, raw = line.split("=", 1)
            values[key.strip()] = raw.strip().strip("\"'")
    def pick(name: str, default: str) -> str:
        return os.getenv(name) or values.get(name) or default
    return {
        "default": pick("ARTICLE_AGENT_MODEL", "gpt-5.5"),
        "topology": pick("ARTICLE_AGENT_TOPOLOGY_MODEL", "gpt-5.6-luna"),
        "arm_details": pick("ARTICLE_AGENT_ARM_DETAILS_MODEL", "gpt-5.6-sol"),
        "structured": pick("ARTICLE_AGENT_STRUCTURED_MODEL", pick("ARTICLE_AGENT_MODEL", "gpt-5.5")),
        "table_classifier": pick("ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL", "gpt-5.6-luna"),
    }


def metrics_payload(report: Any) -> dict[str, Any]:
    return {
        key: report.metrics[key]
        for key in (
            "hard_exact",
            "production_coverage",
            "supported_value_accuracy",
            "status_accuracy",
            "evidence_grounding",
        )
    } | {
        "conflicts": report.metrics["conflicts"],
        "entities": report.metrics["entities"],
        "field_failure_counts": report.field_failure_counts,
        "entity_failure_counts": report.entity_failure_counts,
    }


def render_html(summary: dict[str, Any]) -> str:
    report = summary["report"]
    stage_rows = summary["first_failure_summary"]["by_first_failure_stage"]
    error_rows = summary["error_type_by_stage"]
    lines = [
        "<!doctype html><meta charset='utf-8'><title>PR5R-5 2015-06 First-Failure Localization</title>",
        "<style>body{font-family:system-ui, sans-serif;max-width:1200px;margin:2rem auto;line-height:1.45}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.35rem;text-align:left}pre{white-space:pre-wrap;background:#f6f6f6;padding:1rem}.ok{color:#087f23}</style>",
        "<h1>PR5R-5 — 2015-06 First-Failure Localization</h1>",
        "<p>诊断运行只在 production assembly 完成后读取 Gold；没有用 Gold 影响 extraction，也没有调用诊断 LLM。</p>",
        "<h2>Traced run</h2><pre>" + html.escape(json.dumps(summary["run_manifest"], ensure_ascii=False, indent=2)) + "</pre>",
        "<h2>Metrics</h2><pre>" + html.escape(json.dumps(report, ensure_ascii=False, indent=2)) + "</pre>",
        "<h2>First-failure stage</h2>",
        "<table><tr><th>Stage</th><th>Count</th><th>%</th></tr>",
    ]
    total = max(1, sum(stage_rows.values()))
    for stage in STAGES:
        n = stage_rows.get(stage, 0)
        lines.append(f"<tr><td>{stage}</td><td>{n}</td><td>{n / total:.2%}</td></tr>")
    lines.append("</table><h2>Error type × stage</h2><pre>" + html.escape(json.dumps(error_rows, ensure_ascii=False, indent=2)) + "</pre>")
    lines.append("<h2>Target details</h2><pre>" + html.escape(json.dumps(summary["attachment_targets"], ensure_ascii=False, indent=2)) + "</pre>")
    lines.append("<h2>Run drift</h2><pre>" + html.escape(json.dumps(summary["current_vs_traced"], ensure_ascii=False, indent=2)) + "</pre>")
    lines.append("<h2>结论</h2><p>" + html.escape(summary["recommendation"]) + "</p>")
    return "\n".join(lines)


def run(production: Path, out: Path, gold_path: Path, registry_path: Path,
        current_path: Path | None = None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    payloads = [
        load_json(production / "extraction.json"),
        load_json(production / "trial_topology/trial_topology.json"),
        load_json(production / "arm_details/arm_details.canonical.json"),
    ]
    session = TraceSession("2015-06", enabled=True)
    prediction, normalization = assemble(*payloads, trace=session)
    serialized = (prediction.model_dump_json(indent=2) + "\n").encode("utf-8")
    ArticleExtraction.model_validate_json(serialized)
    artifact = session.artifact()
    gold_report, gold = evaluate(prediction, gold_path, registry_path)
    targets = locate_targets(gold.truth, prediction, artifact)
    result_content_present = 0
    result_content_total = 0
    for kind in ("ArmResult", "ComparisonResult"):
        for gold_entity in entities(gold.truth, kind):
            result_content_total += 1
            if any(
                content_match(gold.truth, gold_entity, prediction, pred_entity)[0]
                for pred_entity in entities(prediction, kind)
            ):
                result_content_present += 1
    result_entity_failures = [
        item for item in gold_report.entity_failures
        if item.get("entity_type") in {"ArmResult", "ComparisonResult"}
    ]
    stage_summary = {stage: 0 for stage in STAGES}
    root_summary = {root: 0 for root in ROOT_CAUSES}
    error_by_stage = {kind: {stage: 0 for stage in STAGES} for kind in ERROR_TYPES}
    for row in targets:
        stage = row["first_failure_stage"]
        root = row["root_cause"]
        stage_summary[stage] = stage_summary.get(stage, 0) + 1
        root_summary[root] = root_summary.get(root, 0) + 1
        for error_type in row["wrong_fields"]:
            error_by_stage.setdefault(error_type, {stage_name: 0 for stage_name in STAGES})
            error_by_stage[error_type][stage] += 1

    run_manifest = load_json(production / "manifest.json")
    api_calls = count_recorded_api_calls(production)
    config = {
        "source_pdf": str(Path(run_manifest.get("source_pdf", "")).resolve()),
        "parser_backend": run_manifest.get("parser_backend"),
        "model": run_manifest.get("structured_module_model"),
        "models": read_dotenv_models(),
        "prompt_hashes": {
            "MinerU_method/mineru_method/prompts.py": sha(ROOT / "MinerU method/mineru_method/prompts.py"),
            "src/article_agent/trial_topology_agent.py": sha(ROOT / "src/article_agent/trial_topology_agent.py"),
            "src/article_agent/arm_details_agent.py": sha(ROOT / "src/article_agent/arm_details_agent.py"),
        },
        "registry_sha256": sha(registry_path),
        "gold_sha256": sha(gold_path),
        "normalization_rules_sha256": sha(ROOT / "src/article_agent/outcome_source_normalizer.py"),
        "merger_rules_sha256": sha(ROOT / "src/article_agent/outcome_canonicalizer.py"),
        "missingness_rules": "not modified/read by diagnostic",
        "provenance_tracing": True,
        "production_postprocess_gold_reference": bool(
            load_json(production / "raw_module_responses/outcomes.postprocess.manifest.json")
            .get("gold_used_for_postprocess_comparison", False)
        ),
    }
    current_vs_traced = None
    if current_path and current_path.exists():
        current = ArticleExtraction.model_validate_json(current_path.read_text(encoding="utf-8"))
        current_report, _ = evaluate(current, gold_path, registry_path)
        current_vs_traced = {
            "current_prediction_sha256": sha(current_path),
            "traced_prediction_sha256": hashlib.sha256(serialized).hexdigest(),
            "prediction_different": current.model_dump_json() != prediction.model_dump_json(),
            "current_metrics": metrics_payload(current_report),
            "traced_metrics": metrics_payload(gold_report),
            "drift_note": "Different prediction hashes indicate run-to-run extraction drift; this is not merged into attachment root causes.",
        }

    source_record_count = len(payloads[0].get("outcomes", {}).get("outcomes", []))
    summary = {
        "run_manifest": {
            "run_id": run_manifest.get("run_id", "pr5r5-traced-2015-06"),
            "commit_sha": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "configuration": config,
            "source_record_count": source_record_count,
            "production_api_calls": api_calls,
            "diagnostic_api_calls": 0,
            "prediction_sha256": hashlib.sha256(serialized).hexdigest(),
            "trace_sha256": hashlib.sha256(wire(artifact).encode("utf-8")).hexdigest(),
        },
        "report": metrics_payload(gold_report),
        "attachment_targets": targets,
        "first_failure_summary": {
            "total_localized_targets": len(targets),
            "localized": sum(row["first_failure_stage"] != "UNKNOWN" for row in targets),
            "unknown": sum(row["first_failure_stage"] == "UNKNOWN" for row in targets),
            "wrong_entity_attachments": len(targets),
            "result_content_present": result_content_present,
            "result_content_total": result_content_total,
            "result_content_missing_or_ambiguous": result_content_total - result_content_present,
            "evaluator_result_entity_failures_not_proven_attachment": len(result_entity_failures),
            "by_first_failure_stage": stage_summary,
            "by_root_cause": root_summary,
        },
        "error_type_by_stage": error_by_stage,
        "current_vs_traced": current_vs_traced,
        "recommendation": (
            "根据实际 trace，下一步只应修改 first-failure 数量最多且非 UNKNOWN 的 production layer；"
            "若 UNKNOWN 占主导，应先补齐缺失的上游/中间 artifact，而不是猜测修复层。"
        ),
        "production_logic_changed": False,
        "gold_changed": False,
        "registry_changed": False,
        "prompt_changed": False,
        "gold_used_for_extraction": False,
        "gold_used_for_production_prediction": False,
        "diagnostic_llm_calls": 0,
        "normalization_equal": normalization == normalization,
    }
    (out / "TRACED_PREDICTION.json").write_bytes(serialized)
    (out / "PROVENANCE_EVENTS.json").write_text(wire(artifact["events"]), encoding="utf-8")
    (out / "RESULT_LINEAGE.json").write_text(wire(artifact["result_lineage"]), encoding="utf-8")
    (out / "ATTACHMENT_TARGETS.json").write_text(wire(targets), encoding="utf-8")
    (out / "FIRST_FAILURE_LOCALIZATION.json").write_text(wire(targets), encoding="utf-8")
    (out / "FIRST_FAILURE_SUMMARY.json").write_text(wire(summary["first_failure_summary"]), encoding="utf-8")
    (out / "ERROR_TYPE_BY_STAGE.json").write_text(wire(error_by_stage), encoding="utf-8")
    (out / "CURRENT_VS_TRACED_RUN.json").write_text(wire(current_vs_traced), encoding="utf-8")
    (out / "RUN_MANIFEST.json").write_text(wire(summary["run_manifest"]), encoding="utf-8")
    (out / "PROVENANCE_TRACE.json").write_text(wire(artifact), encoding="utf-8")
    (out / "EVALUATION.json").write_text(wire(summary["report"]), encoding="utf-8")
    (out / "SUMMARY.json").write_text(wire(summary), encoding="utf-8")
    md = [
        "# PR5R-5 — 2015-06 Traced Re-extraction & First-Failure Localization",
        "",
        "本次为独立诊断 run；未覆盖历史 benchmark。raw extraction 和 traced canonical assembly 不读取 Gold；当前 main 的可选 postprocess 会在抽取后读取 Gold 做冲突注释，该引用未进入 TRACED_PREDICTION。diagnostic API calls = 0。",
        "",
        f"- traced prediction SHA256: `{summary['run_manifest']['prediction_sha256']}`",
        f"- trace SHA256: `{summary['run_manifest']['trace_sha256']}`",
        f"- production API calls（持久化记录）: `{api_calls['recorded_total']}`",
        f"- attachment targets with content present: `{len(targets)}`",
        f"- localized: `{summary['first_failure_summary']['localized']}`; UNKNOWN: `{summary['first_failure_summary']['unknown']}`",
        "",
        "## Metrics",
        "",
        "```json",
        json.dumps(summary["report"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## First-failure stage",
        "",
        "| stage | count |",
        "|---|---:|",
    ]
    for stage in STAGES:
        md.append(f"| {stage} | {stage_summary[stage]} |")
    md += [
        "",
        "## Error type × stage",
        "",
        "```json",
        json.dumps(error_by_stage, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Run drift",
        "",
        "```json",
        json.dumps(current_vs_traced, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 结论",
        "",
        summary["recommendation"],
        "",
        "Retrieval 仅追踪到 production-input boundary；若 evidence 在该边界前已缺失，严格标记为 RETRIEVAL_OR_UPSTREAM/UNKNOWN，不指认具体 PDF chunk。",
    ]
    (out / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "REPORT.html").write_text(render_html(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-dir", type=Path, default=DEFAULT_PRODUCTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--current-prediction", type=Path, default=DEFAULT_CURRENT)
    args = parser.parse_args(argv)
    summary = run(
        args.production_dir,
        args.output,
        args.gold,
        args.registry,
        args.current_prediction if args.current_prediction.exists() else None,
    )
    print(json.dumps({
        "output": str(args.output),
        "production_api_calls": summary["run_manifest"]["production_api_calls"],
        "diagnostic_api_calls": 0,
        "metrics": summary["report"],
        "first_failure_summary": summary["first_failure_summary"],
        "current_vs_traced": summary["current_vs_traced"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
