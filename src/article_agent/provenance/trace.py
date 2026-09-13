"""Read-only, deterministic provenance trace primitives.

The functions in this module do not call extraction code or an API.  They can
be used by a future pipeline to emit events, and can also replay the limited
provenance retained in existing canonical predictions.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

STAGES = (
    "RETRIEVAL",
    "SKILL_EXTRACTION",
    "RESULT_CONSTRUCTION",
    "PARENT_BINDING",
    "NORMALIZATION",
    "MERGER",
    "FINAL_PROJECTION",
)


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_candidate_id(*, article_id: str, skill_name: str, context_hash: str,
                        source_ref: dict[str, Any], local_index: int,
                        structural_identity: dict[str, Any] | None = None) -> str:
    payload = {
        "article_id": article_id,
        "skill_name": skill_name,
        "context_hash": context_hash,
        "source_ref": source_ref,
        "local_index": local_index,
        "structural_identity": structural_identity or {},
    }
    return "cand-" + hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()[:24]


def stable_event_id(candidate_id: str, stage: str, event_type: str,
                    before: Any, after: Any, rule_id: str, ordinal: int = 0) -> str:
    payload = {
        "candidate_id": candidate_id,
        "stage": stage,
        "event_type": event_type,
        "before": before,
        "after": after,
        "rule_id": rule_id,
        "ordinal": ordinal,
    }
    return "evt-" + hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()[:24]


def locate_first_failure(trace: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative first-failure result for a stage trace."""
    stages = trace.get("stages", {})
    if any(stages.get(stage, {}).get("availability") != "AVAILABLE" for stage in STAGES):
        return {
            "first_failure_stage": "UNKNOWN",
            "first_failure_event": None,
            "root_cause": "ARTIFACT_NOT_AVAILABLE",
            "trace_completeness": "PARTIAL",
        }
    for stage in ("SKILL_EXTRACTION", "RESULT_CONSTRUCTION", "PARENT_BINDING",
                  "NORMALIZATION", "MERGER", "FINAL_PROJECTION"):
        for event in trace.get("events", []):
            if event.get("stage") != stage:
                continue
            if event.get("event_type") in {"PARENT_REMOVED", "PARENT_REPLACED"}:
                return {
                    "first_failure_stage": stage,
                    "first_failure_event": event["event_id"],
                    "root_cause": event.get("reason_code", "OTHER"),
                    "trace_completeness": "COMPLETE",
                }
    return {
        "first_failure_stage": "UNKNOWN",
        "first_failure_event": None,
        "root_cause": "OTHER",
        "trace_completeness": "COMPLETE",
    }


