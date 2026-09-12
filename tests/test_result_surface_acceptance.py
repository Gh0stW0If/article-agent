"""Frozen real-source replay. No online judge and no changes to evaluator semantics."""
from collections import Counter
import importlib.util
from pathlib import Path

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.hybrid.semantic_judge import CachedSemanticJudge, digest
from article_agent.result_surface import normalize_result_surfaces

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("surface_acceptance", ROOT / "scripts/pr5f2_result_surface_acceptance.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_real_baseline_and_two_offline_replays_byte_identical(tmp_path, monkeypatch):
    cache_keys = {j["input_sha256"] for j in runner.read(runner.BEFORE / "semantic_judgments.json")}
    original_judge = CachedSemanticJudge.judge
    calls = []
    def only_existing_cache(self, request):
        key = digest(self.canonical_input(request))
        assert key in cache_keys, "A changed semantic input would require an unauthorized new judgment"
        calls.append(key)
        return original_judge(self, request)
    monkeypatch.setattr(CachedSemanticJudge, "judge", only_existing_cache)
    with runner.api_disabled():
        initial = runner.protected_hashes()
        runner.verify_baseline(tmp_path / "baseline")
        context = runner.read(runner.SNAPSHOT / "SOURCE_SURFACE_CONTEXT.json")
        a, b = runner.run(tmp_path / "one", context), runner.run(tmp_path / "two", context)
    assert calls and a == b
    for name in runner.FILES:
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
        assert (tmp_path / "one" / name).read_bytes() == (runner.SNAPSHOT / name).read_bytes()
    assert initial == runner.protected_hashes()
    assert a["api_calls"] == 0


def test_real_frozen_identity_no_regression_and_scope_counts():
    summary = runner.read(runner.SNAPSHOT / "SUMMARY.json")
    for entity, matched in (("ArmResult", 12), ("ComparisonResult", 10), ("Outcome", 3)):
        assert summary["before"]["hybrid_entity_metrics"][entity] == summary["after"]["hybrid_entity_metrics"][entity]
        assert summary["after"]["hybrid_entity_metrics"][entity]["matched"] == matched
    assert summary["before"]["conflicts"] == summary["after"]["conflicts"]
    assert summary["hard_failures_before"]["identity_unresolved"] == summary["hard_failures_after"]["identity_unresolved"] == 105
    assert summary["missingness_hard_counts"] == {"NOT_REPORTED": 34, "NOT_APPLICABLE": 24}
    assert summary["missingness_handoff_counts"] == {"NOT_REPORTED": 138, "NOT_APPLICABLE": 33}
    assert summary["after"]["hybrid_hard_acceptable"]["numerator"] >= 64
    assert summary["coverage_promoted_false_conflicts"] == [
        "Comparison:2015-06-S1-C01:contrast", "Comparison:2015-06-S1-C03:contrast"]
    assert summary["after"]["hybrid_production_coverage"]["numerator"] == 72 + len(summary["coverage_promoted_false_conflicts"])
    assert sum(summary["value_denominator_after"].values()) == summary["after"]["hybrid_supported_value_accuracy"]["denominator"]
    assert summary["value_denominator_after"]["partial"] == 1
    assert summary["backlog_after"] == 0


def test_historical_raw_judgments_preserved_and_derived_fast_path():
    baseline = runner.predecessor()
    initial = runner.protected_hashes()
    raw = ArticleExtraction.model_validate(runner.read(baseline.PREDICTION))
    projected = ArticleExtraction.model_validate(runner.read(runner.SNAPSHOT / "CANONICAL_PREDICTION.json"))
    runner.scope_check(raw, projected)
    cache = runner.read(runner.BEFORE / "semantic_judgments.json")
    assert len(cache) == 76
    by_id = {j["judgment_id"]: j for j in cache}
    audit = runner.read(runner.SNAPSHOT / "BEFORE_AFTER_FIELD_EVALUATION.json")
    mean = [a for a in audit if a["field"] == "value_kind"]
    assert len(mean) == 12
    assert Counter(a["raw_judgment"]["result"]["grade"] for a in mean) == {"ERROR": 6, "WRONG": 6}
    for a in mean:
        assert a["raw_judgment"] == by_id[a["raw_judgment"]["judgment_id"]]
        assert a["before_field"]["value"] == "other" and a["after_field"]["value"] == "mean"
        assert a["after_evaluation"]["semantic_method"] == "DETERMINISTIC_EXACT"
        assert a["after_evaluation"]["semantic_judgment_id"] is None
        assert a["normalization_events"][0]["source_cue"]
    assert len(audit) == runner.read(runner.SNAPSHOT / "SUMMARY.json")["normalization_events"]
    assert all(a["normalization_events"] and a["before_field"] and a["after_field"] for a in audit)
    assert runner.protected_hashes() == initial


def test_real_projection_pure_without_file_or_api_access(monkeypatch):
    raw = ArticleExtraction.model_validate(runner.read(runner.predecessor().PREDICTION))
    context = runner.read(runner.SNAPSHOT / "SOURCE_SURFACE_CONTEXT.json")
    expected = runner.read(runner.SNAPSHOT / "CANONICAL_PREDICTION.json")
    def no_files(*args, **kwargs):
        raise AssertionError("Production projection must not open Gold or other files")
    monkeypatch.setattr(Path, "read_text", no_files)
    monkeypatch.setattr(Path, "read_bytes", no_files)
    monkeypatch.setattr("builtins.open", no_files)
    with runner.api_disabled():
        projected = normalize_result_surfaces(raw, context).prediction
    assert projected.model_dump(mode="json") == expected


def test_untouched_timepoint_partial_and_unmatched_results_remain_unscored():
    before = runner.read(runner.BEFORE / "HYBRID_REPORT.json")
    after = runner.read(runner.SNAPSHOT / "HYBRID_REPORT.json")
    newer = {f["target_id"]: f for f in after["field_results"]}
    for old in before["field_results"]:
        if old["hybrid_classification"] == "ENTITY_MISSING":
            assert newer[old["target_id"]] == old
        if old["field_id"].endswith(".timepoint"):
            assert newer[old["target_id"]] == old
    audit = runner.read(runner.SNAPSHOT / "BEFORE_AFTER_FIELD_EVALUATION.json")
    unmatched = [a for a in audit if a["target_id"].startswith("Prediction:")]
    assert len(unmatched) == 4
    assert all(a["after_evaluation"] == a["before_evaluation"] == {
        "hybrid_classification": "UNMATCHED_NOT_SCORED"} for a in unmatched)
