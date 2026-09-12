"""Internal derived ArticleExtraction/2.0 projection. Never consumes Gold or a judge."""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json

from ..domain.models import ArticleExtraction, CanonicalField, Evidence, EvidenceTarget
from .field_binding import arm_cell, bind_comparison_scalar, linked_rows
from .statistic_surface import recognize_mean
from .surface_normalization import normalize_contrast_conflict


@dataclass
class SurfaceProjection:
    prediction: ArticleExtraction
    statistic_events: list[dict] = field(default_factory=list)
    source_bindings: list[dict] = field(default_factory=list)
    conflict_events: list[dict] = field(default_factory=list)


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _repair(graph, entity, entity_type, entity_id, field_name, value, event, context, *, raw_scalar=None):
    previous = getattr(entity, field_name)
    ids = sorted(set(previous.evidence_ids + [
        eid for c in previous.conflict_candidates for eid in c.evidence_ids]))
    trace = entity.legacy_fields.setdefault("result_surface", {"raw_fields": {}, "events": []})
    trace["raw_fields"].setdefault(field_name, previous.model_dump(mode="json"))
    trace["events"].append(deepcopy(event))
    # Existing evidence objects and their reciprocal targets are retained verbatim.
    evidence_id = "RS-" + _hash([entity_type, entity_id, field_name, event])
    evidence = Evidence(
        evidence_id=evidence_id,
        targets=[EvidenceTarget(entity_type=entity_type, entity_id=entity_id, field_id=field_name)],
        quote=event.get("source_quote") or json.dumps(event.get("source_cue", event), ensure_ascii=False),
        source_type="table" if event.get("table_id") else "other",
        source_id=event.get("source_ref") or context.get("source_ref") or "existing-prediction",
        table_id=event.get("table_id"), row_id=event.get("row_id"),
        cell_refs=[str(event["column_index"])] if event.get("column_index") is not None else [],
        support_type="derived", derivation=event["rule"],
        legacy_fields={"source_evidence_ids": ids, "normalization_event": deepcopy(event),
                       "source_document_sha256": context.get("source_document_sha256")},
    )
    graph.evidence.append(evidence)
    setattr(entity, field_name, CanonicalField(
        status="PRESENT", value=value,
        raw_value=raw_scalar if raw_scalar is not None else previous.raw_value,
        evidence_ids=ids + [evidence_id]))


def _normalize_statistics(raw, projected, context, events, bindings):
    for source, result in zip(raw.arm_results, projected.arm_results, strict=True):
        if source.value_kind.status != "PRESENT" or source.value_kind.value != "other":
            continue  # No absence resolution, synonym coding or overwrite of a known kind.
        event = {"entity_id": result.arm_result_id, "entity_type": "ArmResult", "field": "value_kind",
                 "raw_value_kind": source.value_kind.value, "canonical_value_kind": source.value_kind.value,
                 "raw_field": source.value_kind.model_dump(mode="json"), "changed": False,
                 "rule": None, "blocker": None, "source_cue": None,
                 "source_evidence_reference": list(source.value_kind.evidence_ids)}
        rows = linked_rows(source, context, source.value_kind, raw.evidence)
        if not source.value_kind.evidence_ids or len(rows) != 1:
            event["blocker"] = "STATISTIC_SOURCE_ROW_NOT_UNIQUE"
            events.append(event)
            continue
        table, rid, cells = rows[0]
        cell = arm_cell(source, raw, table, cells)
        if not cell or cell["raw_cell"].get("colspan", 1) != 1 or cell["raw_cell"].get("rowspan", 1) != 1:
            event["blocker"] = "ARM_STATISTIC_CELL_NOT_UNIQUE"
            events.append(event)
            continue
        label = str(cells[0]["raw_cell"]["raw_value"]) if cells else ""
        cue = recognize_mean(str(cell["raw_cell"]["raw_value"]),
                             " | ".join(cell["header_path"]), context.get("reporting_statements", []), label)
        event.update(table_id=table["table_id"], row_id=rid, column_index=cell["column_index"],
                     header_path=cell["header_path"], source_ref=table["source_ref"], source_cue=cue)
        if cue is None:
            event["blocker"] = "EXPLICIT_MEAN_SD_SUPPORT_ABSENT"
            events.append(event)
            continue
        # This checks consistency AFTER the structural cell was selected, never searches by numbers.
        observed = ((source.value, cue["mean_scalar"]), (source.standard_deviation, cue["sd_scalar"]))
        if any(f.status == "PRESENT" and f.value != float(scalar) for f, scalar in observed):
            event["blocker"] = "EXISTING_VALUE_AND_SCOPED_SOURCE_DISAGREE"
            events.append(event)
            continue
        event.update(changed=True, canonical_value_kind="mean",
                     rule="STATISTIC_KIND_MEAN_FROM_MEAN_SD_STRUCTURE")
        _repair(projected, result, "ArmResult", result.arm_result_id, "value_kind", "mean", event, context)
        events.append(event)
        # A scalar binding is recorded for the already-present mean and SD. Missing
        # scalar fields are not filled; values and their source evidence are not replaced.
        for field_name, scalar in (("value", cue["mean_scalar"]), ("standard_deviation", cue["sd_scalar"])):
            original = getattr(source, field_name)
            if original.status == "PRESENT":
                bindings.append({
                    "entity_id": result.arm_result_id, "entity_type": "ArmResult", "field": field_name,
                    "raw_source_container": cell["raw_cell"]["raw_value"],
                    "raw_field": original.model_dump(mode="json"), "selected_source_scalar": scalar,
                    "table_id": table["table_id"], "row_id": rid, "column_index": cell["column_index"],
                    "header_path": cell["header_path"], "arm_id": result.arm_id,
                    "outcome_id": result.outcome_id, "timepoint": result.timepoint.model_dump(mode="json"),
                    "source_ref": table["source_ref"], "source_cue": cue,
                    "evidence_ids": list(original.evidence_ids),
                    "binding_result": "BOUND", "binding_confidence": "EXACT_STRUCTURAL_BINDING",
                    "binding_rule": "EXPLICIT_MEAN_SD_COMPONENT", "blockers": [],
                    "changed": False,
                })


