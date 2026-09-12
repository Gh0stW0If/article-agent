"""All unit tests are API-free. Synthetic comparisons never tune the real baseline."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket

import pytest
from pydantic import ValidationError

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.engine import evaluate_article
from article_agent.evaluation.gold_contract import GoldStandardV2
from article_agent.evaluation.registry import load_registry
from article_agent.evaluation.hybrid import (
    CachedSemanticJudge, FakeSemanticJudge, HybridEvaluationReportV1, LiveSemanticJudge,
    SemanticJudgment, evaluate_article_hybrid, load_semantic_registry,
)
from article_agent.evaluation.hybrid.entity_matcher import result_identity
from article_agent.evaluation.hybrid.models import SemanticEntityJudgment
from article_agent.evaluation.hybrid.registry import WHITELIST, SemanticRegistryV1
from article_agent.evaluation.hybrid.semantic_judge import CacheMissError, field_request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hybrid_synthetic", ROOT / "scripts/pr5b_synthetic_acceptance.py")
synthetic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(synthetic)
present = synthetic.present


def grade(value="EQUIVALENT"):
    return {"grade": value, "reason": "Synthetic rubric decision.", "matched_information": [],
            "missing_information": [], "incorrect_information": []}


def identity(value="SAME"):
    return {"decision": value, "same_entity": {"SAME": True, "DIFFERENT": False, "AMBIGUOUS": None}[value],
            "reason": "Synthetic identity decision.", "identity_information": [], "differences": []}


def forbidden(request):
    raise AssertionError("Judge must not be called")


def gold_fixture(edit=None):
    data = synthetic.synthetic_gold().model_dump(mode="json")
    if edit:
        edit(data["truth"])
    synthetic.add_evidence(data["truth"])
    return GoldStandardV2.model_validate(data)


def prediction_fixture(gold, edit=None):
    data = gold.truth.model_dump(mode="json")
    if edit:
        edit(data)
    synthetic.add_evidence(data)
    return ArticleExtraction.model_validate(data)


def evaluate(gold, prediction, responder=forbidden):
    judge = FakeSemanticJudge(responder)
    report = evaluate_article_hybrid(prediction, gold, load_registry(), load_semantic_registry(), judge)
    assert HybridEvaluationReportV1.model_validate_json(report.model_dump_json()) == report
    return report, judge


def field(report, field_id, entity_id=None):
    return next(f for f in report.field_results if f.field_id == field_id
                and (entity_id is None or f.gold_entity_id == entity_id))


@pytest.mark.parametrize("value,score", [
    ("EXACT", 1), ("EQUIVALENT", 1), ("PARTIAL", .5), ("ERROR", .25), ("WRONG", 0),
])
def test_all_grades_frozen_score_mapping(value, score):
    parsed = SemanticJudgment.model_validate(grade(value))
    assert parsed.model_dump(mode="json")["score"] == score
    g = gold_fixture(lambda t: t["studies"][0].update(condition=present("Gold condition")))
    p = prediction_fixture(g, lambda t: t["studies"][0].update(condition=present("Pred condition")))
    report, judge = evaluate(g, p, lambda _: grade(value))
    f = field(report, "study.condition")
    assert f.semantic_score == score and f.hybrid_classification == "SEMANTIC_" + value
    assert f.value_acceptable == (value in {"EXACT", "EQUIVALENT"})
    assert report.metrics["semantic_weighted_score"]["rate"] == score
    assert report.metrics["semantic_acceptable_accuracy"]["rate"] == int(value in {"EXACT", "EQUIVALENT"})
    assert len(judge.calls) == 1


@pytest.mark.parametrize("extra", [{"score": 1}, {"grade": "GOOD"}, {"unexpected": "value"}])
def test_wire_response_rejects_score_invalid_grade_and_extra(extra):
    with pytest.raises(ValidationError):
        SemanticJudgment.model_validate({**grade(), **extra})


def test_entity_contract_is_distinct_and_strict():
    assert SemanticEntityJudgment.model_validate(identity()).same_entity is True
    with pytest.raises(ValidationError):
        SemanticEntityJudgment.model_validate({**identity(), "same_entity": False})
    with pytest.raises(ValidationError):
        SemanticEntityJudgment.model_validate({**identity(), "score": 1})


@pytest.mark.parametrize("gs,ps,expected", [
    ("PRESENT", "UNRESOLVED", "NOT_EXTRACTED"),
    ("PRESENT", "NOT_REPORTED", "FALSE_NR"),
    ("PRESENT", "INSUFFICIENT_CONTEXT", "NOT_EXTRACTED"),
    ("PRESENT", "NOT_APPLICABLE", "STATUS_WRONG"),
    ("NOT_APPLICABLE", "PRESENT", "FALSE_PRESENT"),
    ("PRESENT", "REVIEW_REQUIRED", "STATUS_WRONG"),
    ("REVIEW_REQUIRED", "PRESENT", None),
])
def test_status_mismatches_never_call_llm(gs, ps, expected):
    g = gold_fixture(lambda t: t["studies"][0].update(
        condition=present("urinary retention") if gs == "PRESENT" else {"status": gs}))
    p = prediction_fixture(g, lambda t: t["studies"][0].update(
        condition=present("plausible answer") if ps == "PRESENT" else {"status": ps}))
    report, judge = evaluate(g, p)
    assert field(report, "study.condition").hybrid_classification == expected
    assert not judge.calls


def test_not_reported_sessions_cannot_be_repaired_by_derivation():
    raw = gold_fixture().model_dump(mode="json")
    iid = raw["truth"]["interventions"][0]["intervention_id"]
    raw["truth"]["interventions"][0]["total_sessions"] = {"status": "NOT_REPORTED"}
    raw["missingness_assessments"] = [{
        "entity_type": "Intervention", "entity_id": iid, "field_id": "total_sessions",
        "status": "NOT_REPORTED", "coverage_complete": True, "rationale": "Synthetic complete review"}]
    g = GoldStandardV2.model_validate(raw)
    p = prediction_fixture(g, lambda t: t["interventions"][0].update(total_sessions=present(90)))
    report, judge = evaluate(g, p)
    assert field(report, "intervention.total_sessions").hybrid_classification == "FALSE_PRESENT"
    assert not judge.calls


def test_numeric_and_conflict_never_call_llm():
    g = gold_fixture()
    p = prediction_fixture(g, lambda t: (
        t["arms"][0].update(randomized_n=present(99)),
        t["arms"][1].update(randomized_n=synthetic.conflict((34, 38)))))
    report, judge = evaluate(g, p)
    assert field(report, "arm.randomized_n").hybrid_classification == "VALUE_WRONG"
    assert report.metrics["conflicts"]["candidate_set_exact"] == 1
    assert not judge.calls


def test_semantic_conflict_stays_deterministic_without_llm():
    g = gold_fixture(lambda t: t["studies"][0].update(
        condition={"status": "SOURCE_CONFLICT", "conflict_candidates": [{"value": "A"}, {"value": "B"}]}))
    p = prediction_fixture(g)
    report, judge = evaluate(g, p)
    assert field(report, "study.condition").hybrid_classification == "SOURCE_CONFLICT_DETECTED"
    assert report.metrics["conflicts"]["candidate_set_exact"] == 2
    assert not judge.calls


def test_semantic_deterministic_fast_path_and_nonsemantic_text():
    g = gold_fixture(lambda t: t["studies"][0].update(condition=present("Urinary retention")))
    p = prediction_fixture(g, lambda t: (
        t["studies"][0].update(condition=present("urinary retention")),
        t["article"].update(journal=present("different journal"))))
    report, judge = evaluate(g, p)
    assert field(report, "study.condition").semantic_method == "DETERMINISTIC_EXACT"
    assert field(report, "study.condition").semantic_grade == "EXACT"
    assert report.metrics["semantic_acceptable_accuracy"]["denominator"] == 0
    assert not judge.calls


def test_only_exact_whitelist_and_text_domain_fields():
    overlay, base = load_semantic_registry(), load_registry()
    assert len(overlay.fields) == 30
    assert set(overlay.by_id()) == WHITELIST
    specs = {f.field_id: f for f in base.fields}
    assert all(specs[f.field_id].value_type in {"string", "list[string]"} for f in overlay.fields)
    for invalid in ("article.title", "arm.randomized_n", "outcome.unit"):
        data = overlay.model_dump(mode="json")
        data["fields"][0]["field_id"] = invalid
        with pytest.raises(ValidationError):
            SemanticRegistryV1.model_validate(data)


def test_intervention_abbreviation_structural_arm_context():
    g = gold_fixture(lambda t: t["interventions"][0].update(name=present("Electroacupuncture")))
    p = prediction_fixture(g, lambda t: t["interventions"][0].update(name=present("electroacupuncture (EA)")))
    report, judge = evaluate(g, p, lambda r: grade("EXACT"))
    item = next(m for m in report.entity_matches if m.entity_type == "Intervention")
    assert item.match_status == "MATCHED" and item.match_method == "STRUCTURAL_CONTEXT"
    assert all(r["judge_type"] == "FIELD" for r in judge.calls)


def test_outcome_missing_instrument_does_not_block_identity():
    g = gold_fixture(lambda t: t["outcomes"][0].update(
        name=present("CIC frequency"), instrument={"status": "NOT_APPLICABLE"}))
    p = prediction_fixture(g, lambda t: t["outcomes"][0].update(instrument={"status": "UNRESOLVED"}))
    report, judge = evaluate(g, p, lambda r: identity())
    assert report.metrics["hybrid_entity_metrics"]["Outcome"]["matched"] == 2
    oid = g.truth.outcomes[0].outcome_id
    assert field(report, "outcome.instrument", oid).hybrid_classification == "NOT_EXTRACTED"
    assert all(r["judge_type"] == "ENTITY" for r in judge.calls)


def test_comparison_same_ordered_arms_ignores_missing_relation_for_identity():
    g = gold_fixture()
    p = prediction_fixture(g, lambda t: t["comparisons"][0].update(relation={"status": "UNRESOLVED"}))
    report, judge = evaluate(g, p)
    m = next(m for m in report.entity_matches if m.entity_type == "Comparison")
    assert m.match_status == "MATCHED" and m.match_method == "STRUCTURAL_CONTEXT"
    assert field(report, "comparison.relation").hybrid_classification == "NOT_EXTRACTED"
    assert not judge.calls


def test_reversed_comparison_arms_not_semantically_repaired():
    g = gold_fixture()
    p = prediction_fixture(g, lambda t: t["comparisons"][0]["arm_ids"].reverse())
    report, judge = evaluate(g, p)
    assert report.metrics["hybrid_entity_metrics"]["Comparison"]["matched"] == 0
    assert not judge.calls


@pytest.mark.parametrize("decision,expected", [("SAME", "SPLIT"), ("AMBIGUOUS", "AMBIGUOUS")])
def test_outcome_split_no_best_candidate_selection(decision, expected):
    g = gold_fixture()
    def edit(t):
        t["outcomes"][0]["instrument"] = {"status": "UNRESOLVED"}
        other = deepcopy(t["outcomes"][0])
        other["outcome_id"] += "-copy"
        t["outcomes"].append(other)
        t["studies"][0]["outcome_ids"].append(other["outcome_id"])
    p = prediction_fixture(g, edit)
    report, _ = evaluate(g, p, lambda r: identity(decision))
    first = next(m for m in report.entity_matches
                 if m.entity_type == "Outcome" and m.gold_entity_id == g.truth.outcomes[0].outcome_id)
    assert first.match_status == expected and first.prediction_entity_id is None


def test_merged_outcomes_are_not_resolved():
    def edit_g(t):
        t["outcomes"][1].update(name=present("Related pain"), instrument={"status": "NOT_APPLICABLE"})
    g = gold_fixture(edit_g)
    def edit_p(t):
        removed = t["outcomes"].pop()["outcome_id"]
        t["studies"][0]["outcome_ids"].remove(removed)
        t["outcomes"][0]["instrument"] = {"status": "UNRESOLVED"}
    report, _ = evaluate(g, prediction_fixture(g, edit_p), lambda r: identity())
    assert any(m.match_status == "MERGED" for m in report.entity_matches)
    assert report.metrics["hybrid_entity_metrics"]["Outcome"]["matched"] == 0


def test_uncertain_competitor_blocks_otherwise_same_pair():
    g = gold_fixture()
    def edit(t):
        t["outcomes"][0]["instrument"] = {"status": "UNRESOLVED"}
        other = deepcopy(t["outcomes"][0])
        other["outcome_id"] += "-copy"
        other["name"] = present("Uncertain identity")
        t["outcomes"].append(other)
        t["studies"][0]["outcome_ids"].append(other["outcome_id"])
    def respond(r):
        return identity("AMBIGUOUS" if r["prediction"]["name"]["value"] == "Uncertain identity" else "SAME")
    report, _ = evaluate(g, prediction_fixture(g, edit), respond)
    assert any(m.match_status == "AMBIGUOUS" and m.entity_type == "Outcome" for m in report.entity_matches)


@pytest.mark.parametrize("field_name,gold_text,pred_text,judgment,expected", [
    ("timepoint", "1 month", "1st month", "EQUIVALENT", True),
    ("value_kind", "mean", "mean value", "EQUIVALENT", True),
    ("value_kind", "mean", "median", "WRONG", False),
    ("analysis_set", "ITT", "intention-to-treat", "EQUIVALENT", True),
    ("analysis_set", "ITT", "PP", "WRONG", False),
])
def test_result_semantic_identity_fields(field_name, gold_text, pred_text, judgment, expected):
    g = gold_fixture(lambda t: t["arm_results"][0].update({field_name: present(gold_text)}))
    p = prediction_fixture(g, lambda t: t["arm_results"][0].update({field_name: present(pred_text)}))
    report, judge = evaluate(g, p, lambda r: grade(judgment))
    assert (report.metrics["hybrid_entity_metrics"]["ArmResult"]["matched"] == 1) is expected
    for request in judge.calls:
        if request["judge_type"] == "RESULT_IDENTITY_FIELD":
            for side in ("gold", "prediction"):
                assert request[side]["raw_value"] is None and request[side]["evidence"] == []


def test_numeric_timepoint_has_priority_and_no_numeric_llm():
    g = gold_fixture(lambda t: t["arm_results"][0].update(
        timepoint_value=present(1), timepoint_unit=present("month")))
    p = prediction_fixture(g, lambda t: t["arm_results"][0].update(timepoint_value=present(2)))
    report, judge = evaluate(g, p)
    # Existing PR5B matches are intentionally frozen even if a stronger key would differ.
    assert not judge.calls
    assert field(report, "armResult.timepoint_value").hybrid_classification == "VALUE_WRONG"
    specs = {f.field_id: f for f in load_registry().fields}
    decision, ids = result_identity("ArmResult", g.truth.arm_results[0], p.arm_results[0],
                                   specs, load_semantic_registry().by_id(), FakeSemanticJudge(forbidden))
    assert decision is False and ids == []


def test_missing_analysis_set_unique_and_ambiguous_results():
    g = gold_fixture()
    p = prediction_fixture(g, lambda t: t["arm_results"][0].update(analysis_set={"status": "UNRESOLVED"}))
    report, judge = evaluate(g, p)
    assert report.metrics["hybrid_entity_metrics"]["ArmResult"]["matched"] == 1
    assert field(report, "armResult.analysis_set").hybrid_classification == "NOT_EXTRACTED"
    def edit(t):
        second = deepcopy(t["arm_results"][0])
        second["arm_result_id"] += "-PP"
        second["analysis_set"] = present("PP")
        t["arm_results"].append(second)
    g2 = gold_fixture(edit)
    def edit_p(t):
        t["arm_results"].pop()
        t["arm_results"][0]["analysis_set"] = {"status": "UNRESOLVED"}
    ambiguous, _ = evaluate(g2, prediction_fixture(g2, edit_p))
    assert ambiguous.metrics["hybrid_entity_metrics"]["ArmResult"]["matched"] == 0
    assert ambiguous.metrics["hybrid_entity_metrics"]["ArmResult"]["ambiguous_gold"] == 2


def test_result_numeric_values_do_not_affect_identity_requests_or_matching():
    g = gold_fixture()
    def edit(t):
        t["comparison_results"][0].update(timepoint=present("four weeks"), estimate=present(999),
            confidence_interval_lower=present(-999), confidence_interval_upper=present(999), p_value=present(.9))
    p = prediction_fixture(g, edit)
    report, judge = evaluate(g, p, lambda r: grade())
    identity_requests = [r for r in judge.calls if r["judge_type"] == "RESULT_IDENTITY_FIELD"]
    assert identity_requests
    for request in identity_requests:
        assert "999" not in json.dumps(request) and "0.9" not in json.dumps(request)
        assert request["field_id"] in {"comparisonResult.timepoint", "comparisonResult.analysis_set", "comparisonResult.effect_measure"}
    assert field(report, "comparisonResult.estimate").hybrid_classification == "VALUE_WRONG"
    assert report.metrics["hybrid_entity_metrics"]["ComparisonResult"]["matched"] == 1


def test_derived_mismatch_cannot_be_identity_rescued():
    g = gold_fixture()
    p = prediction_fixture(g, lambda t: t["comparison_results"][0].update(
        derived=True, derivation="Synthetic computation", timepoint=present("four weeks")))
    report, judge = evaluate(g, p)
    assert report.metrics["hybrid_entity_metrics"]["ComparisonResult"]["matched"] == 0
    assert not judge.calls


def test_failures_not_wrong_and_excluded_from_semantic_denominator():
    g = gold_fixture(lambda t: t["studies"][0].update(condition=present("Gold condition")))
    p = prediction_fixture(g, lambda t: t["studies"][0].update(condition=present("Prediction condition")))
    report, _ = evaluate(g, p, lambda r: None)
    result = field(report, "study.condition")
    assert result.hybrid_classification == "JUDGE_UNAVAILABLE"
    assert result.value_acceptable is None and result.semantic_grade is None
    assert report.metrics["judge_failure_count"] == 1
    assert report.metrics["semantic_acceptable_accuracy"]["denominator"] == 0
    assert not any(report.metrics["semantic_grade_distribution"].values())


def test_entity_failure_is_ambiguous_not_an_accepted_edge():
    g = gold_fixture()
    p = prediction_fixture(g, lambda t: t["outcomes"][0].update(instrument={"status": "UNRESOLVED"}))
    report, _ = evaluate(g, p, lambda r: None)
    assert any(m.match_status == "AMBIGUOUS" for m in report.entity_matches)
    assert report.metrics["judge_failure_count"] == 1


def sample_request():
    spec = load_semantic_registry().by_id()["study.condition"]
    return field_request(spec, {"value": "gold", "raw_value": None, "evidence": []},
                         {"value": "prediction", "raw_value": None, "evidence": []})


class FakeClient:
    model = "gpt-5.6-sol"
    api_mode = "responses"

    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def chat_json(self, messages, temperature):
        self.calls.append((messages, temperature))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def test_live_cache_calls_once_and_replay_identical(tmp_path, monkeypatch):
    client = FakeClient([grade("PARTIAL")])
    live = LiveSemanticJudge(client, tmp_path)
    a, b = live.judge(sample_request()), live.judge(sample_request())
    assert a == b and len(client.calls) == 1 and client.calls[0][1] == 0
    monkeypatch.setattr(socket, "socket", forbidden)
    cached = CachedSemanticJudge(tmp_path)
    assert a.model_dump_json() == cached.judge(sample_request()).model_dump_json()
    assert "score" not in json.loads(client.calls[0][0][1]["content"])


def test_technical_retry_strict_parser_and_no_default_equivalent(tmp_path):
    client = FakeClient([{**grade(), "grade": "GOOD"}, grade("WRONG")])
    live = LiveSemanticJudge(client, tmp_path)
    item = live.judge(sample_request())
    assert len(client.calls) == 2 and item.attempts == 2
    assert item.result["grade"] == "WRONG"
    assert item.technical_errors == ["ValidationError"]
    assert live.judge(sample_request()) == item and len(client.calls) == 2


def test_exhausted_technical_retries_are_frozen_and_sanitized(tmp_path):
    client = FakeClient([RuntimeError("private credential not publishable")] * 3)
    item = LiveSemanticJudge(client, tmp_path).judge(sample_request())
    assert item.status == "JUDGE_UNAVAILABLE" and item.result is None and item.attempts == 3
    assert "private credential" not in item.model_dump_json()
    assert CachedSemanticJudge(tmp_path).judge(sample_request()) == item


def test_cache_miss_tamper_and_model_separation(tmp_path):
    with pytest.raises(CacheMissError):
        CachedSemanticJudge(tmp_path).judge(sample_request())
    item = LiveSemanticJudge(FakeClient([grade()]), tmp_path).judge(sample_request())
    with pytest.raises(CacheMissError):
        CachedSemanticJudge(tmp_path, model="different-model").judge(sample_request())
    payload = item.model_dump(mode="json")
    payload["result"]["score"] = .1
    with pytest.raises(ValueError, match="score"):
        CachedSemanticJudge(artifacts=[payload]).judge(sample_request())
    payload = item.model_dump(mode="json")
    payload["gold_representation"] = {"value": "tampered"}
    with pytest.raises(ValueError, match="provenance"):
        CachedSemanticJudge(artifacts=[payload]).judge(sample_request())


def test_frozen_report_replay_and_input_immutability(monkeypatch):
    g = gold_fixture(lambda t: t["studies"][0].update(condition=present("Gold condition")))
    p = prediction_fixture(g, lambda t: t["studies"][0].update(condition=present("Pred condition")))
    registry, overlay = load_registry(), load_semantic_registry()
    before = [obj.model_dump_json() for obj in (p, g, registry, overlay)]
    judge = FakeSemanticJudge(lambda r: grade("PARTIAL"))
    first = evaluate_article_hybrid(p, g, registry, overlay, judge)
    monkeypatch.setattr(socket, "socket", forbidden)
    replay = evaluate_article_hybrid(p, g, registry, overlay, CachedSemanticJudge(
        artifacts=[a.model_dump(mode="json") for a in first.semantic_judgments], model=judge.model))
    assert replay.model_dump_json(indent=2) == first.model_dump_json(indent=2)
    assert before == [obj.model_dump_json() for obj in (p, g, registry, overlay)]


def test_baseline_pr5b_byte_replay_and_locked_matches():
    import runpy
    module = runpy.run_path(str(ROOT / "scripts/pr5e1_hybrid_evaluate.py"))
    p = ArticleExtraction.model_validate_json((module["BASELINE"] / "prediction.json").read_text(encoding="utf-8"))
    g = GoldStandardV2.model_validate_json(module["GOLD"].read_text(encoding="utf-8"))
    ref = module["replay_pr5b"](p, g, load_registry())
    report, _ = evaluate(g, p, lambda r: identity("AMBIGUOUS") if r["judge_type"] == "ENTITY" else grade("PARTIAL"))
    locked = {(m.entity_type, m.gold_entity_id, m.prediction_entity_id) for m in ref.entity_matches if m.match_status == "MATCHED"}
    new = {(m.entity_type, m.gold_entity_id, m.prediction_entity_id) for m in report.entity_matches if m.match_status == "MATCHED"}
    assert locked <= new
    assert report.metrics["conflicts"]["conflict_detected"] == report.metrics["conflicts"]["candidate_set_exact"] == 2
    assert report.deterministic_reference["hard_exact"] == ref.metrics["hard_exact"]


def test_module_does_not_import_hybrid_from_production_or_change_v3():
    # The new evaluator must remain opt-in; no extraction-stage imports.
    for name in ("pipeline.py", "outcome_canonicalizer.py", "outcome_source_normalizer.py",
                 "trial_topology_agent.py", "arm_details_agent.py"):
        path = ROOT / "src/article_agent" / name
        if path.exists():
            assert "evaluation.hybrid" not in path.read_text(encoding="utf-8")


def test_published_snapshot_offline_replay_and_all_artifact_bytes(tmp_path, monkeypatch):
    import runpy
    import article_agent.models
    module = runpy.run_path(str(ROOT / "scripts/pr5e1_hybrid_evaluate.py"))
    directory = ROOT / "benchmarks/2015-06/hybrid_eval_v1"
    judgments = json.loads((directory / "semantic_judgments.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(article_agent.models, "OpenAICompatibleClient", forbidden)
    report = module["run"](tmp_path, CachedSemanticJudge(artifacts=judgments))
    for name in module["OUTPUT_NAMES"]:
        assert (tmp_path / name).read_bytes() == (directory / name).read_bytes(), name
    assert all(a.status == "SUCCESS" and a.attempts == 1 for a in report.semantic_judgments)
    assert len(report.semantic_judgments) == 42
    assert report.metrics["semantic_grade_distribution"] == {
        "EXACT": 2, "EQUIVALENT": 1, "PARTIAL": 4, "ERROR": 0, "WRONG": 0}
    # Identity rejections must be visible but not mixed into ordinary field accuracy.
    assert report.metrics["result_identity_grade_distribution"] == {
        "EXACT": 3, "EQUIVALENT": 0, "PARTIAL": 2, "ERROR": 4, "WRONG": 4}
    disagreements = (directory / "SEMANTIC_DISAGREEMENTS.md").read_text(encoding="utf-8")
    assert "Identity rejections and uncertainty" in disagreements
    assert "armResult.value_kind" in disagreements


def test_prompt_is_versioned_and_frozen():
    from article_agent.evaluation.hybrid.prompts import (
        SEMANTIC_PROMPT_VERSION, SEMANTIC_PROMPT_SHA256, SYSTEM_PROMPT,
    )
    assert SEMANTIC_PROMPT_VERSION == "SEMANTIC_JUDGE_PROMPT/1.0.0"
    assert SEMANTIC_PROMPT_SHA256 == "1c01740f6be269269da667c5a4c01841a77008255a3df72d0fe13aef70e55d95"
    assert "Do not infer missing prediction content from evidence" in SYSTEM_PROMPT
    assert "Do not return score" in SYSTEM_PROMPT
