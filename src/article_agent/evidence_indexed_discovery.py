"""Evidence-indexed structure discovery for PR5G-2B.

The parser/source adapter creates stable ``SourceUnit`` objects first.  An
optional bounded annotator may label one unit at a time, but it cannot create
entities or decide result cardinality.  Slots are then constructed
deterministically from accepted unit annotations and the frozen topology.

This module is intentionally independent from Gold, Registry and evaluator.
It does not change the legacy free-form extraction path.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain.models import ArticleExtraction
from .slot_result_extraction import (
    ResultSlot,
    SlotContractViolation,
    SlotFill,
    SlotFillResult,
    SlotPlan,
    SourceRef,
    _key,
    _text,
    discover_result_slots,
    validate_slot_fills,
)
from .trial_topology_agent import TrialTopology


class EvidenceIndexedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceUnit(EvidenceIndexedModel):
    source_unit_id: str = Field(min_length=1)
    unit_type: Literal["table_row", "table_header", "source_cell", "paragraph"]
    text: str = Field(min_length=1)
    source_ref: SourceRef
    table_id: str | None = None
    row_id: str | None = None
    column_id: str | None = None
    parent_unit_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SourceUnitIndex(EvidenceIndexedModel):
    schema_version: Literal["SOURCE_UNIT_INDEX/1.0"] = "SOURCE_UNIT_INDEX/1.0"
    article_id: str = Field(min_length=1)
    units: list[SourceUnit] = Field(default_factory=list)
    source_sha256: str
    gold_used: bool = False


class UnitAnnotation(EvidenceIndexedModel):
    source_unit_id: str = Field(min_length=1)
    outcome_span: str | None = None
    timepoint_span: str | None = None
    arm_refs: list[str] = Field(default_factory=list)
    comparison_refs: list[list[str]] = Field(default_factory=list)
    evidence_span: str | None = None
    status: Literal["SUPPORTED", "AMBIGUOUS", "UNRESOLVED"] = "SUPPORTED"
    raw_annotation: dict[str, Any] = Field(default_factory=dict)


class AnnotationContractResult(EvidenceIndexedModel):
    accepted: list[UnitAnnotation] = Field(default_factory=list)
    violations: list[SlotContractViolation] = Field(default_factory=list)
    ambiguities: list[SlotContractViolation] = Field(default_factory=list)


def _stable_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _unit_id(
    unit_type: str,
    *,
    source_id: str | None,
    table_id: str | None,
    row_id: str | None,
    column_id: str | None,
    text: str,
) -> str:
    # Coordinates are preferred over text, so harmless OCR/whitespace changes
    # do not change identity.  Text is the fallback for paragraph-only input.
    coordinates = {
        "unit_type": unit_type,
        "source_id": source_id or "",
        "table_id": table_id or "",
        "row_id": row_id or "",
        "column_id": column_id or "",
    }
    if not any(coordinates[key] for key in ("source_id", "table_id", "row_id", "column_id")):
        coordinates["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return "su-" + _stable_id(coordinates)


def _canonical_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def build_source_unit_index(
    article_id: str,
    source_records: list[dict[str, Any]] | dict[str, Any],
    *,
    markdown: str | None = None,
) -> SourceUnitIndex:
    """Create stable row/header/cell/paragraph units from parser output."""

    if isinstance(source_records, dict):
        records = source_records.get("outcomes", source_records)
        if isinstance(records, dict):
            records = records.get("outcomes", [])
    else:
        records = source_records
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError("source_records must be a list of dictionaries")
    units: list[SourceUnit] = []
    for index, row in enumerate(records):
        table_id = _text(row.get("table_id"))
        row_id = _text(row.get("row_id"))
        text = _canonical_text(row.get("source_evidence") or row.get("outcome_name") or json.dumps(row, ensure_ascii=False))
        source_id = _text(row.get("source_id"))
        if source_id is None:
            if table_id or row_id:
                source_id = f"{article_id}:{table_id or 'source'}:{row_id or 'row'}"
            else:
                source_id = f"{article_id}:record:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
        row_ref = SourceRef(
            source_index=index, source_id=source_id, table_id=table_id, row_id=row_id, quote=text,
        )
        row_unit_id = _unit_id("table_row" if table_id else "paragraph",
                               source_id=source_id, table_id=table_id, row_id=row_id,
                               column_id=None, text=text)
        units.append(SourceUnit(
            source_unit_id=row_unit_id,
            unit_type="table_row" if table_id else "paragraph",
            text=text,
            source_ref=row_ref,
            table_id=table_id,
            row_id=row_id,
            payload=deepcopy(row),
        ))
        column_map = row.get("column_map")
        if isinstance(column_map, dict):
            column_map = list(column_map.values())
        if isinstance(column_map, list):
            header_text = _canonical_text(" | ".join(
                _canonical_text(item.get("header_path") if isinstance(item, dict) else item)
                for item in column_map
            ))
            if header_text:
                header_id = _unit_id("table_header", source_id=source_id, table_id=table_id,
                                     row_id=row_id, column_id=None, text=header_text)
                units.append(SourceUnit(
                    source_unit_id=header_id, unit_type="table_header", text=header_text,
                    source_ref=SourceRef(source_index=index, source_id=source_id,
                                         table_id=table_id, row_id=row_id, quote=header_text),
                    table_id=table_id, row_id=row_id, parent_unit_id=row_unit_id,
                    payload={"column_map": deepcopy(column_map)},
                ))
        cells = row.get("source_cells")
        if isinstance(cells, list):
            for cell_index, cell in enumerate(cells):
                if not isinstance(cell, dict):
                    continue
                cell_text = _canonical_text(cell.get("raw_value") or cell.get("value") or "")
                if not cell_text:
                    continue
                column_id = _text(
                    cell.get("column_id") or cell.get("column") or cell.get("column_index")
                ) or str(cell_index)
                cell_id = _unit_id("source_cell", source_id=source_id, table_id=table_id,
                                   row_id=row_id, column_id=column_id, text=cell_text)
                units.append(SourceUnit(
                    source_unit_id=cell_id, unit_type="source_cell", text=cell_text,
                    source_ref=SourceRef(source_index=index, source_id=source_id,
                                         table_id=table_id, row_id=row_id,
                                         column_id=column_id, quote=cell_text),
                    table_id=table_id, row_id=row_id, column_id=column_id,
                    parent_unit_id=row_unit_id, payload=deepcopy(cell),
                ))
    if markdown:
        for paragraph_index, paragraph in enumerate(re.split(r"\n\s*\n+", markdown)):
            text = _canonical_text(paragraph)
            if not text:
                continue
            source_id = f"{article_id}:paragraph:{paragraph_index}"
            units.append(SourceUnit(
                source_unit_id=_unit_id("paragraph", source_id=source_id, table_id=None,
                                        row_id=None, column_id=None, text=text),
                unit_type="paragraph", text=text,
                source_ref=SourceRef(source_id=source_id, quote=text),
                payload={"paragraph_index": paragraph_index},
            ))
    # Duplicate parser emissions for the same coordinate are retained when
    # their content differs (for example, several outcome records sharing a
    # legacy row_id).  A deterministic content suffix prevents silent loss
    # while keeping equivalent replay order-independent.
    unique: dict[str, SourceUnit] = {}
    for unit in units:
        existing = unique.get(unit.source_unit_id)
        if existing is None:
            unique[unit.source_unit_id] = unit
            continue
        if existing.text == unit.text and existing.payload == unit.payload:
            continue
        candidate_id = unit.source_unit_id + "-" + hashlib.sha256(
            unit.text.encode("utf-8")
        ).hexdigest()[:8]
        unique[candidate_id] = unit.model_copy(update={"source_unit_id": candidate_id})
    ordered = sorted(unique.values(), key=lambda item: (
        item.table_id or "", item.row_id or "", item.column_id or "",
        item.unit_type, item.source_unit_id,
    ))
    serial = json.dumps([unit.model_dump() for unit in ordered], ensure_ascii=False,
                        sort_keys=True, separators=(",", ":"))
    return SourceUnitIndex(
        article_id=article_id, units=ordered,
        source_sha256=hashlib.sha256(serial.encode("utf-8")).hexdigest(),
    )


def _contains_span(span: str | None, text: str) -> bool:
    if not _text(span):
        return False
    tokens = str(span).split()
    return bool(tokens) and re.search(r"\s+".join(re.escape(token) for token in tokens), text, re.I) is not None


def validate_unit_annotations(
    index: SourceUnitIndex,
    annotations: list[UnitAnnotation] | list[dict[str, Any]],
) -> AnnotationContractResult:
    """Enforce one bounded annotation per existing source unit."""

    units = {unit.source_unit_id: unit for unit in index.units}
    accepted: list[UnitAnnotation] = []
    violations: list[SlotContractViolation] = []
    ambiguities: list[SlotContractViolation] = []
    seen: set[str] = set()
    for raw in annotations:
        annotation = raw if isinstance(raw, UnitAnnotation) else UnitAnnotation.model_validate(raw)
        unit = units.get(annotation.source_unit_id)
        if unit is None:
            violations.append(SlotContractViolation(
                slot_id=annotation.source_unit_id,
                reason="unknown source_unit_id; annotation cannot create a source unit",
                raw_fill=annotation.model_dump(),
            ))
            continue
        if annotation.source_unit_id in seen:
            violations.append(SlotContractViolation(
                slot_id=annotation.source_unit_id,
                reason="duplicate bounded annotation for source unit",
                raw_fill=annotation.model_dump(),
            ))
            continue
        seen.add(annotation.source_unit_id)
        if annotation.status == "AMBIGUOUS":
            ambiguities.append(SlotContractViolation(
                slot_id=annotation.source_unit_id,
                reason="ambiguous source-unit annotation; no slot created",
                raw_fill=annotation.model_dump(),
            ))
            continue
        if annotation.status == "UNRESOLVED":
            ambiguities.append(SlotContractViolation(
                slot_id=annotation.source_unit_id,
                reason="unresolved source-unit annotation; no slot created",
                raw_fill=annotation.model_dump(),
            ))
            continue
        if annotation.outcome_span and not _contains_span(annotation.outcome_span, unit.text):
            violations.append(SlotContractViolation(
                slot_id=annotation.source_unit_id,
                reason="outcome_span is not supported by source unit text",
                raw_fill=annotation.model_dump(),
            ))
            continue
        if annotation.timepoint_span and not _contains_span(annotation.timepoint_span, unit.text):
            violations.append(SlotContractViolation(
                slot_id=annotation.source_unit_id,
                reason="timepoint_span is not supported by source unit text",
                raw_fill=annotation.model_dump(),
            ))
            continue
        if annotation.evidence_span and not _contains_span(annotation.evidence_span, unit.text):
            violations.append(SlotContractViolation(
                slot_id=annotation.source_unit_id,
                reason="evidence_span is not supported by source unit text",
                raw_fill=annotation.model_dump(),
            ))
            continue
        accepted.append(annotation)
    return AnnotationContractResult(
        accepted=accepted, violations=violations, ambiguities=ambiguities,
    )


def bounded_annotation_prompt(unit: SourceUnit) -> list[dict[str, str]]:
    payload = {
        "task": "Annotate only this existing source unit; do not create entities or result records.",
        "source_unit": unit.model_dump(),
        "rules": [
            "Return at most one annotation for this source_unit_id.",
            "outcome_span/timepoint_span/evidence_span must be verbatim spans of source_unit.text.",
            "arm_refs and comparison_refs must copy explicit labels from this unit only.",
            "If ambiguous, return status AMBIGUOUS and do not choose a parent.",
            "Do not return outcome_id, arm_id, comparison_id, slot_id, or numeric result values.",
        ],
        "output": {
            "source_unit_id": unit.source_unit_id,
            "outcome_span": None,
            "timepoint_span": None,
            "arm_refs": [],
            "comparison_refs": [],
            "evidence_span": None,
            "status": "SUPPORTED",
        },
    }
    return [
        {"role": "system", "content": "You are a bounded evidence annotator. Return JSON only."},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def annotate_units_with_client(index: SourceUnitIndex, client: Any) -> AnnotationContractResult:
    raw: list[UnitAnnotation] = []
    violations: list[SlotContractViolation] = []
    for unit in index.units:
        response: Any = None
        try:
            response = client.chat_json(bounded_annotation_prompt(unit), temperature=0.0)
            payload = response.get("annotation", response) if isinstance(response, dict) else response
            raw.append(UnitAnnotation.model_validate(payload))
        except Exception as exc:
            violations.append(SlotContractViolation(
                slot_id=unit.source_unit_id,
                reason=f"invalid bounded annotation response: {type(exc).__name__}: {exc}",
                raw_fill={"response": response},
            ))
    checked = validate_unit_annotations(index, raw)
    return AnnotationContractResult(
        accepted=checked.accepted,
        violations=[*violations, *checked.violations],
        ambiguities=checked.ambiguities,
    )


def build_slot_plan_from_annotations(
    article_id: str,
    topology: TrialTopology | dict[str, Any],
    arm_graph: ArticleExtraction | dict[str, Any],
    index: SourceUnitIndex,
    annotations: list[UnitAnnotation] | AnnotationContractResult,
    *,
    trace: Any = None,
) -> SlotPlan:
    """Canonicalise bounded annotations into deterministic result slots."""

    checked = annotations if isinstance(annotations, AnnotationContractResult) else validate_unit_annotations(index, annotations)
    units = {unit.source_unit_id: unit for unit in index.units}
    rows: list[dict[str, Any]] = []
    source_unit_for_index: dict[int, str] = {}
    for row_index, annotation in enumerate(checked.accepted):
        unit = units[annotation.source_unit_id]
        payload = deepcopy(unit.payload)
        payload["source_unit_id"] = unit.source_unit_id
        payload["source_evidence"] = annotation.evidence_span or unit.text
        if annotation.outcome_span:
            payload["outcome_name"] = annotation.outcome_span
            payload["outcomeName"] = annotation.outcome_span
        if annotation.timepoint_span:
            payload["timepoint"] = annotation.timepoint_span
            payload["outcome_observation_timepoint_raw"] = annotation.timepoint_span
        if annotation.arm_refs:
            original_arms = payload.get("arm", payload.get("arms", [])) or []
            if isinstance(original_arms, dict):
                original_arms = [original_arms]
            wanted = {_key(item) for item in annotation.arm_refs}
            payload["arm"] = [
                deepcopy(arm) for arm in original_arms
                if isinstance(arm, dict) and any(
                    _key(arm.get(name)) in wanted
                    for name in ("arm_id", "arm_label", "label")
                )
            ]
            # Explicit arm refs may be the frozen IDs even when the source row
            # has no nested arm object; create only those references, without
            # inventing values.
            existing = {
                _key(next((arm.get(name) for name in ("arm_id", "arm_label", "label")
                           if _text(arm.get(name))), ""))
                for arm in payload["arm"]
            }
            for ref in annotation.arm_refs:
                if _key(ref) not in existing:
                    payload["arm"].append({"arm_id": ref})
        else:
            payload["arm"] = []
        if annotation.comparison_refs:
            payload["comparisons"] = [
                {"arm_ids": list(pair), "contrast": " vs ".join(pair), "relation": "explicit"}
                for pair in annotation.comparison_refs if len(pair) >= 2
            ]
        else:
            payload["comparisons"] = []
            payload.pop("comparison", None)
        rows.append(payload)
        source_unit_for_index[row_index] = unit.source_unit_id
    plan = discover_result_slots(article_id, topology, arm_graph, rows, trace=trace)
    # Attach source unit provenance to every slot.  The existing slot identity
    # remains coordinate-based and therefore stable across equivalent runs.
    updated: list[ResultSlot] = []
    for slot in plan.slots:
        indices = [ref.source_index for ref in slot.source_refs if ref.source_index is not None]
        source_ids = [source_unit_for_index[index] for index in indices if index in source_unit_for_index]
        updated.append(slot.model_copy(update={"source_unit_ids": list(dict.fromkeys(source_ids))}))
    return plan.model_copy(update={"slots": updated})


def run_evidence_indexed_discovery(
    article_id: str,
    source_records: list[dict[str, Any]] | dict[str, Any],
    topology: TrialTopology | dict[str, Any],
    arm_graph: ArticleExtraction | dict[str, Any],
    *,
    markdown: str | None = None,
    annotations: list[UnitAnnotation] | None = None,
    trace: Any = None,
) -> tuple[SourceUnitIndex, AnnotationContractResult, SlotPlan]:
    index = build_source_unit_index(article_id, source_records, markdown=markdown)
    checked = validate_unit_annotations(index, annotations or [])
    plan = build_slot_plan_from_annotations(
        article_id, topology, arm_graph, index, checked, trace=trace,
    )
    return index, checked, plan


__all__ = [
    "AnnotationContractResult", "SourceUnit", "SourceUnitIndex", "UnitAnnotation",
    "annotate_units_with_client", "bounded_annotation_prompt",
    "build_slot_plan_from_annotations", "build_source_unit_index",
    "run_evidence_indexed_discovery", "validate_unit_annotations",
]
