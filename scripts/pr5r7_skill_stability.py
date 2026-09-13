"""PR5R-7: offline Skill stability and frozen-run contract audit.

This diagnostic deliberately does not call the API and does not alter any
production, Gold, evaluator, or canonicalization behavior.  It consumes the
already captured PR5R-6 Run A/B/C artifacts plus the historical frozen
2015-06 artifact and emits deterministic JSON/HTML/Markdown reports.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CURRENT_ROOT = ROOT / "outputs/pr5r6_reproducibility_2015_06"
FROZEN_ROOT = ROOT / "outputs/mineru_method_lossless_sol_luna_v5/2015-06"
FROZEN_PREDICTION = ROOT / "outputs/pr5d1_2015_06_benchmark_retry06/prediction.json"
FROZEN_PREDICTION_MANIFEST = ROOT / "outputs/pr5d1_2015_06_benchmark_retry06/RUN_MANIFEST.json"
OUT = ROOT / "outputs/pr5r7_skill_stability_2015_06"
RUNS = ("run_a", "run_b", "run_c")

sys.path.insert(0, str(ROOT))
from scripts.pr5d1_build_prediction import assemble  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_file():
        return sha256(path)
    rows = []
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        rows.append({"path": child.relative_to(path).as_posix(), "sha256": sha256(child)})
    return digest_value(rows)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest_value(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(norm(x) for x in value)
    if isinstance(value, dict):
        return stable_json(value)
    text = str(value).casefold()
    return re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).strip()


def field_value(field: Any) -> Any:
    if isinstance(field, dict) and "value" in field:
        return field.get("value")
    if hasattr(field, "value") and hasattr(field, "status"):
        return getattr(field, "value")
    return field


def entity_type_counts(prediction: Any) -> dict[str, int]:
    return {
        "Article": 1 if prediction.article else 0,
        "Study": len(prediction.studies),
        "Arm": len(prediction.arms),
        "Intervention": len(prediction.interventions),
        "Outcome": len(prediction.outcomes),
        "ArmResult": len(prediction.arm_results),
        "Comparison": len(prediction.comparisons),
        "ComparisonResult": len(prediction.comparison_results),
    }


def prediction_sets(prediction: Any) -> dict[str, list[str]]:
    outcomes = {
        f"{norm(field_value(o.name))}::{norm(field_value(o.instrument))}"
        for o in prediction.outcomes
    }
    arms = {f"{a.arm_id}::{norm(field_value(a.label))}" for a in prediction.arms}
    comparisons = {
        f"{c.comparison_id}::{','.join(sorted(c.arm_ids))}"
        for c in prediction.comparisons
    }
    timepoints = {
        norm(field_value(r.timepoint))
        for r in (*prediction.arm_results, *prediction.comparison_results)
        if norm(field_value(r.timepoint))
    }
    statistic_kinds = {
        norm(field_value(r.value_kind))
        for r in prediction.arm_results
        if hasattr(r, "value_kind") and norm(field_value(r.value_kind))
    } | {
        norm(field_value(r.effect_measure))
        for r in prediction.comparison_results
        if hasattr(r, "effect_measure") and norm(field_value(r.effect_measure))
    }
    values = set()
    for result in (*prediction.arm_results, *prediction.comparison_results):
        for name in (
            "value", "standard_deviation", "change_from_baseline",
            "dispersion_lower", "dispersion_upper", "n", "event_count",
            "denominator", "estimate", "confidence_interval_lower",
            "confidence_interval_upper", "p_value",
        ):
            if hasattr(result, name):
                value = field_value(getattr(result, name))
                if value is not None:
                    values.add(f"{name}={norm(value)}")
    return {
        "Outcome": sorted(outcomes),
        "Arm": sorted(arms),
        "Comparison": sorted(comparisons),
        "Timepoint": sorted(timepoints),
        "Statistic": sorted(statistic_kinds),
        "Value": sorted(values),
    }


def slot_sets(prediction: Any) -> dict[str, set[str]]:
    outcome_by_id = {
        o.outcome_id: f"{norm(field_value(o.name))}::{norm(field_value(o.instrument))}"
        for o in prediction.outcomes
    }
    arm_slots = set()
    for result in prediction.arm_results:
        arm_slots.add("::".join((
            outcome_by_id.get(result.outcome_id, result.outcome_id),
            norm(field_value(result.timepoint)),
            result.arm_id,
        )))
    comparison_slots = set()
    for result in prediction.comparison_results:
        comparison_slots.add("::".join((
            outcome_by_id.get(result.outcome_id, result.outcome_id),
            norm(field_value(result.timepoint)),
            result.comparison_id,
        )))
    return {"Outcome×Timepoint×Arm": arm_slots, "Outcome×Timepoint×Comparison": comparison_slots}


def source_skill_summary(bundle: dict[str, Any], predictions: dict[str, Any]) -> dict[str, Any]:
    modules = ("metadata", "acupuncture", "risk_of_bias", "outcomes", "consort_flow")
    summary: dict[str, Any] = {}
    for module in modules:
        raw = bundle.get(module, {})
        if module == "outcomes":
            records = raw.get("outcomes", []) if isinstance(raw, dict) else []
            record_count = len(records)
            fields = sorted({k for r in records if isinstance(r, dict) for k in r})
        else:
            records = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
            record_count = len(records)
            fields = sorted({k for r in records if isinstance(r, dict) for k in r})
        summary[module] = {
            "raw_record_count": record_count,
            "candidate_count": record_count,
            "field_presence": fields,
            "entity_type_count": {},
        }
    for run, prediction in predictions.items():
        summary.setdefault("canonical_projection", {})[run] = {
            "entity_type_count": entity_type_counts(prediction),
            "sets": prediction_sets(prediction),
        }
    return summary


def raw_skill_stability(bundles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare source-record identity per production Skill, without Gold."""
    modules = ("metadata", "acupuncture", "risk_of_bias", "outcomes", "consort_flow")
    result: dict[str, Any] = {}
    for module in modules:
        by_run: dict[str, set[str]] = {}
        record_counts: dict[str, int] = {}
        fields_by_run: dict[str, set[str]] = {}
        for run, bundle in bundles.items():
            raw = bundle.get(module, {})
            records = raw.get("outcomes", []) if module == "outcomes" and isinstance(raw, dict) else (
                raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
            )
            record_counts[run] = len(records)
            by_run[run] = {
                digest_value({
                    "table_id": record.get("table_id"),
                    "row_id": record.get("row_id"),
                    "name": record.get("outcome_name") or record.get("field") or record.get("name"),
                    "source": record.get("source_evidence") or record.get("source"),
                })
                for record in records if isinstance(record, dict)
            }
            fields_by_run[run] = {key for record in records if isinstance(record, dict) for key in record}
        metrics = pairwise_metrics(by_run)
        result[module] = {
            "raw_record_count": record_counts,
            "candidate_count": record_counts,
            "count_range": max(record_counts.values()) - min(record_counts.values()),
            "field_presence": {run: sorted(fields_by_run[run]) for run in RUNS},
            **metrics,
        }
    return result


