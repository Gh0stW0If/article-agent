from types import SimpleNamespace

from article_agent.domain.models import CanonicalField
from scripts.pr5r5_trace_localization import (
    classify_first_failure,
    content_match,
    trace_state,
)


def cf(value, status="PRESENT"):
    return CanonicalField(status=status, value=value)


def graph(outcome_name="Pain", outcome_id="O1", arm_label="A", arm_id="A1"):
    outcome = SimpleNamespace(outcome_id=outcome_id, name=cf(outcome_name))
    arm = SimpleNamespace(arm_id=arm_id, label=cf(arm_label))
    return SimpleNamespace(outcomes=[outcome], arms=[arm])


def result(outcome_id="O1", arm_id="A1", timepoint=None, p_value=0.01):
    return SimpleNamespace(
        outcome_id=outcome_id,
        arm_id=arm_id,
        timepoint=cf(timepoint) if timepoint else cf(None, "NOT_REPORTED"),
        timepoint_value=cf(None, "NOT_REPORTED"),
        timepoint_unit=cf(None, "NOT_REPORTED"),
        analysis_set=cf(None, "NOT_REPORTED"),
        value_kind=cf(None, "NOT_REPORTED"),
        value=cf(None, "NOT_REPORTED"),
        standard_deviation=cf(None, "NOT_REPORTED"),
        change_from_baseline=cf(None, "NOT_REPORTED"),
        dispersion_lower=cf(None, "NOT_REPORTED"),
        dispersion_upper=cf(None, "NOT_REPORTED"),
        n=cf(None, "NOT_REPORTED"),
        event_count=cf(None, "NOT_REPORTED"),
        denominator=cf(None, "NOT_REPORTED"),
        effect_measure=cf(None, "NOT_REPORTED"),
        estimate=cf(None, "NOT_REPORTED"),
        confidence_interval_lower=cf(None, "NOT_REPORTED"),
        confidence_interval_upper=cf(None, "NOT_REPORTED"),
        p_value=cf(p_value),
        raw_value=cf(str(p_value)),
    )


def test_content_match_ignores_identity_but_requires_reported_value():
    gold_graph = graph("Pain", "O1", "A", "A1")
    pred_graph = graph("Different label", "O9", "A", "A9")
    assert content_match(gold_graph, result(), pred_graph, result("O9", "A9")) == (True, 1.0)


def test_skill_timepoint_error_is_localized_at_skill_extraction():
    candidate = {
        "failure_localization": {"trace_completeness": "COMPLETE"},
        "raw_extraction": {
            "raw_outcome": "Pain",
            "raw_arm": "A",
            "raw_timepoint": "3 months",
            "raw_comparison": None,
        },
        "final": {"final_parent_ids": {"outcome": "O1", "arm": "A1", "timepoint": "3 months"}},
        "events": [],
    }
    gold_graph = graph("Pain", "O1", "A", "A1")
    gold = result("O1", "A1", "1 month")
    pred_graph = graph("Pain", "O1", "A", "A1")
    out = classify_first_failure(candidate, gold_graph, gold, pred_graph)
    assert out["first_failure_stage"] == "SKILL_EXTRACTION"
    assert out["root_cause"] == "TIMEPOINT_WRONG_AT_EXTRACTION"


def test_trace_state_reads_merge_event_without_guessing():
    candidate = {
        "events": [{
            "event_id": "e1",
            "event_type": "RESULT_MERGED",
            "stage": "MERGER",
            "after": {"survivor": "R1"},
        }]
    }
    assert trace_state(candidate, "MERGER") == {"survivor": "R1"}
