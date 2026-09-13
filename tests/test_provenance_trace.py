import json
from pathlib import Path

from article_agent.provenance.trace import (
    TraceBuilder,
    TraceSession,
    build_prediction_trace,
    locate_first_failure,
    stable_candidate_id,
    stable_event_id,
)


def _complete(candidate_id="cand-test"):
    return {
        "candidate_id": candidate_id,
        "constructed_result_id": "R1",
        "stages": {stage: {"availability": "AVAILABLE"} for stage in (
            "RETRIEVAL", "SKILL_EXTRACTION", "RESULT_CONSTRUCTION",
            "PARENT_BINDING", "NORMALIZATION", "MERGER", "FINAL_PROJECTION",
        )},
        "events": [],
    }


def test_merger_parent_replacement_is_localized():
    trace = _complete()
    trace["events"] = [{
        "event_id": "e1", "stage": "MERGER", "event_type": "PARENT_REPLACED",
        "reason_code": "PARENT_CHANGED_DURING_MERGE",
    }]
    result = locate_first_failure(trace)
    assert result["first_failure_stage"] == "MERGER"
    assert result["first_failure_event"] == "e1"


def test_skill_extraction_parent_error_is_localized():
    trace = _complete()
    trace["events"] = [{
        "event_id": "e1", "stage": "SKILL_EXTRACTION", "event_type": "PARENT_REMOVED",
        "reason_code": "PARENT_INCOMPLETE_AT_EXTRACTION",
    }]
    assert locate_first_failure(trace)["first_failure_stage"] == "SKILL_EXTRACTION"


def test_result_construction_drops_comparison():
    trace = _complete()
    trace["events"] = [{
        "event_id": "e1", "stage": "RESULT_CONSTRUCTION", "event_type": "PARENT_REMOVED",
        "reason_code": "PARENT_LOST_DURING_RESULT_CONSTRUCTION",
    }]
    assert locate_first_failure(trace)["first_failure_stage"] == "RESULT_CONSTRUCTION"


def test_parent_binding_and_normalization_are_observable():
    for stage in ("PARENT_BINDING", "NORMALIZATION", "FINAL_PROJECTION"):
        trace = _complete()
        trace["events"] = [{
            "event_id": "e1", "stage": stage, "event_type": "PARENT_REPLACED",
            "reason_code": "OTHER",
        }]
        assert locate_first_failure(trace)["first_failure_stage"] == stage


def test_missing_intermediate_artifact_stays_unknown():
    trace = _complete()
    trace["stages"]["MERGER"] = {"availability": "NOT_AVAILABLE"}
    result = locate_first_failure(trace)
    assert result["first_failure_stage"] == "UNKNOWN"
    assert result["root_cause"] == "ARTIFACT_NOT_AVAILABLE"


def test_candidate_and_event_ids_are_stable():
    kwargs = {
        "article_id": "a1", "skill_name": "outcome-result",
        "context_hash": "ctx", "source_ref": {"table_id": "t1", "row_id": "r1"},
        "local_index": 0,
    }
    assert stable_candidate_id(**kwargs) == stable_candidate_id(**kwargs)
    assert stable_event_id("c1", "MERGER", "PARENT_REPLACED", "A", "B", "rule") == stable_event_id(
        "c1", "MERGER", "PARENT_REPLACED", "A", "B", "rule"
    )


def test_trace_builder_does_not_accept_or_need_gold():
    builder = TraceBuilder({
        "candidate_id": "c1",
        "constructed_result_id": "R1",
        "stages": {stage: {"availability": "AVAILABLE"} for stage in (
            "RETRIEVAL", "SKILL_EXTRACTION", "RESULT_CONSTRUCTION",
            "PARENT_BINDING", "NORMALIZATION", "MERGER", "FINAL_PROJECTION",
        )},
    })
    event = builder.event(stage="FINAL_PROJECTION", event_type="FINAL_RESULT_EMITTED",
                          after={"result_id": "R1"}, rule_id="test")
    assert event["event_id"]
    assert "gold" not in json.dumps(builder.finish(), ensure_ascii=False).casefold()


def test_existing_prediction_replay_is_deterministic():
    path = Path("benchmarks/2015-06/missingness_v1/CANONICAL_PREDICTION.json")
    if not path.exists():
        return
    from article_agent.domain.models import ArticleExtraction
    prediction = ArticleExtraction.model_validate_json(path.read_text(encoding="utf-8"))
    first = build_prediction_trace(prediction)
    second = build_prediction_trace(prediction)
    assert first == second


def test_trace_session_writer_failure_does_not_escape():
    def fail(_):
        raise OSError("trace sink unavailable")
    session = TraceSession("a1", writer=fail)
    candidate_id = session.create_candidate(
        skill_name="s", skill_version="1", context_hash="ctx",
        source_ref={"row_id": "r1"}, local_index=0,
        raw_extraction={"raw_value": 1}, entity_type="ArmResult",
    )
    assert candidate_id
    assert session.incomplete is True
    artifact = session.artifact()
    assert artifact["trace_incomplete"] is True


def test_trace_session_complete_without_retrieval_requirement():
    session = TraceSession("a1")
    candidate_id = session.create_candidate(
        skill_name="s", skill_version="1", context_hash="ctx",
        source_ref={"row_id": "r1"}, local_index=0,
        raw_extraction={"raw_value": 1}, entity_type="ArmResult",
    )
    session.event(candidate_id, stage="RESULT_CONSTRUCTION",
                  event_type="RESULT_CREATED", rule_id="construct")
    session.event(candidate_id, stage="PARENT_BINDING",
                  event_type="ARM_BOUND", after="A1", rule_id="bind")
    session.event(candidate_id, stage="FINAL_PROJECTION",
                  event_type="FINAL_RESULT_EMITTED", after="R1", rule_id="final")
    session.set_result(candidate_id, result_id="R1", parent={"arm": "A1"})
    item = session.artifact()["candidates"][0]
    assert item["failure_localization"]["trace_completeness"] == "COMPLETE"
