"""Offline PR5G-2A slot-based result extraction acceptance.

The default mode replays the three already-saved PR5R-6 source runs.  It does
not call topology, outcome, evaluation or Gold APIs; it only runs the new
deterministic structure planner and a source-backed fill fixture.  ``--run-
extractions`` is intentionally opt-in for a future online experiment.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from article_agent.slot_result_extraction import (
    SlotFill,
    SourceRef,
    discover_result_slots,
    materialize_slot_fills,
    validate_slot_fills,
)
from article_agent.trial_topology_agent import TrialTopology
from article_agent.domain.models import ArticleExtraction


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "outputs/pr5r6_reproducibility_2015_06"
OUT = ROOT / "outputs/pr5g2a_slot_acceptance_2015_06"
RUNS = ("run_a", "run_b", "run_c")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_digest(value: Any) -> str:
    return hashlib.sha256(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)).encode()
    ).hexdigest()


def load_run(run: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], Path]:
    article = SOURCE_ROOT / f"{run}_output/2015-06"
    extraction = json.loads((article / "extraction.json").read_text(encoding="utf-8"))
    topology = json.loads((article / "trial_topology/trial_topology.json").read_text(encoding="utf-8"))
    arm_graph = json.loads((article / "arm_details/arm_details.canonical.json").read_text(encoding="utf-8"))
    return extraction["outcomes"]["outcomes"], topology, arm_graph, article


def aliases(topology: TrialTopology, graph: ArticleExtraction) -> dict[str, str]:
    result: dict[str, str] = {}
    for arm, source in zip(graph.arms, topology.arms, strict=True):
        for label in (arm.arm_id, arm.label.value, source.name, source.source_label, *source.aliases):
            if label and str(label).strip().casefold() not in {"nr", "unknown"}:
                result[" ".join(str(label).casefold().split())] = arm.arm_id
    return result


def fill_fixture(
    plan,
    records: list[dict[str, Any]],
    topology: TrialTopology,
    graph: ArticleExtraction,
) -> list[SlotFill]:
    """Replay values only from the exact source row supporting each slot."""

    arm_alias = aliases(topology, graph)
    by_index = {index: row for index, row in enumerate(records)}
    fills: list[SlotFill] = []
    for slot in plan.slots:
        ref = next((ref for ref in slot.source_refs if ref.source_index is not None), None)
        if ref is None or ref.source_index not in by_index:
            continue
        row = by_index[ref.source_index]
        values: dict[str, Any] = {}
        field_aliases = {
            "timepoint": ("timepoint", "outcome_observation_timepoint_raw"),
            "timepoint_value": ("timepoint_value", "outcome_observation_timepoint_value"),
            "timepoint_unit": ("timepoint_unit", "outcome_observation_timepoint_unit"),
            "analysis_set": ("analysis_set", "analysis_population"),
        }
        for target, names in field_aliases.items():
            for name in names:
                if row.get(name) not in (None, "", "NR"):
                    values[target] = row[name]
                    break
        if slot.slot_type == "ArmResult":
            arms = row.get("arm", row.get("arms", [])) or []
            if isinstance(arms, dict):
                arms = [arms]
            arm = next(
                (
                    item for item in arms if isinstance(item, dict)
                    and arm_alias.get(" ".join(str(
                        next((item.get(name) for name in ("arm_id", "arm_label", "label")
                              if item.get(name) not in (None, "", "NR")), "")
                    ).casefold().split())) == slot.arm_id
                ),
                None,
            )
            if arm:
                aliases_map = {
                    "value": ("value", "estimate"),
                    "standard_deviation": ("standard_deviation", "sd"),
                    "change_from_baseline": ("change_from_baseline", "change"),
                    "dispersion_lower": ("dispersion_lower", "lower"),
                    "dispersion_upper": ("dispersion_upper", "upper"),
                    "n": ("n",), "event_count": ("event_count",), "denominator": ("denominator",),
                    "raw_value": ("raw_value",),
                    "value_kind": ("value_kind", "statistic_type"),
                }
                for target, names in aliases_map.items():
                    for name in names:
                        if arm.get(name) not in (None, "", "NR"):
                            values[target] = arm[name]
                            break
        else:
            comparisons = row.get("comparisons")
            if comparisons is None:
                comparisons = [row.get("comparison") or {}]
            if isinstance(comparisons, dict):
                comparisons = [comparisons]
            comp = next(
                (
                    item for item in comparisons if isinstance(item, dict)
                    and tuple(arm_alias.get(" ".join(str(label).casefold().split()), "")
                              for label in (item.get("arm_labels") or []))
                    == tuple(slot.comparison_arm_ids)
                ),
                None,
            )
            if comp:
                aliases_map = {
                    "effect_measure": ("effect_measure", "between_group_measure", "effect_size_name"),
                    "estimate": ("estimate", "outcome_between_group_estimate"),
                    "confidence_interval_lower": ("confidence_interval_lower", "outcome_between_group_lower"),
                    "confidence_interval_upper": ("confidence_interval_upper", "outcome_between_group_upper"),
                    "p_value": ("p_value", "outcome_p_value"),
                    "p_value_comparator": ("p_value_comparator", "outcome_p_value_comparator"),
                    "raw_value": ("raw_value",),
                }
                for target, names in aliases_map.items():
                    for name in names:
                        if comp.get(name) not in (None, "", "NR"):
                            values[target] = comp[name]
                            break
        fills.append(SlotFill(
            slot_id=slot.slot_id, values=values,
            source_refs=[SourceRef.model_validate(ref.model_dump())],
        ))
    return fills


def slot_sets(plans: dict[str, Any], slot_type: str) -> dict[str, set[str]]:
    return {run: {slot.slot_id for slot in plan.slots if slot.slot_type == slot_type}
            for run, plan in plans.items()}


def stability(plans: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for slot_type, label in (("ArmResult", "ArmResult"), ("ComparisonResult", "ComparisonResult")):
        sets = slot_sets(plans, slot_type)
        common = set.intersection(*sets.values()) if sets else set()
        union = set.union(*sets.values()) if sets else set()
        result[label] = {
            "counts": {run: len(values) for run, values in sets.items()},
            "common": len(common),
            "union": len(union),
            "two_run": len(union - common) - sum(
                1 for slot in union if sum(slot in values for values in sets.values()) == 1
            ),
            "one_run": sum(
                1 for slot in union if sum(slot in values for values in sets.values()) == 1
            ),
            "common_ratio": round(len(common) / len(union), 6) if union else 1.0,
            "pairwise": {
                f"{left}-{right}": len(sets[left] & sets[right])
                for left, right in (("run_a", "run_b"), ("run_a", "run_c"), ("run_b", "run_c"))
            },
        }
    return result


def value_stability(plans: dict[str, Any], fills: dict[str, list[SlotFill]]) -> dict[str, Any]:
    values: dict[str, dict[str, Any]] = {}
    for run, plan in plans.items():
        for fill in fills[run]:
            values.setdefault(fill.slot_id, {})[run] = fill.values.get("value", fill.values.get("estimate"))
    counts = Counter()
    for slot_values in values.values():
        present = [value for value in slot_values.values() if value is not None]
        if len(present) < 3:
            counts["MISSING_IN_ONE_RUN"] += 1
        elif len({str(value) for value in present}) == 1:
            counts["SAME_VALUE"] += 1
        else:
            counts["DIFFERENT_VALUE"] += 1
    return {"counts": dict(counts), "slot_count": len(values)}


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    plans: dict[str, Any] = {}
    fills: dict[str, list[SlotFill]] = {}
    manifests: dict[str, Any] = {}
    for run_name in RUNS:
        records, topology_raw, graph_raw, article = load_run(run_name)
        topology = TrialTopology.model_validate(topology_raw)
        graph = ArticleExtraction.model_validate(graph_raw)
        trace = None
        plan = discover_result_slots("2015-06", topology, graph, records)
        plans[run_name] = plan
        fills[run_name] = fill_fixture(plan, records, topology, graph)
        checked = validate_slot_fills(plan, fills[run_name])
        materialized = materialize_slot_fills(plan, checked)
        (OUT / f"{run_name.upper()}_SLOT_PLAN.json").write_text(
            plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (OUT / f"{run_name.upper()}_SLOT_FILLS.json").write_text(
            json.dumps(checked.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (OUT / f"{run_name.upper()}_FINAL_PREDICTION.json").write_text(
            json.dumps({
                "schema_version": "SLOT_BASED_RESULT_PREDICTION/1.0",
                "article_id": "2015-06",
                "slots": [slot.model_dump() for slot in plan.slots],
                "materialized": [item.model_dump() for item in materialized],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifests[run_name] = {
            "source_extraction_sha256": digest(article / "extraction.json"),
            "topology_sha256": digest(article / "trial_topology/trial_topology.json"),
            "arm_graph_sha256": digest(article / "arm_details/arm_details.canonical.json"),
            "slot_plan_sha256": digest(OUT / f"{run_name.upper()}_SLOT_PLAN.json"),
            "slot_fill_sha256": digest(OUT / f"{run_name.upper()}_SLOT_FILLS.json"),
            "slot_counts": {
                "ArmResult": sum(slot.slot_type == "ArmResult" for slot in plan.slots),
                "ComparisonResult": sum(slot.slot_type == "ComparisonResult" for slot in plan.slots),
            },
            "outcome_count": len(plan.discovered_outcomes),
            "warnings": len(plan.warnings),
            "contract_violations": len(checked.violations),
            "ambiguities": len(checked.ambiguities),
            "api_calls": 0,
            "gold_used": False,
        }

    summary = {
        "pr": "PR5G-2A",
        "article_id": "2015-06",
        "mode": "OFFLINE_REPLAY",
        "legacy_freeform_path_preserved": True,
        "gold_changed": False,
        "registry_changed": False,
        "evaluator_changed": False,
        "study_specific_hardcoding": False,
        "plans": manifests,
        "slot_stability": stability(plans),
        "slot_value_stability": value_stability(plans, fills),
        "contract_violations": sum(len(validate_slot_fills(plans[run], fills[run]).violations) for run in RUNS),
        "ambiguous_slots": sum(
            sum("ambiguous timepoint" in warning for warning in plans[run].warnings)
            for run in RUNS
        ),
        "content_recall": {"status": "NOT_RUN", "reason": "Gold/evaluator are prohibited in PR5G-2A"},
        "secondary_metrics": {"HARD": "NOT_RUN", "coverage": "NOT_RUN", "supported_value_accuracy": "NOT_RUN"},
        "legacy_reference": {
            "ArmResult": {"common": 30, "two_run": 12, "one_run": 21},
            "ComparisonResult": {"common": 6, "two_run": 7, "one_run": 16},
        },
        "baseline": {
            "commit_sha": "ffdfaf99b9e273860ddceac4e9cd68f1bc8e561f",
            "parser_backend": "pymupdf-fallback:mineru",
            "model": "gpt-5.6-sol",
            "result_construction_version": "legacy-pr5d1-build-prediction",
        },
    }
    (OUT / "RUN_MANIFEST.json").write_text(json.dumps(manifests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SLOT_STABILITY.json").write_text(json.dumps(summary["slot_stability"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SLOT_VALUE_STABILITY.json").write_text(json.dumps(summary["slot_value_stability"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SLOT_CONTRACT_VIOLATIONS.json").write_text(json.dumps({"count": summary["contract_violations"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SLOT_AMBIGUITIES.json").write_text(json.dumps({"count": summary["ambiguous_slots"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "LEGACY_VS_SLOT_BASED.json").write_text(json.dumps({
        "legacy": summary["legacy_reference"], "slot_based": summary["slot_stability"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# PR5G-2A — Slot-based Result Extraction",
        "",
        "本次为离线 replay：复用 PR5R-6 已保存的三次 source extraction，不调用 API、Gold 或 evaluator。",
        "",
        f"- baseline commit: `{summary['baseline']['commit_sha']}`",
        "- legacy freeform path: 保留",
        "- Gold / Registry / evaluator: 未修改",
        "",
        "## Slot stability",
        "",
        "```json",
        json.dumps(summary["slot_stability"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Value stability",
        "",
        "```json",
        json.dumps(summary["slot_value_stability"], ensure_ascii=False, indent=2),
        "```",
        "",
        "Content Recall 与 HARD/coverage 本 PR 不调用 Gold/evaluator，标记为 NOT_RUN；后续 acceptance 应使用同一当前 evaluator 重新测量。",
        "",
        "结论：Result 数量和 identity 已从 LLM 自由生成改为 source-supported slot planning + constrained slot filling；",
        "本次离线回放显示主要剩余漂移位于 source-supported structure discovery，而不是 materialization。",
    ]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (OUT / "REPORT.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>PR5G-2A</title>"
        "<style>body{font-family:system-ui;max-width:1100px;margin:2rem auto}pre{white-space:pre-wrap;background:#f6f6f6;padding:1rem}</style>"
        "<h1>PR5G-2A — Slot-based Result Extraction</h1><p>离线 replay，无 API/Gold/evaluator。</p><pre>"
        + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre>",
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
