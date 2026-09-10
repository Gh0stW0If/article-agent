from copy import deepcopy

from article_agent.outcome_source_normalizer import normalize_outcome_sources
from article_agent.trial_topology_agent import TrialTopology


def topology():
    ev=lambda name: [{"source_id":"article","quote":name,"arm_text":name}]
    return TrialTopology(number_of_arms=3, arms=[
        {"name": "CIC", "source_label": "Group 1", "aliases": ["A01"],"evidence":ev("CIC")},
        {"name": "EA + CIC", "source_label": "Group 2", "aliases": ["A02"],"evidence":ev("EA + CIC")},
        {"name": "Sham acupuncture + CIC", "source_label": "Group 3", "aliases": ["A03"],"evidence":ev("Sham acupuncture + CIC")},
    ])


def test_statistic_and_timepoint_split_only_when_explicit():
    rows, _ = normalize_outcome_sources("2015-06", topology(), [{"outcome_name": "Residual urine volume mean at 1 month"}])
    assert rows[0]["outcome_name"] == "Residual urine volume"
    assert rows[0]["value_kind"] == "mean"
    assert rows[0]["timepoint"] == "at 1 month"
    rows, _ = normalize_outcome_sources("2015-06", topology(), [{"outcome_name": "Residual urine volume"}])
    assert rows[0]["outcome_name"] == "Residual urine volume"
    assert "value_kind" not in rows[0]


def test_independent_instrument_not_repeated():
    rows, _ = normalize_outcome_sources("2015-06", topology(), [{"outcome_name": "Pain", "measurement_instrument": "VAS"}])
    assert rows[0]["outcome_name"] == "Pain"


def test_ambiguous_name_is_unchanged():
    original = {"outcome_name": "Outcome mean change", "value_kind": "NR", "source_evidence": "x"}
    rows, _ = normalize_outcome_sources("2015-06", topology(), [original])
    assert rows[0]["outcome_name"] == original["outcome_name"]


def test_exact_arm_binding_and_unknown_arm():
    rows, report = normalize_outcome_sources("2015-06", topology(), [{"outcome_name": "Pain", "arm": [
        {"arm_label": "Group 1", "value": 1}, {"arm_label": "Group X", "value": 2}]}])
    assert rows[0]["arm"][0]["source_arm_id"] == "2015-06-S1-A01"
    assert rows[0]["arm"][1]["source_arm_id"] is None
    assert any(w["type"] == "ARM_BINDING" for w in report["warnings"])


def test_explicit_comparison_mapping_and_ambiguous_p():
    rows, report = normalize_outcome_sources("2015-06", topology(), [{"outcome_name": "Pain",
        "comparison": {"arm_labels": ["Group 2", "Group 1"], "contrast": "Group 2 vs Group 1"},
        "p_value_cells": [{"header_path": ["P1"], "value": .01}]}])
    assert rows[0]["comparison"]["source_arm_ids"] == ["2015-06-S1-A02", "2015-06-S1-A01"]
    assert rows[0]["p_value_comparisons"] is None
    assert any(w["type"] == "COMPARISON_SCOPE" for w in report["warnings"])


def test_original_traceable_and_no_mutation():
    original = [{"outcome_name": "Pain mean at 1 month", "arm": [{"arm_label": "Group 1"}]}]
    before = deepcopy(original)
    rows, _ = normalize_outcome_sources("2015-06", topology(), original)
    assert original == before
    assert rows[0]["_pr41_original"] == before[0]

def test_normalization_counters_are_reported():
    rows, report = normalize_outcome_sources("2015-06", topology(), [{
        "outcome_name": "Pain mean at 1 month",
        "arm": [{"arm_label": "Group 1"}],
        "comparison": {"arm_labels": ["Group 1", "Group 2"], "contrast": "Group 1 vs Group 2"},
    }])
    assert report["counters"]["statistic/value_kind"] == 1
    assert report["counters"]["timepoint"] == 1
    assert report["counters"]["arm_bindings"] == 1
    assert report["counters"]["comparator_mappings"] == 1


def test_complete_offline_composition(monkeypatch):
    import socket
    from article_agent.trial_topology_agent import topology_to_canonical
    from article_agent.outcome_canonicalizer import canonicalize_outcomes
    from article_agent.domain import ArticleExtraction
    def no_network(*args, **kwargs):
        raise AssertionError("offline only")
    monkeypatch.setattr(socket, "socket", no_network)
    t = topology()
    graph = topology_to_canonical("2015-06", t)
    original_graph = graph.model_dump()
    raw = [{"outcome_name": "Pain mean at 1 month",
            "source_evidence": "Pain mean at 1 month: Group 1 10, Group 2 12",
            "arm": [{"arm_label": "Group 1", "value": 10}],
            "comparison": {"contrast": "Group 1 vs Group 2"},
            "outcome_p_value": 0.05}]
    original = deepcopy(raw)
    normalized, report = normalize_outcome_sources("2015-06", t, raw)
    result = canonicalize_outcomes("2015-06", t, graph, normalized)
    assert raw == original and graph.model_dump() == original_graph
    assert normalized[0]["_pr41_original"] == original[0]
    assert result.arms == graph.arms
    assert len(result.outcomes) == len(result.arm_results) == 1
    assert result.arm_results[0].value.value == 10
    assert result.arm_results[0].value_kind.value == "mean"
    assert result.comparison_results[0].p_value.value == 0.05
    assert ArticleExtraction.model_validate_json(result.model_dump_json()) == result
    assert report["counters"]["arm_bindings"] == 1
