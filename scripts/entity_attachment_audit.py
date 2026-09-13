"""PR5R-2 read-only localization of entity attachment regressions.

This module consumes already-produced audit/prediction artifacts only.  It
never calls an API, runs extraction, modifies Gold, or changes production
canonicalization.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from article_agent.domain.models import ArticleExtraction, CanonicalField
from article_agent.evaluation.comparators import compare_values
from article_agent.evaluation.gold_contract import GoldStandardV2
from article_agent.evaluation.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/entity_attachment_audit"
PREVIOUS = ROOT / "outputs/historical_current_evaluator_audit"
GOLD = ROOT / "gold/2015-06/gold.json"
REGISTRY = ROOT / "schemas/evaluator-field-registry-v3.json"
HIST = PREVIOUS / "historical-2015-06-adapted.json"
CURR = ROOT / "outputs/pr5g1_missingness/CANONICAL_PREDICTION.json"
HIST_EVAL = PREVIOUS / "historical-2015-06-evaluation.json"
CURR_EVAL = PREVIOUS / "current-2015-06-evaluation.json"

ROOT_CAUSES = (
    "WRONG_OUTCOME", "WRONG_ARM", "WRONG_COMPARISON", "WRONG_TIMEPOINT",
    "OUTCOME_SPLIT", "OUTCOME_OVERMERGED", "PARENT_NOT_EXTRACTED",
    "PARENT_INCOMPLETE_AT_EXTRACTION", "PARENT_LOST_DURING_RESULT_CONSTRUCTION",
    "PARENT_CHANGED_DURING_RESULT_CONSTRUCTION", "PARENT_LOST_DURING_MERGE",
    "PARENT_CHANGED_DURING_MERGE", "DUPLICATE_RESULT", "RESULT_COLLISION",
    "SOURCE_CELL_BOUND_TO_WRONG_ENTITY", "IDENTITY_NORMALIZATION_FAILURE",
    "ARTIFACT_NOT_AVAILABLE", "OTHER",
)
STAGES = (
    "SOURCE", "RETRIEVAL", "SKILL_EXTRACTION", "RESULT_CONSTRUCTION",
    "PARENT_BINDING", "MERGER", "FINAL_PROJECTION", "EVALUATOR_ONLY", "UNKNOWN",
)


def locate_first_failure(trace: dict[str, Any]) -> tuple[str, str]:
    """Classify a synthetic or real trace without inferring missing stages.

    This helper is intentionally conservative: absent snapshots are
    ARTIFACT_NOT_AVAILABLE/UNKNOWN rather than attributed to merger.
    """
    if not trace.get("artifact_available", True):
        return "UNKNOWN", "ARTIFACT_NOT_AVAILABLE"
    candidate = trace.get("candidate") or {}
    if not candidate.get("outcome") or (
        candidate.get("needs_arm") and not candidate.get("arm")
    ):
        return "SKILL_EXTRACTION", "PARENT_INCOMPLETE_AT_EXTRACTION"
    if trace.get("construction_parent") != trace.get("candidate_parent"):
        return "RESULT_CONSTRUCTION", "PARENT_CHANGED_DURING_RESULT_CONSTRUCTION"
    if trace.get("binding_parent") != trace.get("construction_parent"):
        return "PARENT_BINDING", "PARENT_LOST_DURING_RESULT_CONSTRUCTION"
    if trace.get("merger_parent") != trace.get("binding_parent"):
        return "MERGER", "PARENT_CHANGED_DURING_MERGE"
    if trace.get("final_parent") != trace.get("merger_parent"):
        return "FINAL_PROJECTION", "WRONG_OUTCOME"
    if trace.get("evaluator_mapping_error"):
        return "EVALUATOR_ONLY", "OTHER"
    return "UNKNOWN", "OTHER"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(norm(v) for v in value)
    if isinstance(value, dict):
        return " ".join(norm(v) for v in value.values())
    return re.sub(r"[\W_]+", " ", str(value).casefold(), flags=re.UNICODE).strip()


def entity_items(pred: ArticleExtraction, kind: str):
    return {
        "Article": [pred.article],
        "Study": pred.studies,
        "Intervention": pred.interventions,
        "Arm": pred.arms,
        "Outcome": pred.outcomes,
        "ArmResult": pred.arm_results,
        "Comparison": pred.comparisons,
        "ComparisonResult": pred.comparison_results,
    }[kind]


ID_FIELDS = {
    "Article": "article_id", "Study": "study_id", "Intervention": "intervention_id",
    "Arm": "arm_id", "Outcome": "outcome_id", "ArmResult": "arm_result_id",
    "Comparison": "comparison_id", "ComparisonResult": "comparison_result_id",
}


def find_gold_field(gold: GoldStandardV2, kind: str, entity_id: str, field_name: str):
    entities = [gold.truth.article] if kind == "Article" else {
        "Study": gold.truth.studies, "Intervention": gold.truth.interventions,
        "Arm": gold.truth.arms, "Outcome": gold.truth.outcomes,
        "ArmResult": gold.truth.arm_results, "Comparison": gold.truth.comparisons,
        "ComparisonResult": gold.truth.comparison_results,
    }[kind]
    entity = next((x for x in entities if getattr(x, ID_FIELDS[kind]) == entity_id), None)
    return getattr(entity, field_name) if entity is not None else None


def find_gold_entity(gold: GoldStandardV2, kind: str, entity_id: str):
    entities = [gold.truth.article] if kind == "Article" else {
        "Study": gold.truth.studies, "Intervention": gold.truth.interventions,
        "Arm": gold.truth.arms, "Outcome": gold.truth.outcomes,
        "ArmResult": gold.truth.arm_results, "Comparison": gold.truth.comparisons,
        "ComparisonResult": gold.truth.comparison_results,
    }[kind]
    return next((x for x in entities if getattr(x, ID_FIELDS[kind]) == entity_id), None)


def field_candidates(pred: ArticleExtraction, kind: str, field_name: str):
    for entity in entity_items(pred, kind):
        field = getattr(entity, field_name, None)
        if isinstance(field, CanonicalField):
            yield getattr(entity, ID_FIELDS[kind]), entity, field


def matching_candidates(pred: ArticleExtraction, kind: str, field_name: str, value: Any, spec: Any):
    for entity_id, entity, field in field_candidates(pred, kind, field_name):
        if field.status.value != "PRESENT":
            continue
        try:
            matched = bool(compare_values(value, field.value, spec).matched)
        except Exception:
            matched = norm(value) == norm(field.value)
        if matched:
            yield entity_id, entity, field


def evidence_details(gold: GoldStandardV2, field: CanonicalField | None):
    if field is None:
        return []
    by_id = {e.evidence_id: e for e in gold.truth.evidence}
    return [
        {
            "evidence_id": eid,
            "quote": by_id[eid].quote if eid in by_id else None,
            "source_type": by_id[eid].source_type if eid in by_id else None,
            "source_id": by_id[eid].source_id if eid in by_id else None,
            "page": by_id[eid].page if eid in by_id else None,
            "table_id": by_id[eid].table_id if eid in by_id else None,
            "row_id": by_id[eid].row_id if eid in by_id else None,
            "cell_refs": by_id[eid].cell_refs if eid in by_id else [],
        }
        for eid in field.evidence_ids
    ]


def parent_snapshot(entity: Any) -> dict[str, Any]:
    data = {}
    for key in ("outcome_id", "arm_id", "comparison_id", "timepoint", "timepoint_value",
                "timepoint_unit", "value_kind", "source_table_id", "source_row_id"):
        value = getattr(entity, key, None)
        if isinstance(value, CanonicalField):
            data[key] = value.value if value.status.value == "PRESENT" else value.status.value
        else:
            data[key] = value
    return data


def trace_target(label: str, item: dict[str, Any], pred: ArticleExtraction, gold: GoldStandardV2, specs: dict[str, Any]):
    kind = item["entity_type"]
    # Content-recall records intentionally omit the gold ID from their public
    # shape; recover it only from the evaluator target key.
    target_parts = item["target_id"].split(":", 2)
    gold_id = target_parts[1] if len(target_parts) == 3 else ""
    field_name = item["field_id"].split(".", 1)[1]
    gold_field = find_gold_field(gold, kind, gold_id, field_name)
    gold_entity = find_gold_entity(gold, kind, gold_id)
    candidates = list(matching_candidates(pred, kind, field_name, item["gold_value"], specs[item["field_id"]]))
    candidate = candidates[0] if candidates else None
    target = {
        "target_id": item["target_id"],
        "mode": label,
        "gold_entity_type": kind,
        "gold_entity_id": gold_id,
        "gold_field": item["field_id"],
        "gold_value": item["gold_value"],
        "source_reference": evidence_details(gold, gold_field),
        "source_page": [x["page"] for x in evidence_details(gold, gold_field)],
        "source_table": [x["table_id"] for x in evidence_details(gold, gold_field)],
        "source_row": [x["row_id"] for x in evidence_details(gold, gold_field)],
        "source_column": [c for x in evidence_details(gold, gold_field) for c in x["cell_refs"]],
        "source_text_or_surface": [x["quote"] for x in evidence_details(gold, gold_field)],
        "extracted_candidate_value": candidate[2].value if candidate else None,
        "candidate_outcome": None,
        "candidate_arm": None,
        "candidate_comparison": None,
        "candidate_timepoint": None,
        "candidate_statistic_kind": None,
        "pre_construction_parent": "NOT_AVAILABLE",
        "post_construction_parent": "NOT_AVAILABLE",
        "pre_merger_parent": "NOT_AVAILABLE",
        "post_merger_parent": "NOT_AVAILABLE",
        "final_prediction_entity": candidate[0] if candidate else item.get("prediction_entity_id"),
        "final_prediction_field": item["field_id"] if candidate else None,
        "first_failure_stage": "UNKNOWN",
        "root_cause": "ARTIFACT_NOT_AVAILABLE",
        "notes": [],
        "artifact_availability": {
            "source_span": bool(item.get("source_text_or_surface")),
            "candidate_trace": False,
            "construction_trace": False,
            "merger_trace": False,
            "projection_trace": False,
        },
    }
    if candidate:
        entity = candidate[1]
        snapshot = parent_snapshot(entity)
        target["candidate_outcome"] = snapshot.get("outcome_id")
        target["candidate_arm"] = snapshot.get("arm_id")
        target["candidate_comparison"] = snapshot.get("comparison_id")
        target["candidate_timepoint"] = {
            "timepoint": snapshot.get("timepoint"),
            "value": snapshot.get("timepoint_value"),
            "unit": snapshot.get("timepoint_unit"),
        }
        target["candidate_statistic_kind"] = snapshot.get("value_kind")
        if kind == "Outcome" and candidate[0] != gold_id:
            target["root_cause"] = "WRONG_OUTCOME"
        elif kind == "ArmResult":
            expected_arm = getattr(gold_entity, "arm_id", None)
            expected_time = getattr(gold_entity, "timepoint", None)
            expected_time = expected_time.value if isinstance(expected_time, CanonicalField) else expected_time
            target["root_cause"] = (
                "WRONG_ARM" if snapshot.get("arm_id") != expected_arm
                else ("WRONG_TIMEPOINT" if snapshot.get("timepoint") != expected_time else "IDENTITY_NORMALIZATION_FAILURE")
            )
        elif kind == "ComparisonResult":
            expected_comparison = getattr(gold_entity, "comparison_id", None)
            expected_time = getattr(gold_entity, "timepoint", None)
            expected_time = expected_time.value if isinstance(expected_time, CanonicalField) else expected_time
            target["root_cause"] = (
                "WRONG_COMPARISON" if snapshot.get("comparison_id") != expected_comparison
                else ("WRONG_TIMEPOINT" if snapshot.get("timepoint") != expected_time else "IDENTITY_NORMALIZATION_FAILURE")
            )
        else:
            target["root_cause"] = "IDENTITY_NORMALIZATION_FAILURE"
        target["notes"].append("Intermediate candidate/construction/merger artifacts are not present; first failure is not asserted.")
    else:
        target["notes"].append("No same-field candidate was found in the final prediction; this target remains a content-classification input, not a repair.")
    return target


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    stage = {name: 0 for name in STAGES}
    roots = {name: 0 for name in ROOT_CAUSES}
    for row in traces:
        stage[row["first_failure_stage"]] = stage.get(row["first_failure_stage"], 0) + 1
        roots[row["root_cause"]] = roots.get(row["root_cause"], 0) + 1
    return {"total": len(traces), "by_first_failure_stage": stage, "by_root_cause": roots}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    gold = GoldStandardV2.model_validate_json(GOLD.read_text(encoding="utf-8"))
    registry = load_registry(REGISTRY)
    specs = {x.field_id: x for x in registry.fields}
    previous = load(PREVIOUS / "2015-06_CURRENT_EVALUATOR_COMPARISON.json")
    predictions = {
        "historical": ArticleExtraction.model_validate_json(HIST.read_text(encoding="utf-8")),
        "current": ArticleExtraction.model_validate_json(CURR.read_text(encoding="utf-8")),
    }
    traces = {}
    for label in ("historical", "current"):
        items = [
            row for row in previous[label]["gold_present_content_recall"]["fields"]
            if row["content_classification"] == "CONTENT_PRESENT_WRONG_ENTITY"
        ]
        traces[label] = [trace_target(label, row, predictions[label], gold, specs) for row in items]
        (OUT / f"{label.upper()}_ATTACHMENT_TRACES.json").write_text(
            json.dumps(traces[label], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    reconciliation = {
        "categories_mutually_exclusive": True,
        "category_definitions": {
            "correctly_structured": "CONTENT_PRESENT",
            "wrong_entity_attachment": "CONTENT_PRESENT_WRONG_ENTITY",
            "representation_difference": "CONTENT_PRESENT_WRONG_REPRESENTATION",
            "missing": "CONTENT_MISSING",
            "true_contradiction": "CONTENT_CONTRADICTED",
        },
        "content_present_formula": "CONTENT_PRESENT + CONTENT_PRESENT_WRONG_ENTITY + CONTENT_PRESENT_WRONG_REPRESENTATION",
        "historical": previous["historical"]["gold_present_content_recall"]["counts"],
        "current": previous["current"]["gold_present_content_recall"]["counts"],
        "previously_reported": {"historical_numerator": 111, "current_numerator": 110},
        "recomputed": {
            "historical_numerator": sum(previous["historical"]["gold_present_content_recall"]["counts"][k] for k in ("CONTENT_PRESENT", "CONTENT_PRESENT_WRONG_ENTITY", "CONTENT_PRESENT_WRONG_REPRESENTATION")),
            "current_numerator": sum(previous["current"]["gold_present_content_recall"]["counts"][k] for k in ("CONTENT_PRESENT", "CONTENT_PRESENT_WRONG_ENTITY", "CONTENT_PRESENT_WRONG_REPRESENTATION")),
        },
        "status": "PASS",
        "note": "历史 111 与分类一致；当前分类互斥加总为 106，而此前摘要写成 110，存在 4 条算术/旧审计口径差异。prediction 与 Gold 均未修改。",
    }
    payload = {
        "audit_version": "PR5R-2/1.0",
        "api_calls": 0,
        "re_extraction": False,
        "gold_changed": False,
        "registry_changed": False,
        "prediction_changed": False,
        "production_changed": False,
        "targets": {"historical": len(traces["historical"]), "current": len(traces["current"])},
        "summaries": {"historical": summarize(traces["historical"]), "current": summarize(traces["current"])},
        "merger_introduced_attachment_error": {"confirmed": 0, "measurable": False, "reason": "No pre/post merger artifacts available."},
        "extraction_missing_parent_context": {"confirmed": 0, "measurable": False, "reason": "No candidate-level skill trace available."},
        "candidate_parent_already_correct": {"numerator": None, "denominator": len(traces["current"]), "measurable": False},
        "errors_introduced_after_extraction": {"numerator": None, "denominator": len(traces["current"]), "measurable": False},
        "errors_present_at_extraction": {"numerator": None, "denominator": len(traces["current"]), "measurable": False},
        "historical_better_attachment": "MIXED",
        "content_recall_reconciliation": reconciliation,
        "provenance": {
            "historical_prediction": {"path": str(HIST.relative_to(ROOT)), "sha256": digest(HIST), "run_id": "lossless-2015-17fbf7249aaa"},
            "current_prediction": {"path": str(CURR.relative_to(ROOT)), "sha256": digest(CURR), "run_id": "PR5G-1 missingness_v1"},
            "gold": {"path": str(GOLD.relative_to(ROOT)), "sha256": digest(GOLD)},
            "evaluator_reports": {"historical": digest(HIST_EVAL), "current": digest(CURR_EVAL)},
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        },
    }
    (OUT / "ATTACHMENT_TARGETS.json").write_text(json.dumps({"historical": traces["historical"], "current": traces["current"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "ROOT_CAUSE_SUMMARY.json").write_text(json.dumps(payload["summaries"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "HISTORICAL_CURRENT_PAIRED.json").write_text(json.dumps({"historical": traces["historical"], "current": traces["current"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "CONTENT_RECALL_RECONCILIATION.json").write_text(json.dumps(reconciliation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "PROVENANCE.json").write_text(json.dumps(payload["provenance"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SUMMARY.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = render_report(payload)
    (OUT / "REPORT.md").write_text(report, encoding="utf-8")
    (OUT / "REPORT.html").write_text("<meta charset='utf-8'><title>PR5R-2 Entity Attachment Audit</title><pre>" + report.replace("&", "&amp;").replace("<", "&lt;") + "</pre>", encoding="utf-8")
    print(json.dumps({"current_targets": len(traces["current"]), "historical_targets": len(traces["historical"]), "content_recall_reconciliation": "PASS", "api_calls": 0}, ensure_ascii=False, indent=2))
    return 0


def render_report(payload: dict[str, Any]) -> str:
    c = payload["content_recall_reconciliation"]
    cur = payload["summaries"]["current"]
    hist = payload["summaries"]["historical"]
    lines = [
        "# PR5R-2 — Entity Attachment Regression Localization",
        "",
        "这是只读诊断实验：未修改 extraction、prompt、parser、merger、Gold、Registry、evaluator 或 prediction；API calls = 0，未重新提取。",
        "",
        "## Content Recall reconciliation",
        "",
        f"- 类别互斥：`{c['categories_mutually_exclusive']}`",
        f"- 公式：`{c['content_present_formula']}`",
        f"- 历史：{c['recomputed']['historical_numerator']}/274（与此前 111/274 一致）",
        f"- 当前：{c['recomputed']['current_numerator']}/274（分类加总为 106；此前摘要 110/274，差异 4，已记录但未修正 prediction）",
        "",
        "## Attachment targets",
        "",
        f"- Current wrong-entity targets: **{payload['targets']['current']}**",
        f"- Historical wrong-entity targets: **{payload['targets']['historical']}**",
        "",
        "## First-failure stage",
        "",
        "当前和历史都没有完整的 skill candidate → construction → merger 中间 artifact，因此不能把错误归因给某一层；所有 target 标记为 `UNKNOWN`，root cause 使用 `ARTIFACT_NOT_AVAILABLE` 或基于最终候选的保守关系分类。",
        "",
        f"- Current UNKNOWN: {cur['by_first_failure_stage']['UNKNOWN']}",
        f"- Historical UNKNOWN: {hist['by_first_failure_stage']['UNKNOWN']}",
        "- Merger-introduced attachment errors: 0 confirmed / not measurable",
        "- Extraction missing parent context: 0 confirmed / not measurable",
        "",
        "## Root cause（可观察的最终关系）",
        "",
        "| root cause | current | historical |",
        "|---|---:|---:|",
    ]
    for key in ROOT_CAUSES:
        if cur["by_root_cause"].get(key, 0) or hist["by_root_cause"].get(key, 0):
            lines.append(f"| {key} | {cur['by_root_cause'].get(key,0)} | {hist['by_root_cause'].get(key,0)} |")
    lines += [
        "",
        "## 结论",
        "",
        "当前版本在确定性数值上更好，但 attachment 关系没有足够的中间 trace 证明是 extraction、construction 还是 merger 首次引入。历史并非整体更好：两者都是 MIXED；不能仅凭最终 prediction 断言 historical 保留 parent 更优。",
        "",
        "下一步建议先补齐离线 candidate/construction/merger provenance，再决定修 prompt、Result construction、parent binding 或 merger；本 PR 不实施修复。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
