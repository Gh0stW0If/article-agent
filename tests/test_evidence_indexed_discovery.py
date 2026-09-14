from article_agent.evidence_indexed_discovery import (
    UnitAnnotation,
    build_slot_plan_from_annotations,
    build_source_unit_index,
    bounded_annotation_prompt,
    validate_unit_annotations,
)
from article_agent.trial_topology_agent import TrialTopology, topology_to_canonical


def fixtures():
    rows = [{
        "table_id": "T2",
        "row_id": "row_03",
        "outcome_name": "Residual urine volume",
        "timepoint": "1st month",
        "source_evidence": "Residual urine volume at 1st month: Group 1 10; Group 2 12; Group 3 11",
        "arm": [
            {"arm_label": "Group 1", "value": 10},
            {"arm_label": "Group 2", "value": 12},
            {"arm_label": "Group 3", "value": 11},
        ],
        "source_cells": [
            {"column_id": "group_1", "raw_value": "10"},
            {"column_id": "group_2", "raw_value": "12"},
            {"column_id": "group_3", "raw_value": "11"},
        ],
        "column_map": [{"header_path": ["Group 1", "1st month"]}],
    }]
    topology = TrialTopology(number_of_arms=3, arms=[
        {"source_label": f"Group {index}", "name": name, "evidence": [{
            "source_id": "article", "quote": f"Group {index}: {name}", "arm_text": f"Group {index}",
        }]}
        for index, name in enumerate(("CIC", "EA + CIC", "Sham acupuncture + CIC"), 1)
    ])
    return rows, topology, topology_to_canonical("A", topology)


def test_source_unit_ids_are_coordinate_stable_under_record_reordering():
    rows, _, _ = fixtures()
    other = [dict(rows[0], row_id="row_04", source_evidence="Other")]
    first = build_source_unit_index("A", rows + other)
    second = build_source_unit_index("A", list(reversed(rows + other)))
    assert {unit.source_unit_id for unit in first.units} == {unit.source_unit_id for unit in second.units}
    assert {unit.unit_type for unit in first.units} == {"table_row", "table_header", "source_cell"}


def test_bounded_annotation_must_reference_existing_source_unit_and_verbatim_spans():
    rows, _, _ = fixtures()
    index = build_source_unit_index("A", rows)
    row_unit = next(unit for unit in index.units if unit.unit_type == "table_row")
    accepted = validate_unit_annotations(index, [UnitAnnotation(
        source_unit_id=row_unit.source_unit_id,
        outcome_span="Residual urine volume",
        timepoint_span="1st month",
        arm_refs=["Group 1", "Group 2", "Group 3"],
        evidence_span="Residual urine volume at 1st month",
    )])
    assert len(accepted.accepted) == 1
    rejected = validate_unit_annotations(index, [{
        "source_unit_id": "su-unknown",
        "outcome_span": "Residual urine volume",
    }])
    assert len(rejected.violations) == 1


def test_new_outcome_or_result_cardinality_is_not_accepted_from_annotation():
    rows, topology, graph = fixtures()
    index = build_source_unit_index("A", rows)
    row_unit = next(unit for unit in index.units if unit.unit_type == "table_row")
    annotation = UnitAnnotation(
        source_unit_id=row_unit.source_unit_id,
        outcome_span="Residual urine volume",
        timepoint_span="1st month",
        arm_refs=["Group 1", "Group 2", "Group 3"],
        comparison_refs=[["Group 2", "Group 1"]],
        evidence_span="Residual urine volume at 1st month",
    )
    plan = build_slot_plan_from_annotations("A", topology, graph, index, [annotation])
    assert len(plan.discovered_outcomes) == 1
    assert len([slot for slot in plan.slots if slot.slot_type == "ArmResult"]) == 3
    assert len([slot for slot in plan.slots if slot.slot_type == "ComparisonResult"]) == 1
    assert all(slot.source_unit_ids == [row_unit.source_unit_id] for slot in plan.slots)


def test_ambiguous_annotation_abstains_without_creating_slots():
    rows, topology, graph = fixtures()
    index = build_source_unit_index("A", rows)
    row_unit = next(unit for unit in index.units if unit.unit_type == "table_row")
    annotation = UnitAnnotation(
        source_unit_id=row_unit.source_unit_id,
        outcome_span="Residual urine volume",
        timepoint_span="1st month",
        status="AMBIGUOUS",
    )
    plan = build_slot_plan_from_annotations("A", topology, graph, index, [annotation])
    assert plan.slots == []


def test_bounded_prompt_does_not_offer_entity_or_slot_creation():
    rows, _, _ = fixtures()
    unit = next(unit for unit in build_source_unit_index("A", rows).units if unit.unit_type == "table_row")
    prompt = bounded_annotation_prompt(unit)
    text = prompt[1]["content"]
    assert "Do not return outcome_id" in text
    assert "source_unit_id" in text
