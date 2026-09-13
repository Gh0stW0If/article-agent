from copy import deepcopy

import pytest

from article_agent.domain.models import ArticleExtraction
from article_agent.provenance import TraceSession
from article_agent.slot_result_extraction import (
    SlotFill,
    discover_result_slots,
    fill_slots_with_client,
    materialize_canonical_results,
    materialize_slot_fills,
    run_result_extraction,
    validate_slot_fills,
)
from article_agent.trial_topology_agent import TrialTopology, topology_to_canonical


def topology_and_graph(arms=3):
    names = ["CIC", "EA + CIC", "Sham acupuncture + CIC"][:arms]
    topology = TrialTopology(
        number_of_arms=arms,
        arms=[
            {
                "name": name,
                "source_label": f"Group {index}",
                "evidence": [
                    {
                        "source_id": "article",
                        "quote": f"Group {index}: {name}",
                        "arm_text": f"Group {index}",
                    }
                ],
            }
            for index, name in enumerate(names, 1)
        ],
    )
    return topology, topology_to_canonical("A", topology)


def record(**changes):
    row = {
        "outcome_name": "Residual urine volume",
        "measurement_instrument": "Ultrasound",
        "timepoint": "1 month",
        "table_id": "T2",
        "row_id": "r1",
        "source_evidence": "Residual urine volume at 1 month",
        "arm": [
            {"arm_label": "Group 1", "value": 10},
            {"arm_label": "Group 2", "value": 12},
        ],
    }
    row.update(changes)
    return row


def plan(rows, arms=3, trace=None):
    topology, graph = topology_and_graph(arms)
    return discover_result_slots("A", topology, graph, rows, trace=trace)


def test_source_order_does_not_change_slot_ids():
    rows = [record(), record(outcome_name="Pain", row_id="r2", arm=[{"arm_label": "Group 1", "value": 3}])]
    first = plan(rows)
    second = plan(list(reversed(rows)))
    assert {slot.slot_id for slot in first.slots} == {slot.slot_id for slot in second.slots}


def test_only_source_supported_timepoint_is_planned():
    result = plan([record()])
    assert {slot.timepoint_id for slot in result.slots} == {"1 month"}
    assert not any(slot.timepoint_id == "3 month" for slot in result.slots)


def test_three_arms_do_not_form_cartesian_product():
    rows = [record(arm=[{"arm_label": "Group 2", "value": 12}])]
    result = plan(rows, arms=3)
    assert len(result.slots) == 1
    assert result.slots[0].arm_id == "A-S1-A02"


def test_only_explicit_comparison_is_planned():
    rows = [record(
        arm=[{"arm_label": f"Group {i}", "value": i} for i in range(1, 4)],
        comparison={"contrast": "Group 2 vs Group 1", "relation": "between-group"},
    )]
    result = plan(rows, arms=3)
    assert [slot.comparison_id for slot in result.slots if slot.slot_type == "ComparisonResult"]
    assert all(slot.comparison_id for slot in result.slots if slot.slot_type == "ComparisonResult")
    assert len({slot.comparison_id for slot in result.slots if slot.slot_type == "ComparisonResult"}) == 1


def test_unknown_arm_never_creates_new_arm_or_slot():
    result = plan([record(arm=[{"arm_label": "new treatment", "value": 7}])], arms=3)
    assert not result.slots
    assert any("unknown/ambiguous arm" in warning for warning in result.warnings)


def test_ambiguous_timepoint_abstains():
    result = plan([record(timepoint="1 or 3 months", timepoint_candidates=["1 month", "3 months"])])
    assert not result.slots
    assert any("ambiguous timepoint" in warning for warning in result.warnings)


def test_slot_fill_cannot_create_new_slot_or_identity():
    result = plan([record()])
    valid = result.slots[0]
    checked = validate_slot_fills(result, [
        SlotFill(slot_id="slot-new", values={"value": 9}),
        SlotFill(slot_id=valid.slot_id, identity={"timepoint_id": "3 month"}, values={"value": 9}),
    ])
    assert len(checked.accepted) == 0
    assert len(checked.violations) == 2


def test_client_filler_is_one_slot_and_rejects_expansion():
    result = plan([record()])

    class Client:
        def __init__(self):
            self.calls = []

        def chat_json(self, messages, temperature=0.0):
            self.calls.append(messages)
            slot_id = result.slots[len(self.calls) - 1].slot_id
            return {"slot_id": slot_id, "values": {"value": 10}}

    client = Client()
    checked = fill_slots_with_client(
        result, {slot.slot_id: "source" for slot in result.slots}, client
    )
    assert len(client.calls) == len(result.slots)
    assert len(checked.accepted) == len(result.slots)


