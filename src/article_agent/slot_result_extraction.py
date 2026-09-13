"""Source-supported, slot-based result extraction primitives.

This module deliberately sits beside (and does not replace) the legacy
free-form outcome path.  Structure discovery is deterministic and offline:
it only uses source records plus the already frozen topology/arm graph.  A
caller may then provide slot fills from an LLM or a replay fixture; fills are
contract-checked before deterministic materialisation.

No Gold, evaluator, registry or model-generated entity IDs are used here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain.models import (
    ArmResult,
    ArticleExtraction,
    CanonicalField,
    ComparisonResult,
    Evidence,
    EvidenceTarget,
    FieldStatus,
    Outcome,
)
from .trial_topology_agent import TrialTopology


class SlotModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(SlotModel):
    source_index: int | None = None
    source_id: str | None = None
    table_id: str | None = None
    row_id: str | None = None
    column_id: str | None = None
    quote: str | None = None


class ResultSlot(SlotModel):
    """A source-supported result identity, before numeric value filling."""

    slot_id: str = Field(min_length=1)
    slot_type: Literal["ArmResult", "ComparisonResult"]
    outcome_id: str = Field(min_length=1)
    outcome_name: str = Field(min_length=1)
    instrument: str | None = None
    timepoint_id: str | None = None
    timepoint_raw: str | None = None
    arm_id: str | None = None
    comparison_id: str | None = None
    comparison_arm_ids: list[str] = Field(default_factory=list)
    source_unit_ids: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    discovery_rule: str = Field(min_length=1)
    discovery_evidence: list[str] = Field(default_factory=list)
    status: Literal["SUPPORTED", "AMBIGUOUS", "UNRESOLVED"] = "SUPPORTED"

    @model_validator(mode="after")
    def parent_shape(self) -> "ResultSlot":
        if self.slot_type == "ArmResult" and (not self.arm_id or self.comparison_id):
            raise ValueError("ArmResult slot requires arm_id and no comparison_id")
        if self.slot_type == "ComparisonResult" and (not self.comparison_id or self.arm_id):
            raise ValueError("ComparisonResult slot requires comparison_id and no arm_id")
        if self.slot_type == "ComparisonResult" and len(self.comparison_arm_ids) < 2:
            raise ValueError("ComparisonResult slot requires comparison_arm_ids")
        if self.status == "SUPPORTED" and not self.source_refs:
            raise ValueError("SUPPORTED slot requires source_refs")
        return self


class SlotPlan(SlotModel):
    schema_version: Literal["RESULT_SLOT_PLAN/1.0"] = "RESULT_SLOT_PLAN/1.0"
    article_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    slots: list[ResultSlot] = Field(default_factory=list)
    discovered_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    discovered_timepoints: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    gold_used: bool = False
    registry_used: bool = False


class SlotFill(SlotModel):
    """Values returned for one existing slot.

    ``identity`` is optional for a normal response.  If supplied by a model,
    it is checked against the frozen slot and a mismatch is a contract
    violation, never an instruction to create another slot.
    """

    slot_id: str = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)
    identity: dict[str, Any] = Field(default_factory=dict)
    raw_output: dict[str, Any] = Field(default_factory=dict)


class SlotContractViolation(SlotModel):
    slot_id: str | None = None
    reason: str
    raw_fill: dict[str, Any] = Field(default_factory=dict)


class SlotFillResult(SlotModel):
    accepted: list[SlotFill] = Field(default_factory=list)
    violations: list[SlotContractViolation] = Field(default_factory=list)
    ambiguities: list[SlotContractViolation] = Field(default_factory=list)


class MaterializedResult(SlotModel):
    """Stable, serialisable projection used before optional canonical wiring."""

    result_type: Literal["ArmResult", "ComparisonResult"]
    result_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    arm_id: str | None = None
    comparison_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)


def slot_based_enabled(value: bool | None = None) -> bool:
    """Read the opt-in flag without changing the legacy default."""

    if value is not None:
        return bool(value)
    return os.getenv("SLOT_BASED_RESULT_EXTRACTION", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    if value.casefold() in {"", "nr", "n/r", "not reported", "unknown", "unresolved", "none", "null"}:
        return None
    return value


def _key(value: Any) -> str:
    return " ".join((_text(value) or "").casefold().split())


def _first(data: dict[str, Any], names: tuple[str, ...]) -> Any:
    return next((data[name] for name in names if _text(data.get(name)) is not None), None)


def _outcome_identity(name: str, instrument: str | None) -> tuple[str, str]:
    # Deliberately limited to structural normalization.  No synonym/fuzzy
    # clinical matching is performed in this layer.
    return _key(name), _key(instrument)


def canonical_timepoint(value: Any) -> tuple[str | None, str | None, str]:
    """Return (canonical id, raw value, status) using only explicit syntax."""

    raw = _text(value)
    if raw is None:
        return None, None, "UNRESOLVED"
    low = _key(raw)
    if low in {"baseline", "pre treatment", "pretreatment", "pre-treatment"}:
        return "baseline", raw, "SUPPORTED"
    low = low.replace("first month", "1 month").replace("one month", "1 month")
    low = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", low)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months|year|years)", low)
    if not match:
        # Explicit but non-standard text remains an identity rather than
        # being guessed into a numeric timepoint.
        return f"text:{low}", raw, "SUPPORTED"
    number, unit = match.groups()
    unit = unit.rstrip("s")
    return f"{number} {unit}", raw, "SUPPORTED"


def _stable_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _source_ref(row: dict[str, Any], index: int, *, quote: str | None = None) -> SourceRef:
    return SourceRef(
        source_index=index,
        source_id=_text(row.get("source_id")),
        table_id=_text(row.get("table_id")),
        row_id=_text(row.get("row_id")),
        quote=quote or _text(row.get("source_evidence")),
    )


def _arm_aliases(topology: TrialTopology, arm_graph: ArticleExtraction) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for arm, source_arm in zip(arm_graph.arms, topology.arms, strict=True):
        labels = [arm.arm_id, arm.label.value, source_arm.name, source_arm.source_label, *source_arm.aliases]
        for label in labels:
            if _key(label):
                aliases.setdefault(_key(label), set()).add(arm.arm_id)
    return aliases


def _bind_arm(label: Any, aliases: dict[str, set[str]]) -> str | None:
    found = aliases.get(_key(label), set())
    return next(iter(found)) if len(found) == 1 else None


def _explicit_comparisons(row: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = row.get("comparisons")
    if explicit is None:
        item = row.get("comparison")
        explicit = [item] if isinstance(item, dict) else []
    if isinstance(explicit, dict):
        explicit = [explicit]
    return [item for item in explicit if isinstance(item, dict)]


def _comparison_labels(item: dict[str, Any]) -> list[Any]:
    labels = item.get("arm_ids") or item.get("arm_labels") or []
    if labels and not any(_text(value) for value in labels):
        labels = item.get("arm_labels") or []
    if not labels and _text(item.get("intervention_arm_id")):
        labels = [item["intervention_arm_id"], *(item.get("comparator_arm_ids") or [])]
        if _text(item.get("control_arm_id")):
            labels.append(item["control_arm_id"])
    if not labels and _text(item.get("contrast")):
        parts = re.split(r"\s+vs\.?\s+", str(item["contrast"]), flags=re.I)
        if len(parts) == 2:
            labels = parts
    return list(labels) if isinstance(labels, list) else []


def _slot_source_key(slot: ResultSlot) -> tuple[Any, ...]:
    source = min(
        (
            (ref.table_id or ref.source_id or "", ref.row_id or "", ref.column_id or "", ref.quote or "")
            for ref in slot.source_refs
        ),
        default=("", "", "", ""),
    )
    return (slot.slot_type, slot.outcome_id, slot.timepoint_id or "", slot.arm_id or slot.comparison_id or "", source)


def _source_identity(ref: SourceRef) -> tuple[str, ...]:
    """Prefer stable document coordinates; quote is only a last resort."""

    if ref.table_id or ref.row_id or ref.column_id:
        return (ref.table_id or "", ref.row_id or "", ref.column_id or "")
    return (ref.source_id or "", ref.quote or "")


def discover_result_slots(
    article_id: str,
    topology: TrialTopology | dict[str, Any],
    arm_graph: ArticleExtraction | dict[str, Any],
    source_records: list[dict[str, Any]] | dict[str, Any],
    *,
    trace: Any = None,
) -> SlotPlan:
    """Build a deterministic source-supported slot plan.

    The function never forms an Outcome × Timepoint × Arm product.  A slot is
    created only when that exact parent appears in a source record and can be
    bound to a frozen topology arm/comparison.
    """

    topology = TrialTopology.model_validate(topology.model_dump() if isinstance(topology, TrialTopology) else topology)
    graph = ArticleExtraction.model_validate(arm_graph.model_dump() if isinstance(arm_graph, ArticleExtraction) else arm_graph)
    if graph.article.article_id != article_id or len(graph.studies) != 1:
        raise ValueError("article_id and single frozen study must match")
    if isinstance(source_records, dict):
        records = source_records.get("outcomes", source_records)
        if isinstance(records, dict):
            records = records.get("outcomes", [])
    else:
        records = source_records
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError("source_records must be a list of raw outcome records")
    sid = graph.studies[0].study_id
    aliases = _arm_aliases(topology, graph)
    slots: dict[tuple[Any, ...], ResultSlot] = {}
    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    comparison_identity: dict[str, tuple[str, ...]] = {}
    timepoints: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    if trace is not None:
        trace.global_event(
            stage="RESULT_CONSTRUCTION", event_type="STRUCTURE_DISCOVERY_STARTED",
            after={"record_count": len(records)}, rule_id="source-supported-slot-planner",
        )

    def warn(index: int, message: str) -> None:
        full = f"source[{index}]: {message}"
        if full not in warnings:
            warnings.append(full)

    for index, row in enumerate(records):
        name = _first(row, ("outcome_name", "outcomeName", "name"))
        if not _text(name):
            warn(index, "missing outcome identity")
            continue
        instrument = _first(row, ("measurement_instrument", "instrument", "instrumentRaw"))
        identity = _outcome_identity(str(name), _text(instrument))
        if identity not in outcomes:
            # Provisional identity is content-derived.  Final Oxx numbering
            # is assigned from a sorted identity list below, so source record
            # order cannot change slot IDs.
            oid = "outcome-" + _stable_id({"name": identity[0], "instrument": identity[1]})
            outcomes[identity] = {
                "outcome_id": oid,
                "name": str(name).strip(),
                "instrument": _text(instrument),
                "source_refs": [_source_ref(row, index)],
            }
            if trace is not None:
                trace.global_event(
                    stage="RESULT_CONSTRUCTION", event_type="OUTCOME_DISCOVERED",
                    after=outcomes[identity], rule_id="first-source-outcome-identity",
                    source_refs=[_source_ref(row, index).model_dump()],
                )
        outcome = outcomes[identity]
        tp_value = _first(row, ("timepoint", "outcome_observation_timepoint_raw", "timepoint_raw"))
        # A producer can explicitly expose multiple candidates; abstain rather
        # than choosing one.
        tp_candidates = row.get("timepoint_candidates")
        if isinstance(tp_candidates, list) and len(tp_candidates) > 1:
            timepoint_id, tp_raw, tp_status = None, _text(tp_value), "AMBIGUOUS"
            warn(index, "ambiguous timepoint; no slot parent selected")
        else:
            timepoint_id, tp_raw, tp_status = canonical_timepoint(tp_value)
        if timepoint_id:
            timepoints.setdefault(timepoint_id, {
                "timepoint_id": timepoint_id, "raw_values": [], "source_refs": [],
            })
            if tp_raw and tp_raw not in timepoints[timepoint_id]["raw_values"]:
                timepoints[timepoint_id]["raw_values"].append(tp_raw)
            timepoints[timepoint_id]["source_refs"].append(_source_ref(row, index).model_dump())
            if trace is not None:
                trace.global_event(
                    stage="RESULT_CONSTRUCTION", event_type="TIMEPOINT_DISCOVERED",
                    after={"timepoint_id": timepoint_id, "raw": tp_raw},
                    rule_id="explicit-timepoint-normalization",
                    source_refs=[_source_ref(row, index).model_dump()],
                )
        if tp_status == "AMBIGUOUS" and trace is not None:
            trace.global_event(
                stage="RESULT_CONSTRUCTION", event_type="SLOT_AMBIGUOUS",
                after={"source_index": index, "dimension": "timepoint"},
                rule_id="ambiguous-timepoint-abstain",
                source_refs=[_source_ref(row, index).model_dump()],
            )
        row_ref = _source_ref(row, index)
        arms = row.get("arm", row.get("arms", [])) or []
        if isinstance(arms, dict):
            arms = [arms]
        for arm in arms:
            if not isinstance(arm, dict):
                warn(index, "invalid arm shape")
                continue
            label = next(
                (arm.get(name) for name in ("arm_id", "arm_label", "label") if _text(arm.get(name))),
                None,
            )
            arm_id = _bind_arm(label, aliases)
            if not arm_id:
                warn(index, f"unknown/ambiguous arm binding {label}")
                if trace is not None:
                    trace.global_event(
                        stage="RESULT_CONSTRUCTION", event_type="SLOT_REJECTED",
                        after={"slot_type": "ArmResult", "label": label},
                        rule_id="frozen-arm-binding-required",
                        source_refs=[row_ref.model_dump()],
                    )
                continue
            if tp_status == "AMBIGUOUS":
                continue
            structure = {
                "slot_type": "ArmResult", "outcome_id": outcome["outcome_id"],
                "timepoint_id": timepoint_id, "arm_id": arm_id,
                "table_id": row_ref.table_id, "row_id": row_ref.row_id,
            }
            slot_id = "slot-" + _stable_id(structure)
            slot = ResultSlot(
                slot_id=slot_id, slot_type="ArmResult", outcome_id=outcome["outcome_id"],
                outcome_name=outcome["name"], instrument=outcome["instrument"],
                timepoint_id=timepoint_id, timepoint_raw=tp_raw, arm_id=arm_id,
                source_refs=[row_ref], discovery_rule="explicit-row-arm-binding",
                discovery_evidence=[row_ref.quote] if row_ref.quote else [],
            )
            key = (slot.slot_type, slot.outcome_id, slot.timepoint_id, slot.arm_id)
            if key in slots:
                slots[key].source_refs = sorted(
                    {ref.model_dump_json(): ref for ref in [*slots[key].source_refs, row_ref]}.values(),
                    key=lambda ref: (ref.table_id or "", ref.row_id or "", ref.source_index or -1),
                )
                slots[key].discovery_evidence = list(dict.fromkeys(
                    [*slots[key].discovery_evidence, *( [row_ref.quote] if row_ref.quote else [])]
                ))
            else:
                slots[key] = slot
                if trace is not None:
                    trace.global_event(
                        stage="RESULT_CONSTRUCTION", event_type="SLOT_CREATED",
                        after=slot.model_dump(), rule_id=slot.discovery_rule,
                        source_refs=[row_ref.model_dump()],
                    )

        for comparison in _explicit_comparisons(row):
            labels = _comparison_labels(comparison)
            bound = [_bind_arm(label, aliases) for label in labels]
            if len(bound) < 2 or None in bound or len(set(bound)) != len(bound):
                if labels or _text(comparison.get("contrast")):
                    warn(index, "comparison participants not uniquely explicit")
                continue
            if not (_text(comparison.get("contrast")) or _text(comparison.get("relation"))):
                warn(index, "arm list alone does not establish a reported comparison")
                continue
            comparison_key = tuple(bound)
            # Reuse an existing frozen comparison when one is supplied in the
            # graph; otherwise allocate only for this explicitly reported pair.
            existing = next((item for item in graph.comparisons if tuple(item.arm_ids) == comparison_key), None)
            if existing is None:
                # A slot planner may represent an explicit source comparison
                # without mutating the frozen graph. The deterministic ID is
                # local to the plan and is materialised only if accepted.
                # Comparison numbering is finalised from sorted arm tuples;
                # never use encounter order for identity.
                cid = "comparison-" + _stable_id({"arms": comparison_key})
                comparison_identity[cid] = comparison_key
            else:
                cid = existing.comparison_id
            if tp_status == "AMBIGUOUS":
                continue
            structure = {
                "slot_type": "ComparisonResult", "outcome_id": outcome["outcome_id"],
                "timepoint_id": timepoint_id, "comparison_id": cid,
                "table_id": row_ref.table_id, "row_id": row_ref.row_id,
            }
            slot = ResultSlot(
                slot_id="slot-" + _stable_id(structure), slot_type="ComparisonResult",
                outcome_id=outcome["outcome_id"], outcome_name=outcome["name"],
                instrument=outcome["instrument"], timepoint_id=timepoint_id,
                timepoint_raw=tp_raw, comparison_id=cid, source_refs=[row_ref],
                comparison_arm_ids=list(bound),
                discovery_rule="explicit-comparison-binding",
                discovery_evidence=[row_ref.quote] if row_ref.quote else [],
            )
            key = (slot.slot_type, slot.outcome_id, slot.timepoint_id, slot.comparison_id)
            if key in slots:
                slots[key].source_refs = sorted(
                    {ref.model_dump_json(): ref for ref in [*slots[key].source_refs, row_ref]}.values(),
                    key=lambda ref: (ref.table_id or "", ref.row_id or "", ref.source_index or -1),
                )
            else:
                slots[key] = slot
                if trace is not None:
                    trace.global_event(
                        stage="RESULT_CONSTRUCTION", event_type="SLOT_CREATED",
                        after=slot.model_dump(), rule_id=slot.discovery_rule,
                        source_refs=[row_ref.model_dump()],
                    )

    # Freeze deterministic entity numbering independently of source order.
    outcome_ids = {
        identity: f"{sid}-O{index:02d}"
        for index, identity in enumerate(sorted(outcomes), start=1)
    }
    comparison_pairs = sorted(set(comparison_identity.values()))
    comparison_ids: dict[str, str] = {}
    for index, pair in enumerate(comparison_pairs, start=1):
        comparison_ids["comparison-" + _stable_id({"arms": pair})] = f"{sid}-C{index:02d}"
    finalized: list[ResultSlot] = []
    for slot in slots.values():
        update: dict[str, Any] = {}
        old_outcome = next(
            (identity for identity, value in outcomes.items() if value["outcome_id"] == slot.outcome_id),
            None,
        )
        if old_outcome is not None:
            update["outcome_id"] = outcome_ids[old_outcome]
        if slot.comparison_id in comparison_ids:
            update["comparison_id"] = comparison_ids[slot.comparison_id]
        candidate = slot.model_copy(update=update, deep=True)
        structure = {
            "slot_type": candidate.slot_type,
            "outcome_id": candidate.outcome_id,
            "timepoint_id": candidate.timepoint_id,
            "arm_id": candidate.arm_id,
            "comparison_id": candidate.comparison_id,
            "source_identity": min((_source_identity(ref) for ref in candidate.source_refs),
                default=("", "", "", ""),
            ),
        }
        finalized.append(candidate.model_copy(update={"slot_id": "slot-" + _stable_id(structure)}))
    discovered_outcomes = []
    for identity, item in sorted(outcomes.items(), key=lambda entry: outcome_ids[entry[0]]):
        discovered_outcomes.append({**item, "outcome_id": outcome_ids[identity]})
    ordered_slots = sorted(finalized, key=_slot_source_key)
    return SlotPlan(
        article_id=article_id,
        study_id=sid,
        slots=ordered_slots,
        discovered_outcomes=discovered_outcomes,
        discovered_timepoints=sorted(timepoints.values(), key=lambda item: item["timepoint_id"]),
        warnings=warnings,
    )


_ALLOWED_FILL_FIELDS = {
    "timepoint", "timepoint_value", "timepoint_unit", "analysis_set", "value_kind",
    "value", "standard_deviation", "change_from_baseline", "dispersion_lower",
    "dispersion_upper", "n", "event_count", "denominator", "raw_value",
    "effect_measure", "estimate", "confidence_interval_lower",
    "confidence_interval_upper", "p_value", "p_value_comparator",
}


def validate_slot_fills(plan: SlotPlan, fills: list[SlotFill] | list[dict[str, Any]]) -> SlotFillResult:
    """Accept only fills for existing slots; reject identity expansion."""

    lookup = {slot.slot_id: slot for slot in plan.slots}
    accepted: list[SlotFill] = []
    violations: list[SlotContractViolation] = []
    ambiguities: list[SlotContractViolation] = []
    for raw in fills:
        fill = raw if isinstance(raw, SlotFill) else SlotFill.model_validate(raw)
        slot = lookup.get(fill.slot_id)
        if slot is None:
            violations.append(SlotContractViolation(
                slot_id=fill.slot_id, reason="unknown slot_id; model attempted to create a slot",
                raw_fill=fill.model_dump(),
            ))
            continue
        identity = fill.identity
        expected = {
            "outcome_id": slot.outcome_id, "timepoint_id": slot.timepoint_id,
            "arm_id": slot.arm_id, "comparison_id": slot.comparison_id,
        }
        mismatches = [key for key, value in identity.items() if key in expected and value != expected[key]]
        forbidden = set(fill.values) - _ALLOWED_FILL_FIELDS
        if mismatches or forbidden:
            reason = []
            if mismatches:
                reason.append("identity mismatch: " + ",".join(sorted(mismatches)))
            if forbidden:
                reason.append("forbidden fields: " + ",".join(sorted(forbidden)))
            violations.append(SlotContractViolation(
                slot_id=fill.slot_id, reason="; ".join(reason),
                raw_fill=fill.model_dump(),
            ))
            continue
        if slot.status == "AMBIGUOUS":
            ambiguities.append(SlotContractViolation(
                slot_id=fill.slot_id, reason="ambiguous slot cannot be force-filled",
                raw_fill=fill.model_dump(),
            ))
            continue
        accepted.append(fill)
    return SlotFillResult(accepted=accepted, violations=violations, ambiguities=ambiguities)


def materialize_slot_fills(plan: SlotPlan, fills: list[SlotFill] | SlotFillResult) -> list[MaterializedResult]:
    """Materialise only accepted slots in deterministic slot order."""

    accepted = fills.accepted if isinstance(fills, SlotFillResult) else validate_slot_fills(plan, fills).accepted
    by_id = {fill.slot_id: fill for fill in accepted}
    arm_index = comp_index = 0
    output: list[MaterializedResult] = []
    for slot in plan.slots:
        fill = by_id.get(slot.slot_id)
        if fill is None:
            continue
        if slot.slot_type == "ArmResult":
            arm_index += 1
            result_id = f"{plan.study_id}-AR{arm_index:03d}"
        else:
            comp_index += 1
            result_id = f"{plan.study_id}-CR{comp_index:03d}"
        output.append(MaterializedResult(
            result_type=slot.slot_type, result_id=result_id, slot_id=slot.slot_id,
            outcome_id=slot.outcome_id, arm_id=slot.arm_id,
            comparison_id=slot.comparison_id, fields=deepcopy(fill.values),
            source_refs=sorted(
                {ref.model_dump_json(): ref for ref in [*slot.source_refs, *fill.source_refs]}.values(),
                key=lambda ref: (ref.table_id or "", ref.row_id or "", ref.source_index or -1),
            ),
        ))
    return output


def materialize_canonical_results(
    plan: SlotPlan,
    fills: list[SlotFill] | SlotFillResult,
) -> tuple[list[ArmResult], list[ComparisonResult], list[Evidence]]:
    """Create canonical result entities without changing the frozen graph.

    This helper is intentionally conservative: fields without a supplied
    value remain UNRESOLVED, and evidence is emitted only for supplied fields.
    """

    materialized = materialize_slot_fills(plan, fills)
    evidence: list[Evidence] = []
    arm_results: list[ArmResult] = []
    comparison_results: list[ComparisonResult] = []

    def field(value: Any, *, eid: str | None = None) -> CanonicalField[Any]:
        if value is None:
            return CanonicalField(status=FieldStatus.UNRESOLVED)
        return CanonicalField(status=FieldStatus.PRESENT, value=value, raw_value=str(value),
                              evidence_ids=[eid] if eid else [])

    def add_evidence(result_type: str, result_id: str, field_name: str, refs: list[SourceRef], value: Any) -> str:
        eid = f"{result_id}-E{len(evidence) + 1:03d}"
        ref = refs[0] if refs else SourceRef()
        evidence.append(Evidence(
            evidence_id=eid,
            targets=[EvidenceTarget(entity_type=result_type, entity_id=result_id, field_id=field_name)],
            quote=ref.quote or f"slot {result_id} {field_name}: {value}",
            source_type="table" if ref.table_id else "markdown",
            source_id=ref.source_id or ref.table_id or f"{plan.article_id}:slot",
            table_id=ref.table_id, row_id=ref.row_id,
        ))
        return eid

    arm_fields = (
        "timepoint", "timepoint_value", "timepoint_unit", "analysis_set", "value_kind",
        "value", "standard_deviation", "change_from_baseline", "dispersion_lower",
        "dispersion_upper", "n", "event_count", "denominator", "raw_value",
    )
    comparison_fields = (
        "timepoint", "timepoint_value", "timepoint_unit", "analysis_set", "effect_measure",
        "estimate", "confidence_interval_lower", "confidence_interval_upper", "p_value",
        "p_value_comparator", "raw_value",
    )
    for item in materialized:
        values = item.fields
        if item.result_type == "ArmResult":
            kwargs: dict[str, Any] = {
                "arm_result_id": item.result_id, "outcome_id": item.outcome_id,
                "arm_id": item.arm_id,
            }
            for name in arm_fields:
                value = values.get(name)
                eid = add_evidence("ArmResult", item.result_id, name, item.source_refs, value) if value is not None else None
                kwargs[name] = field(value, eid=eid)
            arm_results.append(ArmResult(**kwargs))
        else:
            kwargs = {
                "comparison_result_id": item.result_id, "outcome_id": item.outcome_id,
                "comparison_id": item.comparison_id,
            }
            for name in comparison_fields:
                value = values.get(name)
                eid = add_evidence("ComparisonResult", item.result_id, name, item.source_refs, value) if value is not None else None
                kwargs[name] = field(value, eid=eid)
            comparison_results.append(ComparisonResult(**kwargs))
    return arm_results, comparison_results, evidence


def build_slot_filling_prompt(slot: ResultSlot, source_text: str) -> list[dict[str, str]]:
    """Small, constrained prompt used by an optional caller/API adapter."""

    system = (
        "You fill one existing clinical result slot. Return JSON only. "
        "Do not create or rename outcomes, timepoints, arms, comparisons, or slots. "
        "If a value is not explicitly supported, omit it. Preserve raw source representation."
    )
    user = {
        "task": "Fill only the supplied ResultSlot.",
        "slot": slot.model_dump(),
        "allowed_fields": sorted(_ALLOWED_FILL_FIELDS),
        "source_text": source_text,
        "output": {"slot_id": slot.slot_id, "values": {}, "identity": {}},
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def fill_slots_with_client(
    plan: SlotPlan,
    source_text_by_slot: dict[str, str],
    client: Any,
    *,
    trace: Any = None,
) -> SlotFillResult:
    """Ask an injected JSON client to fill existing slots one at a time.

    The client is deliberately duck-typed so this layer stays independent of
    a specific gateway.  Any malformed response becomes a contract violation;
    it can never expand the plan.
    """

    raw_fills: list[SlotFill] = []
    violations: list[SlotContractViolation] = []
    for slot in plan.slots:
        response: Any = None
        if trace is not None:
            trace.global_event(
                stage="RESULT_CONSTRUCTION", event_type="SLOT_FILL_STARTED",
                after={"slot_id": slot.slot_id}, rule_id="one-slot-request",
            )
        try:
            response = client.chat_json(
                build_slot_filling_prompt(slot, source_text_by_slot.get(slot.slot_id, "")),
                temperature=0.0,
            )
            payload = response.get("fill", response) if isinstance(response, dict) else response
            raw_fills.append(SlotFill.model_validate(payload))
        except Exception as exc:
            violation = SlotContractViolation(
                slot_id=slot.slot_id,
                reason=f"invalid slot fill response: {type(exc).__name__}: {exc}",
                raw_fill={"response": response},
            )
            violations.append(violation)
            if trace is not None:
                trace.global_event(
                    stage="RESULT_CONSTRUCTION", event_type="SLOT_FILL_CONTRACT_VIOLATION",
                    after=violation.model_dump(), rule_id="strict-slot-fill-json",
                )
    checked = validate_slot_fills(plan, raw_fills)
    if violations:
        checked = SlotFillResult(
            accepted=checked.accepted,
            violations=[*violations, *checked.violations],
            ambiguities=checked.ambiguities,
        )
    if trace is not None:
        for fill in checked.accepted:
            trace.global_event(
                stage="RESULT_CONSTRUCTION", event_type="SLOT_FILLED",
                after=fill.model_dump(), rule_id="existing-slot-only",
            )
    return checked


def run_result_extraction(
    source_records: list[dict[str, Any]] | dict[str, Any],
    topology: TrialTopology | dict[str, Any],
    arm_graph: ArticleExtraction | dict[str, Any],
    *,
    article_id: str,
    legacy_path: Any,
    slot_fills: list[SlotFill] | list[dict[str, Any]] | None = None,
    use_slot_based: bool | None = None,
    trace: Any = None,
) -> Any:
    """Feature-flagged adapter preserving the legacy free-form path."""

    if not slot_based_enabled(use_slot_based):
        return legacy_path(source_records)
    plan = discover_result_slots(article_id, topology, arm_graph, source_records, trace=trace)
    checked = validate_slot_fills(plan, slot_fills or [])
    if trace is not None:
        trace.global_event(
            stage="RESULT_CONSTRUCTION", event_type="SLOT_FILL_STARTED",
            after={"slot_count": len(plan.slots)}, rule_id="slot-fill-contract",
        )
        for fill in checked.accepted:
            trace.global_event(
                stage="RESULT_CONSTRUCTION", event_type="SLOT_FILLED",
                after=fill.model_dump(), rule_id="existing-slot-only",
            )
        for violation in checked.violations:
            trace.global_event(
                stage="RESULT_CONSTRUCTION", event_type="SLOT_FILL_CONTRACT_VIOLATION",
                after=violation.model_dump(), rule_id="reject-new-slot-or-identity",
            )
    return {
        "slot_plan": plan,
        "slot_fills": checked,
        "materialized": materialize_slot_fills(plan, checked),
    }


__all__ = [
    "MaterializedResult", "ResultSlot", "SlotContractViolation", "SlotFill",
    "SlotFillResult", "SlotPlan", "SourceRef", "build_slot_filling_prompt",
    "fill_slots_with_client",
    "canonical_timepoint", "discover_result_slots", "materialize_canonical_results",
    "materialize_slot_fills", "run_result_extraction", "slot_based_enabled",
    "validate_slot_fills",
]