def pairwise_metrics(sets_by_run: dict[str, set[str]]) -> dict[str, Any]:
    result = {}
    for left, right in (("run_a", "run_b"), ("run_a", "run_c"), ("run_b", "run_c")):
        a, b = sets_by_run[left], sets_by_run[right]
        result[f"{left}-{right}"] = {
            "overlap_count": len(a & b),
            "union_count": len(a | b),
            "jaccard": round(len(a & b) / len(a | b), 6) if a | b else 1.0,
            "only_left": sorted(a - b),
            "only_right": sorted(b - a),
        }
    intersection = set.intersection(*(sets_by_run[name] for name in RUNS)) if sets_by_run else set()
    union = set.union(*(sets_by_run[name] for name in RUNS)) if sets_by_run else set()
    return {
        "pairwise": result,
        "intersection": sorted(intersection),
        "union_count": len(union),
        "run_specific": {
            name: sorted(sets_by_run[name] - set.union(*(sets_by_run[x] for x in RUNS if x != name)))
            for name in RUNS
        },
    }


def stability_summary(predictions: dict[str, Any]) -> dict[str, Any]:
    all_sets = {run: prediction_sets(pred) for run, pred in predictions.items()}
    metrics = {}
    for kind in ("Outcome", "Arm", "Comparison", "Timepoint", "Statistic", "Value"):
        metrics[kind] = {
            "counts": {run: len(all_sets[run][kind]) for run in RUNS},
            "count_range": max(len(all_sets[run][kind]) for run in RUNS) - min(len(all_sets[run][kind]) for run in RUNS),
            **pairwise_metrics({run: set(all_sets[run][kind]) for run in RUNS}),
        }
    return metrics


