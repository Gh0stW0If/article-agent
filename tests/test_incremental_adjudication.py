"""Incremental FIELD judging is cache-only except for explicitly eligible new targets."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from article_agent.evaluation.hybrid import FakeSemanticJudge, LiveSemanticJudge, evaluate_article_hybrid, load_semantic_registry
from article_agent.evaluation.registry import load_registry
from article_agent.evaluation.hybrid.incremental_adjudication import (
    MODEL, ManifestOnlyJudge, merge_judgments, plan_targets, replay_frozen_pairs,
)
from article_agent.evaluation.hybrid.prompts import SYSTEM_PROMPT
from article_agent.evaluation.hybrid.semantic_judge import canonical_json, digest
from test_hybrid_semantic_evaluator import gold_fixture, prediction_fixture, present, grade, forbidden

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pr5e2_runner", ROOT / "scripts/pr5e2_adjudicate_new_fields.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def synthetic_inputs():
    gold = gold_fixture(lambda t: t["studies"][0].update(condition=present("Synthetic condition")))
    prediction = prediction_fixture(gold, lambda t: (
        t["studies"][0].update(condition=present("The synthetic condition")),
        t["arm_results"][0].update(timepoint=present("4th week")),
        t["arms"][0].update(randomized_n=present(99)),
    ))
    registry, overlay = load_registry(), load_semantic_registry()
    perfect = evaluate_article_hybrid(gold.truth, gold, registry, overlay, FakeSemanticJudge(forbidden))
    fake = FakeSemanticJudge(lambda request: None if request["field_id"] == "armResult.timepoint" else grade())
    fake.model = MODEL
    before = evaluate_article_hybrid(prediction, gold, registry, overlay, fake, precomputed_matches=perfect.entity_matches)
    prior = before.model_copy(deep=True)
    for f in prior.field_results:
        if f.entity_type == "ArmResult":
            f.prediction_entity_id = None  # simulated predecessor: result not yet linked
    old = [j.model_dump(mode="json") for j in before.semantic_judgments if j.status == "SUCCESS"]
    assert len(old) == 1
    return prediction, gold, registry, overlay, before, prior, old


class Client:
    model = MODEL
    api_mode = "responses"
    def __init__(self, responses=None):
        self.responses = iter(responses or [grade("EXACT")])
        self.calls = []
    def chat_json(self, messages, temperature):
        assert temperature == 0
        assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
        self.calls.append(json.loads(messages[1]["content"]))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def setup(tmp_path, responses=None):
    inputs = synthetic_inputs()
    plan = plan_targets(*inputs)
    assert plan["new_cache_miss_targets"] == plan["new_unique_api_requests"] == 1
    client = Client(responses)
    live = LiveSemanticJudge(client, tmp_path, retries=2)
    return inputs, plan, client, ManifestOnlyJudge(live, plan, inputs[-1])


def test_existing_success_cache_reuse_never_calls_api(tmp_path):
    inputs, plan, client, gated = setup(tmp_path)
    old = inputs[-1][0]
    request = {k: v for k, v in old["canonical_input"].items()
               if k not in {"prompt_version", "prompt_sha256", "model", "temperature"}}
    result = gated.judge(request)
    assert result.model_dump(mode="json") == old
    assert client.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("new_grade", ["EXACT", "EQUIVALENT", "PARTIAL", "ERROR", "WRONG"])
def test_one_new_request_success_stored_once_never_grade_based_retry(tmp_path, new_grade):
    inputs, plan, client, gated = setup(tmp_path, [grade(new_grade)])
    target = plan["targets"][0]
    result = gated.judge(target["request"])
    assert len(client.calls) == 1
    assert client.calls[0] == target["request"]
    assert result.result["grade"] == new_grade
    first = next(tmp_path.glob("*.json")).read_bytes()
    assert gated.judge(target["request"]) == result
    assert len(client.calls) == 1
    # New live object also loads the saved observation, even if grade is WRONG.
    fresh = ManifestOnlyJudge(LiveSemanticJudge(client, tmp_path), plan, inputs[-1])
    assert fresh.judge(target["request"]) == result
    assert len(client.calls) == 1
    assert next(tmp_path.glob("*.json")).read_bytes() == first


def test_technical_errors_remain_unavailable_not_wrong(tmp_path):
    _, plan, client, gated = setup(tmp_path, [TimeoutError("not persisted"),
        {**grade(), "grade": "mostly correct"}, RuntimeError("not persisted")])
    result = gated.judge(plan["targets"][0]["request"])
    assert len(client.calls) == result.attempts == 3
    assert result.status == "JUDGE_UNAVAILABLE" and result.result is None
    assert result.error_code == "SEMANTIC_JUDGE_ERROR"
    assert result.technical_errors == ["TimeoutError", "ValidationError", "RuntimeError"]
    assert "not persisted" not in next(tmp_path.glob("*.json")).read_text(encoding="utf-8")


def test_technical_failure_can_retry_to_success_but_success_never_retried(tmp_path):
    _, plan, client, gated = setup(tmp_path, [TimeoutError(), grade("PARTIAL")])
    result = gated.judge(plan["targets"][0]["request"])
    assert result.status == "SUCCESS" and result.result["grade"] == "PARTIAL"
    assert result.attempts == len(client.calls) == 2


@pytest.mark.parametrize("kind", ["identity", "deterministic", "missingness", "conflict"])
def test_excluded_fields_cannot_become_targets(kind):
    inputs = list(synthetic_inputs())
    before = inputs[4].model_copy(deep=True)
    target = next(f for f in before.field_results if f.field_id == "armResult.timepoint")
    if kind == "identity":
        for m in before.entity_matches:
            if m.entity_type == target.entity_type and m.gold_entity_id == target.gold_entity_id:
                m.match_status = "MISSING"
    elif kind == "deterministic":
        target.field_id = "armResult.raw_value"
    elif kind == "missingness":
        target.gold_status = "NOT_REPORTED"
    else:
        target.prediction_status = "SOURCE_CONFLICT"
    inputs[4] = before
    plan = plan_targets(*inputs)
    assert plan["targets"] == []


def test_api_gate_rejects_unplanned_field_and_input_rewrite(tmp_path):
    _, plan, client, gated = setup(tmp_path)
    request = deepcopy(plan["targets"][0]["request"])
    request["prediction"]["value"] = "rewrite to improve grade"
    with pytest.raises(ValueError, match="outside"):
        gated.judge(request)
    request = deepcopy(plan["targets"][0]["request"])
    request["judge_type"] = "ENTITY"
    with pytest.raises(ValueError, match="outside"):
        gated.judge(request)
    assert not client.calls


def test_frozen_model_and_api_required(tmp_path):
    inputs = synthetic_inputs()
    plan = plan_targets(*inputs)
    client = Client()
    client.model = "another-model"
    with pytest.raises(ValueError, match="gpt-5.6-sol"):
        ManifestOnlyJudge(LiveSemanticJudge(client, tmp_path), plan, inputs[-1])
    client.model, client.api_mode = MODEL, "chat_completions"
    with pytest.raises(ValueError, match="Responses"):
        LiveSemanticJudge(client, tmp_path)


def test_cache_merge_immutable_and_two_replays_identical(tmp_path):
    inputs, plan, client, gated = setup(tmp_path)
    old = deepcopy(inputs[-1])
    result = gated.judge(plan["targets"][0]["request"]).model_dump(mode="json")
    combined = merge_judgments(old, [result], plan)
    assert [digest(r) for r in combined[:len(old)]] == [digest(r) for r in old]
    prediction, gold, registry, overlay, before, _, _ = inputs
    one = replay_frozen_pairs(prediction, gold, registry, overlay, before, combined)
    two = replay_frozen_pairs(prediction, gold, registry, overlay, before, combined)
    assert one.model_dump_json() == two.model_dump_json()
    assert one.entity_matches == before.entity_matches
    assert one.metrics["judge_unavailable_field_count"] == 0
    assert len(client.calls) == 1
    assert inputs[-1] == old
    with pytest.raises(ValueError, match="eligible"):
        merge_judgments(old, [old[0]], plan)
    changed = deepcopy(result)
    changed["result"]["reason"] = "different"
    with pytest.raises(ValueError, match="different"):
        merge_judgments(old, [result, changed], plan)


def test_technical_failure_offline_replay_not_wrong(tmp_path):
    inputs, plan, _, gated = setup(tmp_path, [TimeoutError(), TimeoutError(), TimeoutError()])
    failure = gated.judge(plan["targets"][0]["request"]).model_dump(mode="json")
    combined = merge_judgments(inputs[-1], [failure], plan)
    report = replay_frozen_pairs(*inputs[:5], combined)
    f = next(f for f in report.field_results if f.field_id == "armResult.timepoint")
    assert f.hybrid_classification == "JUDGE_UNAVAILABLE"
    assert f.semantic_grade is None and f.value_acceptable is None


def test_real_dry_run_exact_manifest_and_frozen_field_payloads(tmp_path, monkeypatch):
    def forbidden_client(*args, **kwargs):
        raise AssertionError("Dry run cannot construct live judge/client")
    monkeypatch.setattr(runner, "adjudicate", forbidden_client)
    # Scoped runner output is intentionally local; use its deterministic planner directly.
    inputs = runner.load_inputs()
    plan = runner.get_plan(inputs)
    runner.write_plan(tmp_path, plan)
    assert plan["new_cache_miss_targets"] == plan["new_unique_api_requests"] == 34
    assert plan["old_successful_cache_count"] == 42
    assert plan["cached_successful_unique_keys_used"] == 7
    assert sum(t["in_hard_denominator"] for t in plan["targets"]) == 22
    assert all(t["request"]["judge_type"] == "FIELD" for t in plan["targets"])
    kinds = [t for t in plan["targets"] if t["field_id"] == "armResult.value_kind"]
    assert len(kinds) == 12
    assert all(t["gold"]["value"] == "mean" and t["prediction"]["value"] == "other" for t in kinds)
    assert all(t["gold"]["status"] == t["prediction"]["status"] == "PRESENT" for t in plan["targets"])
    ids = {t["field_id"] for t in plan["targets"]}
    assert not any(name.endswith(("raw_value", "p_value", "randomized_n", "contrast")) for name in ids)
    for target in plan["targets"]:
        assert digest(target["canonical_input"]) == target["cache_key"]
        original = next(j for j in inputs[4].semantic_judgments if j.input_sha256 == target["cache_key"])
        assert original.canonical_input == target["canonical_input"]
    assert (tmp_path / "planned_api_calls.json").exists()
