"""Offline PR5R-3 provenance replay for existing canonical predictions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from article_agent.domain.models import ArticleExtraction
from article_agent.provenance.trace import build_prediction_trace, locate_first_failure

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/provenance_trace_pr5r3"
HIST = ROOT / "outputs/historical_current_evaluator_audit/historical-2015-06-adapted.json"
CURR = ROOT / "benchmarks/2015-06/missingness_v1/CANONICAL_PREDICTION.json"
TARGETS = ROOT / "outputs/entity_attachment_audit/ATTACHMENT_TARGETS.json"
PREVIOUS = ROOT / "outputs/historical_current_evaluator_audit/2015-06_CURRENT_EVALUATOR_COMPARISON.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay_attachment(targets: dict, traces: dict) -> dict:
    paired = {}
    for label in ("historical", "current"):
        trace = traces[label]
        by_result = {x["final"]["final_entity_id"]: x for x in trace["candidates"]}
        rows = []
        for target in targets.get(label, []):
            candidate = by_result.get(target.get("final_prediction_entity"))
            if candidate is None:
                rows.append({
                    "target_id": target.get("target_id"),
                    "trace_candidate_id": None,
                    "first_failure_stage": "UNKNOWN",
                    "first_failure_event": None,
                    "root_cause": "ARTIFACT_NOT_AVAILABLE",
                    "trace_completeness": "NONE",
                })
                continue
            failure = locate_first_failure(candidate)
            rows.append({
                "target_id": target.get("target_id"),
                "trace_candidate_id": candidate["candidate_id"],
                **failure,
            })
        paired[label] = rows
    return paired


def render(payload: dict) -> str:
    lines = [
        "# PR5R-3 — Extraction-to-Result Provenance Trace",
        "",
        "本 PR 只增加 provenance observability，不修改 extraction、prompt、parser、retrieval、result construction、parent binding、normalization、merger、evaluator、Gold、Registry 或 prediction。",
        "",
        "## 可追踪性",
        "",
        "| stage | historical | current |",
        "|---|---|---|",
    ]
    for stage in ("RETRIEVAL", "SKILL_EXTRACTION", "RESULT_CONSTRUCTION", "PARENT_BINDING", "NORMALIZATION", "MERGER", "FINAL_PROJECTION"):
        lines.append(f"| {stage} | {payload['availability']['historical'][stage]} | {payload['availability']['current'][stage]} |")
    lines += [
        "",
        f"- Stable candidate IDs: **{payload['stable_candidate_ids']}**",
        f"- Stable event IDs: **{payload['stable_event_ids']}**",
        f"- PR5R-2 targets: current {payload['pr5r2_targets']['current']} / historical {payload['pr5r2_targets']['historical']}",
        f"- Complete recoverable traces: **{payload['complete_recoverable_targets']}**",
        f"- Still UNKNOWN due unavailable artifacts: **{payload['unknown_targets']}**",
        "",
        "## Benchmark invariance",
        "",
        "Trace replay 只读取已有 prediction/evaluation artifact；未重新评估，因此没有 benchmark 改动。历史/current 数值沿用 PR5R-2 的同 evaluator 结果作为 before/after 参考。",
        "",
        "| metric | historical | current |",
        "|---|---:|---:|",
    ]
    for metric in ("hard_acceptable", "coverage", "supported_value_accuracy", "status_accuracy"):
        h = payload["benchmark"][metric]["historical"]
        c = payload["benchmark"][metric]["current"]
        lines.append(f"| {metric} | {h['numerator']}/{h['denominator']} | {c['numerator']}/{c['denominator']} |")
    lines += [
        "",
        "## 结论",
        "",
        "已有 run 只保留了最终 canonical entity 和少量 source observation，因此 retrieval、construction、parent binding、merger 等中间阶段无法安全恢复。所有无法证明的首次失败都标记为 UNKNOWN/ARTIFACT_NOT_AVAILABLE；没有从 final prediction 反推中间状态。",
        "",
        "下一次正常 extraction 若要完全 traceable，需要在实际 pipeline 的各阶段调用 `TraceBuilder.event()`，并将同一 candidate_id 贯穿到 Result construction、binding、normalization、merge 和 final projection。当前 PR 提供 deterministic ID/event 基础，但未改变现有 production 行为。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    predictions = {
        "historical": ArticleExtraction.model_validate_json(HIST.read_text(encoding="utf-8")),
        "current": ArticleExtraction.model_validate_json(CURR.read_text(encoding="utf-8")),
    }
    traces = {label: build_prediction_trace(prediction) for label, prediction in predictions.items()}
    availability = {label: trace["stages"] for label, trace in traces.items()}
    targets = load(TARGETS) if TARGETS.exists() else {"historical": [], "current": []}
    attachment = replay_attachment(targets, traces)
    complete = sum(
        row["trace_completeness"] == "COMPLETE"
        for rows in attachment.values() for row in rows
    )
    unknown = sum(
        row["first_failure_stage"] == "UNKNOWN"
        for rows in attachment.values() for row in rows
    )
    previous = load(PREVIOUS) if PREVIOUS.exists() else {}
    benchmark = {
        key: {
            label: previous.get(label, {}).get(key, {"numerator": None, "denominator": None})
            for label in ("historical", "current")
        }
        for key in ("hard_acceptable", "coverage", "supported_value_accuracy", "status_accuracy")
    }
    payload = {
        "trace_version": "PR5R-3/1.0",
        "api_calls": 0,
        "re_extraction": False,
        "production_behavior_changed": False,
        "gold_used_for_trace_generation": False,
        "availability": availability,
        "stable_candidate_ids": all(
            len({c["candidate_id"] for c in trace["candidates"]}) == len(trace["candidates"])
            for trace in traces.values()
        ),
        "stable_event_ids": all(
            len({e["event_id"] for e in trace["events"]}) == len(trace["events"])
            for trace in traces.values()
        ),
        "candidate_counts": {label: len(trace["candidates"]) for label, trace in traces.items()},
        "event_counts": {label: len(trace["events"]) for label, trace in traces.items()},
        "pr5r2_targets": {label: len(targets.get(label, [])) for label in ("historical", "current")},
        "complete_recoverable_targets": complete,
        "unknown_targets": unknown,
        "benchmark": benchmark,
        "input_sha256": {
            "historical_prediction": sha(HIST),
            "current_prediction": sha(CURR),
            "pr5r2_targets": sha(TARGETS) if TARGETS.exists() else None,
        },
    }
    (OUT / "PROVENANCE_AVAILABILITY.json").write_text(json.dumps(availability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "CANDIDATE_TRACE.json").write_text(json.dumps(traces, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "PROVENANCE_EVENTS.json").write_text(json.dumps({k: v["events"] for k, v in traces.items()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "RESULT_LINEAGE.json").write_text(json.dumps({k: v["result_lineage"] for k, v in traces.items()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "ATTACHMENT_TRACE_REPLAY.json").write_text(json.dumps(attachment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "RUN_MANIFEST.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SUMMARY.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render(payload), encoding="utf-8")
    print(json.dumps({
        "output": str(OUT),
        "candidate_counts": payload["candidate_counts"],
        "event_counts": payload["event_counts"],
        "complete_recoverable_targets": complete,
        "unknown_targets": unknown,
        "api_calls": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