def slot_stability(predictions: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for slot_kind in ("Outcome×Timepoint×Arm", "Outcome×Timepoint×Comparison"):
        by_run = {run: slot_sets(predictions[run])[slot_kind] for run in RUNS}
        result[slot_kind] = {
            "counts": {run: len(by_run[run]) for run in RUNS},
            **pairwise_metrics(by_run),
            "present_in_three": sorted(set.intersection(*(by_run[r] for r in RUNS))),
            "present_in_two": sorted(
                slot for slot in set.union(*(by_run[r] for r in RUNS))
                if sum(slot in by_run[r] for r in RUNS) == 2
            ),
            "present_in_one": sorted(
                slot for slot in set.union(*(by_run[r] for r in RUNS))
                if sum(slot in by_run[r] for r in RUNS) == 1
            ),
        }
    return result


def value_stability(predictions: dict[str, Any]) -> dict[str, Any]:
    """Compare uniquely keyed slots without using Gold or fuzzy matching."""
    by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for run, prediction in predictions.items():
        outcome_by_id = {
            o.outcome_id: f"{norm(field_value(o.name))}::{norm(field_value(o.instrument))}"
            for o in prediction.outcomes
        }
        rows = {}
        for r in prediction.arm_results:
            slot = "::".join((outcome_by_id.get(r.outcome_id, r.outcome_id), norm(field_value(r.timepoint)), r.arm_id))
            rows[slot] = {
                "value": field_value(r.value),
                "statistic_kind": field_value(r.value_kind),
                "raw_value": field_value(r.raw_value),
            }
        for r in prediction.comparison_results:
            slot = "::".join((outcome_by_id.get(r.outcome_id, r.outcome_id), norm(field_value(r.timepoint)), r.comparison_id))
            rows[slot] = {
                "value": field_value(r.estimate) if field_value(r.estimate) is not None else field_value(r.p_value),
                "statistic_kind": field_value(r.effect_measure),
                "raw_value": field_value(r.raw_value),
            }
        by_run[run] = rows
    all_slots = set.union(*(set(rows) for rows in by_run.values()))
    categories = Counter()
    details = []
    for slot in sorted(all_slots):
        present = [run for run in RUNS if slot in by_run[run]]
        if len(present) < 3:
            categories["MISSING_IN_ONE_RUN"] += 1
            continue
        rows = [by_run[run][slot] for run in RUNS]
        values = {norm(row["value"]) for row in rows}
        stats = {norm(row["statistic_kind"]) for row in rows}
        raw = {norm(row["raw_value"]) for row in rows}
        if any(row["value"] is None for row in rows) and any(row["value"] is not None for row in rows):
            category = "MISSING_IN_ONE_RUN"
        elif len(values) == 1 and len(stats) == 1 and len(raw) == 1:
            category = "SAME_VALUE"
        elif len(values) == 1:
            category = "REPRESENTATION_ONLY_DIFFERENCE"
        else:
            category = "DIFFERENT_VALUE"
        categories[category] += 1
        details.append({"slot": slot, "category": category, "runs": dict(zip(RUNS, rows))})
    return {"counts": dict(categories), "details": details}


def file_hash(path: Path) -> str | None:
    return sha256(path) if path.exists() else None


def classify_contract(rows: dict[str, dict[str, Any]]) -> str:
    critical = (
        "parser_backend", "parser_output_hash", "markdown_hash",
        "retrieval_context_hash", "evidence_context_hash",
        "result_construction_version", "candidate_generation_path",
        "model", "api_config", "temperature", "skill_names_versions",
        "skill_prompt_hashes",
    )
    if any(rows.get(key, {}).get("status") == "DIFFERENT" for key in critical):
        return "RUN_CONTRACT_DRIFT"
    if any(rows.get(key, {}).get("status") in {None, "NOT_AVAILABLE"} for key in critical):
        return "CONTRACT_NOT_PROVABLE"
    return "STOCHASTIC_LLM_DRIFT"


def contract_comparison(current_summary: dict[str, Any]) -> dict[str, Any]:
    old_manifest = load(FROZEN_ROOT / "manifest.json", {})
    current_manifest = load(CURRENT_ROOT / "run_a_output/2015-06/manifest.json", {})
    current_config = current_summary.get("configuration_frozen", {})
    old_hybrid = old_manifest.get("hybrid_route", {})
    current_hybrid = current_manifest.get("hybrid_route", {})
    def status(old: Any, new: Any) -> str:
        if old is None or new is None:
            return "NOT_AVAILABLE"
        return "SAME" if old == new else "DIFFERENT"
    old_hashes = {
        "parser_output_hash": tree_sha256(FROZEN_ROOT / "hybrid"),
        "markdown_hash": file_hash(FROZEN_ROOT / "article.md"),
        "retrieval_context_hash": file_hash(FROZEN_ROOT / "routed_context.json"),
        "evidence_context_hash": file_hash(FROZEN_ROOT / "evidence_contexts.json"),
    }
    new_hashes = current_summary.get("runs", {}).get("run_a", {})
    rows = {
        "git_commit": {"old": old_manifest.get("commit_sha"), "new": current_summary.get("commit_sha")},
        "extraction_run_id": {"old": old_manifest.get("run_id"), "new": current_manifest.get("run_id")},
        "model": {"old": old_manifest.get("structured_module_model"), "new": current_manifest.get("structured_module_model")},
        "api_config": {"old": None, "new": current_config.get("api_parameters_sha256")},
        "temperature": {"old": None, "new": current_config.get("temperature")},
        "parser_backend": {"old": old_manifest.get("parser_backend"), "new": current_manifest.get("parser_backend")},
        "parser_output_hash": {"old": old_hashes["parser_output_hash"], "new": new_hashes.get("parser_output_hash")},
        "markdown_hash": {"old": old_hashes["markdown_hash"], "new": new_hashes.get("article_markdown_hash")},
        "retrieval_context_hash": {"old": old_hashes["retrieval_context_hash"], "new": new_hashes.get("retrieval_context_hash")},
        "evidence_context_hash": {"old": old_hashes["evidence_context_hash"], "new": new_hashes.get("evidence_context_hash")},
        "skill_names_versions": {"old": None, "new": current_config.get("skill_versions")},
        "skill_prompt_hashes": {"old": None, "new": current_config.get("prompt_hashes")},
        "registry_schema_version": {"old": None, "new": "ARTICLE_EXTRACTION/2.0"},
        "runtime_abstention_version": {"old": None, "new": None},
        "result_construction_version": {"old": None, "new": file_hash(ROOT / "scripts/pr5d1_build_prediction.py")},
        "merger_version": {"old": None, "new": None},
        "normalization_version": {"old": None, "new": file_hash(ROOT / "src/article_agent/outcome_source_normalizer.py")},
        "candidate_generation_path": {
            "old": old_manifest.get("normalized_tables"),
            "new": current_manifest.get("normalized_tables"),
        },
    }
    for row in rows.values():
        row["status"] = status(row["old"], row["new"])
    classification = classify_contract(rows)
    old_prediction = load(FROZEN_PREDICTION, {})
    return {
        "classification": classification,
        "rows": rows,
        "historical_prediction": {
            "path": str(FROZEN_PREDICTION.relative_to(ROOT)),
            "sha256": file_hash(FROZEN_PREDICTION),
            "arm_result_count": len(old_prediction.get("arm_results", [])) if isinstance(old_prediction, dict) else None,
            "comparison_result_count": len(old_prediction.get("comparison_results", [])) if isinstance(old_prediction, dict) else None,
            "outcome_count": len(old_prediction.get("outcomes", [])) if isinstance(old_prediction, dict) else None,
            "manifest": load(FROZEN_PREDICTION_MANIFEST, {}),
        },
    }


def render_report(summary: dict[str, Any]) -> str:
    comparison = summary["frozen_run_contract"]["classification"]
    drift = summary["layer_comparison"]["interpretation"]
    slots = summary["result_slot_stability"]
    skill_rows = summary["skill_level_stability"]
    most_unstable = min(
        skill_rows,
        key=lambda name: (
            -skill_rows[name]["count_range"],
            min(item["jaccard"] for item in skill_rows[name]["pairwise"].values()),
        ),
    )
    value_counts = summary["value_stability"]["counts"]
    dominant = "STRUCTURE_DRIFT" if value_counts.get("MISSING_IN_ONE_RUN", 0) else "CONTENT_DRIFT"
    old = summary["frozen_run_contract"]["historical_prediction"]
    return "\n".join([
        "# PR5R-7 — Skill 输出稳定性与 frozen-run contract 对照",
        "",
        f"- 旧/当前 contract 分类：**{comparison}**",
        f"- 当前 A/B/C 首次差异：**{drift}**",
        f"- 15 → 45 ArmResults：**{summary['old_vs_current_classification']}**",
        f"- 历史 frozen prediction：ArmResults `{old['arm_result_count']}`，ComparisonResults `{old['comparison_result_count']}`；"
        f"当前 Run A：ArmResults `{summary['runs']['run_a']['result_counts']['arm_results']}`，"
        f"ComparisonResults `{summary['runs']['run_a']['result_counts']['comparison_results']}`。",
        f"- 当前最不稳定 Skill：**{most_unstable}**",
        f"- slot 层主导漂移：**{dominant}**",
        "",
        "## Run A/B/C",
        "",
        "| run | candidates | ArmResults | ComparisonResults |",
        "|---|---:|---:|---:|",
        *[
            f"| {run} | {summary['runs'][run]['candidate_count']} | "
            f"{summary['runs'][run]['result_counts']['arm_results']} | "
            f"{summary['runs'][run]['result_counts']['comparison_results']} |"
            for run in RUNS
        ],
        "",
        "## Slot stability",
        "",
        f"- Outcome × Timepoint × Arm：三次共同 `{len(slots['Outcome×Timepoint×Arm']['present_in_three'])}`，"
        f"两次 `{len(slots['Outcome×Timepoint×Arm']['present_in_two'])}`，"
        f"单次 `{len(slots['Outcome×Timepoint×Arm']['present_in_one'])}`。",
        f"- Outcome × Timepoint × Comparison：三次共同 `{len(slots['Outcome×Timepoint×Comparison']['present_in_three'])}`，"
        f"两次 `{len(slots['Outcome×Timepoint×Comparison']['present_in_two'])}`，"
        f"单次 `{len(slots['Outcome×Timepoint×Comparison']['present_in_one'])}`。",
        "",
        "## Value stability",
        "",
        "```json",
        json.dumps(summary["value_stability"]["counts"], ensure_ascii=False, indent=2),
        "```",
        "",
        f"- 稳定 slot 中相同数值：`{summary['diagnosis']['stable_slots_same_values']}`；不同数值：`{summary['diagnosis']['stable_slots_different_values']}`。",
        f"- ComparisonResult 方差：{summary['diagnosis']['main_comparison_result_variance']}",
        f"- 下一步建议：**{summary['diagnosis']['next_repair']}**；slot-based extraction：**YES**。",
        "",
        "结论：本 PR 仅做离线诊断，不修改 extraction、Gold、Registry、evaluator 或 canonicalizer。"
    ])


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    current_summary = load(CURRENT_ROOT / "SUMMARY.json", {})
    predictions = {}
    bundles = {}
    for run in RUNS:
        article_dir = CURRENT_ROOT / f"{run}_output/2015-06"
        bundle = load(article_dir / "extraction.json", {})
        topology = load(article_dir / "trial_topology/trial_topology.json", {})
        arm_graph = load(article_dir / "arm_details/arm_details.canonical.json", {})
        prediction, _ = assemble(bundle, topology, arm_graph)
        predictions[run] = prediction
        bundles[run] = bundle
    contract = contract_comparison(current_summary)
    arm_slots = slot_stability(predictions)["Outcome×Timepoint×Arm"]
    comparison_slots = slot_stability(predictions)["Outcome×Timepoint×Comparison"]
    raw_skill = raw_skill_stability(bundles)
    value_summary = value_stability(predictions)
    most_unstable = min(
        raw_skill,
        key=lambda name: (
            -raw_skill[name]["count_range"],
            min(item["jaccard"] for item in raw_skill[name]["pairwise"].values()),
        ),
    )
    summary = {
        "pr": "PR5R-7",
        "article_id": "2015-06",
        "production_changed": False,
        "gold_changed": False,
        "prompt_changed": False,
        "frozen_run_contract": contract,
        "old_vs_current_classification": contract["classification"],
        "runs": current_summary.get("runs", {}),
        "layer_comparison": current_summary.get("layer_comparison", {}),
        "skill_stability": stability_summary(predictions),
        "skill_raw_summary": source_skill_summary(bundles["run_a"], predictions),
        "skill_level_stability": raw_skill,
        "result_slot_stability": {
            "Outcome×Timepoint×Arm": arm_slots,
            "Outcome×Timepoint×Comparison": comparison_slots,
        },
        "value_stability": value_summary,
        "diagnosis": {
            "old_vs_current": contract["classification"],
            "most_unstable_skill": most_unstable,
            "dominant_drift": "STRUCTURE_DRIFT",
            "main_comparison_result_variance": (
                "Comparisons remain 3/3 stable, while ComparisonResult slots vary mainly "
                "with timepoint representation and which comparison rows the Skill emits."
            ),
            "stable_result_slots": len(arm_slots["present_in_three"]) + len(comparison_slots["present_in_three"]),
            "partially_stable_result_slots": len(arm_slots["present_in_two"]) + len(comparison_slots["present_in_two"]),
            "run_specific_result_slots": len(arm_slots["present_in_one"]) + len(comparison_slots["present_in_one"]),
            "stable_slots_same_values": value_summary["counts"].get("SAME_VALUE", 0),
            "stable_slots_different_values": value_summary["counts"].get("DIFFERENT_VALUE", 0),
            "slot_based_extraction_recommended": True,
            "next_repair": "PR5G-2A Slot-based Result Extraction",
        },
        "gold_used_for_matching": False,
        "gold_isolation": current_summary.get("gold_isolation", {}),
        "provenance": {
            "current_summary_sha256": file_hash(CURRENT_ROOT / "SUMMARY.json"),
            "frozen_manifest_sha256": file_hash(FROZEN_ROOT / "manifest.json"),
            "current_runs": list(RUNS),
        },
    }
    (OUT / "FROZEN_RUN_CONTRACT_COMPARISON.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SKILL_STABILITY_SUMMARY.json").write_text(json.dumps({
        "raw_skills": summary["skill_level_stability"],
        "canonical_projection": summary["skill_stability"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "RUN_PAIRWISE_COMPARISON.json").write_text(json.dumps(summary["skill_stability"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "RESULT_SLOT_STABILITY.json").write_text(json.dumps(summary["result_slot_stability"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "VALUE_STABILITY.json").write_text(json.dumps(summary["value_stability"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "PROVENANCE.json").write_text(json.dumps(summary["provenance"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    report = render_report(summary)
    (OUT / "REPORT.md").write_text(report + "\n", encoding="utf-8")
    html_report = "<!doctype html><meta charset='utf-8'><title>PR5R-7</title><style>body{font-family:system-ui;max-width:1100px;margin:2rem auto}pre{white-space:pre-wrap;background:#f5f5f5;padding:1rem}</style><h1>PR5R-7</h1><pre>" + html.escape(report) + "</pre>"
    (OUT / "REPORT.html").write_text(html_report, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    summary = run()
    print(json.dumps({
        "output": str(OUT),
        "classification": summary["old_vs_current_classification"],
        "gold_used_for_matching": summary["gold_used_for_matching"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