def _normalize_comparisons(raw, projected, context, bindings):
    for source, result in zip(raw.comparison_results, projected.comparison_results, strict=True):
        if source.raw_value.status != "PRESENT":
            continue
        binding = bind_comparison_scalar(source, raw, context)
        bindings.append(binding)
        if binding["binding_result"] != "BOUND":
            continue
        if source.p_value.status == "PRESENT" and source.p_value.value != binding["numeric_value"]:
            binding.update(binding_result="AMBIGUOUS", binding_confidence="AMBIGUOUS_BINDING",
                           blockers=["EXISTING_VALUE_AND_SCOPED_SOURCE_DISAGREE"])
            continue
        event = {**deepcopy(binding), "rule": binding["binding_rule"],
                 "source_quote": binding["selected_source_scalar"]}
        binding["changed"] = source.raw_value.value != binding["canonical_scalar"]
        if binding["changed"]:
            _repair(projected, result, "ComparisonResult", result.comparison_result_id,
                    "raw_value", binding["canonical_scalar"], event, context)
        if source.p_value.status == "PRESENT":
            # Preserve inequality in the binding and the local p_value.raw_value.
            # p_value_comparator is an unresolved clinical field: do not fill it.
            p_binding = {**deepcopy(binding), "field": "p_value",
                         "raw_field": source.p_value.model_dump(mode="json"),
                         "changed": source.p_value.raw_value != binding["selected_source_scalar"]}
            bindings.append(p_binding)
            if p_binding["changed"]:
                _repair(projected, result, "ComparisonResult", result.comparison_result_id,
                        "p_value", source.p_value.value, {**event, "field": "p_value"}, context,
                        raw_scalar=binding["selected_source_scalar"])


def normalize_result_surfaces(prediction, source_context):
    """Pure source-only API. Existing IDs/identity/timepoints and missing fields stay fixed."""
    raw_json = prediction.model_dump_json()
    context = deepcopy(source_context)
    projected = prediction.model_copy(deep=True)
    output = SurfaceProjection(projected)
    _normalize_statistics(prediction, projected, context, output.statistic_events, output.source_bindings)
    _normalize_comparisons(prediction, projected, context, output.source_bindings)
    for source, comparison in zip(prediction.comparisons, projected.comparisons, strict=True):
        if source.contrast.status != "SOURCE_CONFLICT":
            continue
        normalized = normalize_contrast_conflict(source.contrast)
        event = {"entity_id": source.comparison_id, "entity_type": "Comparison", "field": "contrast",
                 "raw_field": source.contrast.model_dump(mode="json"), "canonical_value": normalized,
                 "changed": normalized is not None,
                 "rule": "SURFACE_EQUIVALENT_CONTRAST_COLLAPSED" if normalized is not None else None,
                 "blocker": None if normalized is not None else "NON_SURFACE_CONFLICT_RETAINED",
                 "source_evidence_reference": sorted(set(source.contrast.evidence_ids + [
                     eid for c in source.contrast.conflict_candidates for eid in c.evidence_ids]))}
        if normalized is not None:
            _repair(projected, comparison, "Comparison", comparison.comparison_id,
                    "contrast", normalized, event, context)
        output.conflict_events.append(event)
    output.prediction = ArticleExtraction.model_validate_json(projected.model_dump_json())
    if prediction.model_dump_json() != raw_json:
        raise AssertionError("Source prediction mutated")
    return output