class TraceBuilder:
    """Small deterministic event builder for future pipeline instrumentation."""

    def __init__(self, candidate: dict[str, Any]):
        self.candidate = deepcopy(candidate)
        self.events: list[dict[str, Any]] = []

    def event(self, *, stage: str, event_type: str, before: Any = None,
              after: Any = None, rule_id: str = "unspecified",
              input_refs: list[str] | None = None,
              source_refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        ordinal = len(self.events)
        event = {
            "event_id": stable_event_id(
                self.candidate["candidate_id"], stage, event_type,
                before, after, rule_id, ordinal,
            ),
            "candidate_id": self.candidate["candidate_id"],
            "result_id": self.candidate.get("constructed_result_id"),
            "stage": stage,
            "event_type": event_type,
            "before": deepcopy(before),
            "after": deepcopy(after),
            "rule_id": rule_id,
            "input_refs": list(input_refs or []),
            "source_refs": deepcopy(source_refs or []),
            "reason_code": rule_id,
        }
        self.events.append(event)
        return event

    def finish(self) -> dict[str, Any]:
        result = deepcopy(self.candidate)
        result["events"] = deepcopy(self.events)
        result["failure_localization"] = locate_first_failure(result)
        return result


def _field_value(entity: Any, name: str) -> Any:
    value = getattr(entity, name, None)
    if hasattr(value, "status"):
        return value.value if value.status.value == "PRESENT" else value.status.value
    return value


def _source_refs(entity: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    legacy = getattr(entity, "legacy_fields", {}) or {}
    observations = legacy.get("source_observations", [])
    if not isinstance(observations, list):
        observations = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        refs.append({
            "source_index": obs.get("source_index"),
            "table_id": obs.get("table_id"),
            "row_id": obs.get("row_id"),
        })
    if not refs:
        refs.append({
            "source_index": None,
            "table_id": getattr(entity, "source_table_id", None),
            "row_id": getattr(entity, "source_row_id", None),
        })
    return refs


def build_prediction_trace(prediction: Any, *, mode: str = "replay") -> dict[str, Any]:
    """Build a deterministic, conservative trace from a canonical prediction.

    Existing predictions normally contain final entities and sometimes source
    observation references.  Missing intermediate stages are explicitly
    marked unavailable; no parent is inferred from Gold or from a value.
    """
    article_id = prediction.article.article_id
    candidates: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    entities = [
        ("ArmResult", prediction.arm_results),
        ("ComparisonResult", prediction.comparison_results),
    ]
    ordinal = 0
    for entity_type, items in entities:
        for entity in items:
            refs = _source_refs(entity)
            source = refs[0]
            context_hash = hashlib.sha256(_stable(refs).encode("utf-8")).hexdigest()
            candidate_id = stable_candidate_id(
                article_id=article_id,
                skill_name="outcome-result",
                context_hash=context_hash,
                source_ref=source,
                local_index=ordinal,
                structural_identity={
                    "entity_type": entity_type,
                    "source_table_id": getattr(entity, "source_table_id", None),
                    "source_row_id": getattr(entity, "source_row_id", None),
                    "result_id": getattr(entity, "arm_result_id", getattr(entity, "comparison_result_id", None)),
                },
            )
            result_id = getattr(entity, "arm_result_id", getattr(entity, "comparison_result_id", None))
            parent = {
                "outcome": _field_value(entity, "outcome_id"),
                "arm": _field_value(entity, "arm_id"),
                "comparison": _field_value(entity, "comparison_id"),
                "timepoint": {
                    "raw": _field_value(entity, "timepoint"),
                    "value": _field_value(entity, "timepoint_value"),
                    "unit": _field_value(entity, "timepoint_unit"),
                },
                "statistic_kind": _field_value(entity, "value_kind"),
            }
            legacy = getattr(entity, "legacy_fields", {}) or {}
            source_obs = legacy.get("source_observations", [])
            candidate = {
                "candidate_id": candidate_id,
                "skill_name": "outcome-result",
                "skill_version": "NOT_AVAILABLE",
                "context_hash": context_hash,
                "source": {"references": refs, "evidence": []},
                "raw_extraction": {
                    "raw_outcome": None,
                    "raw_arm": None,
                    "raw_comparison": None,
                    "raw_timepoint": None,
                    "raw_statistic_kind": None,
                    "raw_value": _field_value(entity, "raw_value"),
                },
                "constructed_result_id": result_id,
                "entity_type": entity_type,
                "parent_state": parent,
                "merger": {
                    "merge_candidates": [],
                    "merge_rule": "NOT_AVAILABLE",
                    "merge_result": None,
                    "survivor": None,
                    "dropped_candidate": None,
                    "reason": "ARTIFACT_NOT_AVAILABLE",
                },
                "final": {
                    "final_entity_id": result_id,
                    "final_parent_ids": parent,
                    "final_field": "result",
                },
                "stages": {
                    "RETRIEVAL": {"availability": "NOT_AVAILABLE"},
                    "SKILL_EXTRACTION": {
                        "availability": "PARTIAL" if source_obs else "NOT_AVAILABLE",
                        "reason": "source_observations retained" if source_obs else "no skill artifact",
                    },
                    "RESULT_CONSTRUCTION": {"availability": "NOT_AVAILABLE"},
                    "PARENT_BINDING": {"availability": "NOT_AVAILABLE"},
                    "NORMALIZATION": {
                        "availability": "PARTIAL" if legacy.get("result_surface") else "NOT_AVAILABLE",
                    },
                    "MERGER": {"availability": "NOT_AVAILABLE"},
                    "FINAL_PROJECTION": {"availability": "AVAILABLE"},
                },
            }
            builder = TraceBuilder(candidate)
            builder.event(
                stage="FINAL_PROJECTION",
                event_type="FINAL_RESULT_EMITTED",
                after={"result_id": result_id, "parent": parent},
                rule_id="final-canonical-observation",
                source_refs=refs,
            )
            complete = builder.finish()
            candidates.append(complete)
            events.extend(complete["events"])
            lineage.append({
                "candidate_id": candidate_id,
                "constructed_result_id": result_id,
                "final_entity_id": result_id,
                "entity_type": entity_type,
                "parent": parent,
            })
            ordinal += 1
    availability = {}
    for stage in STAGES:
        values = [c["stages"][stage]["availability"] for c in candidates]
        availability[stage] = (
            "AVAILABLE" if values and all(v == "AVAILABLE" for v in values)
            else ("PARTIAL" if any(v in {"AVAILABLE", "PARTIAL"} for v in values) else "NOT_AVAILABLE")
        )
    return {
        "trace_version": "PR5R-3/1.0",
        "mode": mode,
        "article_id": article_id,
        "gold_used": False,
        "api_calls": 0,
        "stages": availability,
        "candidates": candidates,
        "events": events,
        "result_lineage": lineage,
    }
