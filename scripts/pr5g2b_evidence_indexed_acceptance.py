"""Offline PR5G-2B acceptance using the saved PR5R-6 source runs.

Each run independently builds a source-unit index and bounded annotations;
there is no ensemble vote, Gold input, evaluator call or API call.  The
fixture annotation is only a deterministic replay of explicit fields already
present in each source row, allowing the evidence-indexed architecture to be
tested before an online bounded annotator is enabled.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any

from article_agent.domain.models import ArticleExtraction
from article_agent.evidence_indexed_discovery import (
    UnitAnnotation,
    build_slot_plan_from_annotations,
    build_source_unit_index,
    validate_unit_annotations,
)
from article_agent.trial_topology_agent import TrialTopology


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "outputs/pr5r6_reproducibility_2015_06"
OUT = ROOT / "outputs/pr5g2b_evidence_indexed_acceptance_2015_06"
RUNS = ("run_a", "run_b", "run_c")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_run(run: str) -> tuple[list[dict[str, Any]], TrialTopology, ArticleExtraction, Path]:
    article = SOURCE_ROOT / f"{run}_output/2015-06"
    extraction = json.loads((article / "extraction.json").read_text(encoding="utf-8"))
    topology = TrialTopology.model_validate(json.loads(
        (article / "trial_topology/trial_topology.json").read_text(encoding="utf-8")
    ))
    graph = ArticleExtraction.model_validate(json.loads(
        (article / "arm_details/arm_details.canonical.json").read_text(encoding="utf-8")
    ))
    return extraction["outcomes"]["outcomes"], topology, graph, article


def _valid(value: Any) -> bool:
    return value not in (None, "", "NR", "N/R", "unknown")


def fixture_annotations(index) -> list[UnitAnnotation]:
    """Annotate only explicit spans/parents from each indexed row."""

    annotations: list[UnitAnnotation] = []
    for unit in index.units:
        if unit.unit_type not in {"table_row", "paragraph"}:
            continue
        row = unit.payload
        name = row.get("outcome_name") or row.get("outcomeName")
        if not _valid(name):
            continue
        timepoint = row.get("timepoint") or row.get("outcome_observation_timepoint_raw")
        arms = row.get("arm", row.get("arms", [])) or []
        if isinstance(arms, dict):
            arms = [arms]
        arm_refs = []
        for arm in arms:
            if not isinstance(arm, dict):
                continue
            label = next(
                (arm.get(key) for key in ("arm_label", "label", "arm_id") if _valid(arm.get(key))),
                None,
            )
            if _valid(label):
                arm_refs.append(str(label))
        comparison_refs: list[list[str]] = []
        comparisons = row.get("comparisons")
        if comparisons is None:
            comparisons = [row.get("comparison") or {}]
        if isinstance(comparisons, dict):
            comparisons = [comparisons]
        for comparison in comparisons:
            if not isinstance(comparison, dict):
                continue
            labels = comparison.get("arm_labels") or []
            if not labels and _valid(comparison.get("contrast")):
                labels = re.split(r"\s+vs\.?\s+", str(comparison["contrast"]), flags=re.I)
            if len(labels) >= 2 and all(_valid(label) for label in labels):
                comparison_refs.append([str(label) for label in labels])
        annotations.append(UnitAnnotation(
            source_unit_id=unit.source_unit_id,
            outcome_span=str(name),
            timepoint_span=str(timepoint) if _valid(timepoint) and str(timepoint).casefold() in unit.text.casefold() else None,
            arm_refs=arm_refs,
            comparison_refs=comparison_refs,
            evidence_span=unit.text,
            status="SUPPORTED",
        ))
    return annotations


def slot_sets(plans, slot_type):
    return {
        run: {slot.slot_id for slot in plan.slots if slot.slot_type == slot_type}
        for run, plan in plans.items()
    }


def stability(plans):
    summary = {}
    for slot_type in ("ArmResult", "ComparisonResult"):
        sets = slot_sets(plans, slot_type)
        union = set.union(*sets.values()) if sets else set()
        counts = {run: len(values) for run, values in sets.items()}
        frequencies = {slot: sum(slot in values for values in sets.values()) for slot in union}
        common = sum(value == 3 for value in frequencies.values())
        summary[slot_type] = {
            "counts": counts,
            "common": common,
            "two_run": sum(value == 2 for value in frequencies.values()),
            "one_run": sum(value == 1 for value in frequencies.values()),
            "union": len(union),
            "common_ratio": round(common / len(union), 6) if union else 1.0,
        }
    return summary


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    plans = {}
    manifests = {}
    for run in RUNS:
        records, topology, graph, article = load_run(run)
        index = build_source_unit_index("2015-06", records)
        raw_annotations = fixture_annotations(index)
        checked = validate_unit_annotations(index, raw_annotations)
        plan = build_slot_plan_from_annotations(
            "2015-06", topology, graph, index, checked,
        )
        plans[run] = plan
        prefix = run.upper()
        (OUT / f"{prefix}_SOURCE_UNIT_INDEX.json").write_text(
            index.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (OUT / f"{prefix}_UNIT_ANNOTATIONS.json").write_text(
            checked.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (OUT / f"{prefix}_STRUCTURE_PLAN.json").write_text(
            plan.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (OUT / f"{prefix}_FINAL_PREDICTION.json").write_text(
            json.dumps({
                "schema_version": "EVIDENCE_INDEXED_SLOT_PREDICTION/1.0",
                "article_id": "2015-06",
                "source_units": len(index.units),
                "annotations": len(checked.accepted),
                "slots": [slot.model_dump() for slot in plan.slots],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifests[run] = {
            "source_extraction_sha256": digest(article / "extraction.json"),
            "source_unit_count": len(index.units),
            "annotation_count": len(checked.accepted),
            "annotation_violations": len(checked.violations),
            "annotation_ambiguities": len(checked.ambiguities),
            "slot_counts": {
                "ArmResult": sum(slot.slot_type == "ArmResult" for slot in plan.slots),
                "ComparisonResult": sum(slot.slot_type == "ComparisonResult" for slot in plan.slots),
            },
            "warnings": len(plan.warnings),
            "api_calls": 0,
            "gold_used": False,
        }
    slot_stability = stability(plans)
    legacy_counts = {"ArmResult": 45, "ComparisonResult": 17}
    cardinality_guard = {}
    for slot_type, legacy_count in legacy_counts.items():
        observed = [item["slot_counts"][slot_type] for item in manifests.values()]
        cardinality_guard[slot_type] = {
            "legacy_reference_max": legacy_count,
            "slot_based_counts": observed,
            "false_stability_check": (
                "FAIL" if min(observed, default=0) < max(1, int(legacy_count * 0.8))
                else "PASS"
            ),
            "note": "High intersection with sharply lower cardinality is not accepted as success.",
        }
    summary = {
        "pr": "PR5G-2B",
        "article_id": "2015-06",
        "mode": "OFFLINE_BOUNDED_ANNOTATION_REPLAY",
        "ensemble_or_majority_vote": False,
        "plans": manifests,
        "slot_stability": slot_stability,
        "cardinality_guard": cardinality_guard,
        "content_recall": {
            "status": "NOT_RUN",
            "reason": "Gold/evaluator prohibited in this structure-discovery acceptance",
        },
        "hard": "NOT_RUN",
        "coverage": "NOT_RUN",
        "legacy_reference": {
            "ArmResult": {"common": 30, "two_run": 12, "one_run": 21},
            "ComparisonResult": {"common": 6, "two_run": 7, "one_run": 16},
        },
        "gold_used": False,
        "registry_used": False,
        "evaluator_used": False,
    }
    (OUT / "SLOT_STABILITY.json").write_text(json.dumps(slot_stability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "RUN_MANIFEST.json").write_text(json.dumps(manifests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# PR5G-2B — Evidence-indexed Structure Discovery",
        "",
        "三次独立离线 bounded annotation replay；source unit 先由 parser/source records 建立，annotator 不能创建结构实体。",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "本次未调用 API、Gold 或 evaluator；Content Recall/HARD/Coverage 留待在线 acceptance。",
        "没有使用 A/B/C 多数投票，三个运行分别独立生成 source units、annotations 和 slots。",
    ]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (OUT / "REPORT.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>PR5G-2B</title>"
        "<style>body{font-family:system-ui;max-width:1100px;margin:2rem auto}pre{white-space:pre-wrap;background:#f6f6f6;padding:1rem}</style>"
        "<h1>PR5G-2B — Evidence-indexed Structure Discovery</h1><pre>"
        + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre>",
        encoding="utf-8",
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