def test_materialization_is_deterministic_and_slot_bound():
    result = plan([record()])
    fills = [SlotFill(slot_id=slot.slot_id, values={"value": 1}) for slot in result.slots]
    first = materialize_slot_fills(result, fills)
    second = materialize_slot_fills(result, list(reversed(fills)))
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    assert all(item.outcome_id == "A-S1-O01" for item in first)


def test_materialize_canonical_results_preserves_evidence():
    result = plan([record()])
    fill = SlotFill(slot_id=result.slots[0].slot_id, values={"value": 10, "raw_value": "10"})
    arms, comparisons, evidence = materialize_canonical_results(result, [fill])
    assert len(arms) == 1 and not comparisons
    assert arms[0].value.value == 10
    assert evidence[0].targets[0].field_id == "value"


def test_trace_records_structure_and_fill_events():
    trace = TraceSession("A")
    result = plan([record()], trace=trace)
    fill = SlotFill(slot_id=result.slots[0].slot_id, values={"value": 10})
    checked = validate_slot_fills(result, [fill])
    trace.global_event(
        stage="RESULT_CONSTRUCTION", event_type="SLOT_FILL_STARTED",
        after={"slot_count": len(result.slots)}, rule_id="test",
    )
    trace.global_event(
        stage="RESULT_CONSTRUCTION", event_type="SLOT_FILLED",
        after=fill.model_dump(), rule_id="test",
    )
    event_types = {event["event_type"] for event in trace.artifact()["events"]}
    assert {"STRUCTURE_DISCOVERY_STARTED", "OUTCOME_DISCOVERED", "TIMEPOINT_DISCOVERED",
            "SLOT_CREATED", "SLOT_FILL_STARTED", "SLOT_FILLED"} <= event_types
    assert checked.accepted


def test_feature_flag_preserves_legacy_default_and_returns_slot_projection():
    sentinel = object()
    assert run_result_extraction([], {}, {}, article_id="A", legacy_path=lambda _: sentinel) is sentinel
    topology, graph = topology_and_graph(2)
    result = run_result_extraction(
        [record()], topology, graph, article_id="A", legacy_path=lambda _: sentinel,
        use_slot_based=True,
    )
    assert result["slot_plan"].gold_used is False
    assert result["slot_plan"].registry_used is False


def test_canonical_graph_roundtrip_for_materialized_entities():
    topology, graph = topology_and_graph(2)
    result = discover_result_slots("A", topology, graph, [record()])
    fill = SlotFill(slot_id=result.slots[0].slot_id, values={"value": 10})
    arm_results, comparison_results, evidence = materialize_canonical_results(result, [fill])
    payload = graph.model_dump()
    payload["outcomes"] = [{
        "outcome_id": "A-S1-O01", "study_id": "A-S1",
        "name": {"status": "PRESENT", "value": "Residual urine volume",
                 "raw_value": "Residual urine volume", "evidence_ids": [],
                 "conflict_candidates": []},
        "instrument": {"status": "UNRESOLVED", "value": None, "raw_value": None,
                       "evidence_ids": [], "conflict_candidates": []},
        "role": {"status": "UNRESOLVED", "value": None, "raw_value": None,
                 "evidence_ids": [], "conflict_candidates": []},
        "direction": {"status": "UNRESOLVED", "value": None, "raw_value": None,
                      "evidence_ids": [], "conflict_candidates": []},
        "unit": {"status": "UNRESOLVED", "value": None, "raw_value": None,
                 "evidence_ids": [], "conflict_candidates": []},
        "scale_min": {"status": "UNRESOLVED", "value": None, "raw_value": None,
                      "evidence_ids": [], "conflict_candidates": []},
        "scale_max": {"status": "UNRESOLVED", "value": None, "raw_value": None,
                      "evidence_ids": [], "conflict_candidates": []},
    }]
    payload["studies"][0]["outcome_ids"] = ["A-S1-O01"]
    payload["arm_results"] = [item.model_dump() for item in arm_results]
    payload["comparison_results"] = [item.model_dump() for item in comparison_results]
    payload["evidence"] = payload["evidence"] + [item.model_dump() for item in evidence]
    # The result evidence target points to the result and its field.  Add the
    # required reciprocal field linkage after the standalone materialisation.
    evidence_id = next(
        item["evidence_id"]
        for item in payload["evidence"]
        if item["targets"][0]["entity_type"] == "ArmResult"
    )
    payload["arm_results"][0]["value"]["evidence_ids"] = [evidence_id]
    assert ArticleExtraction.model_validate(payload)
