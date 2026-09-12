"""Real frozen replay plus strict missingness-only scope and leakage boundaries."""
from collections import Counter
import importlib.util
from pathlib import Path

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.hybrid import CachedSemanticJudge
from article_agent.evaluation.hybrid.semantic_judge import digest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("missingness_acceptance",
    ROOT / "scripts/pr5g1_missingness_acceptance.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_baseline_then_two_real_offline_replays_byte_identical(tmp_path, monkeypatch):
    previous = runner.predecessor()
    cache = runner.read(previous.BEFORE / "semantic_judgments.json")
    hashes = {j["input_sha256"] for j in cache}
    original = CachedSemanticJudge.judge
    calls = []
    def frozen_only(self, request):
        key = digest(self.canonical_input(request))
        assert key in hashes, "New semantic request is forbidden"
        calls.append(key)
        return original(self, request)
    monkeypatch.setattr(CachedSemanticJudge, "judge", frozen_only)
    protected = runner.protected_hashes()
    with previous.api_disabled():
        runner.verify_baseline(tmp_path / "baseline")
        one, two = runner.run(tmp_path / "one"), runner.run(tmp_path / "two")
    assert one == two and calls and runner.protected_hashes() == protected
    for name in runner.FILES:
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
        assert (tmp_path / "one" / name).read_bytes() == (runner.SNAPSHOT / name).read_bytes()
    assert one["nr_decisions"] == 0 and one["na_decisions"] == 24
    assert one["missingness_before"] == {"NOT_REPORTED": 34, "NOT_APPLICABLE": 24}
    assert one["missingness_after"] == {"NOT_REPORTED": 34, "NOT_APPLICABLE": 0}
    for name, count in (("hybrid_hard_acceptable", 97), ("hybrid_status_accuracy", 123)):
        assert one["after"][name]["numerator"] == count
    for name in ("hybrid_production_coverage", "hybrid_supported_value_accuracy",
                 "hybrid_entity_metrics", "conflicts"):
        assert one["before"][name] == one["after"][name]
    assert one["hard_failures_before"]["identity_unresolved"] == one["hard_failures_after"]["identity_unresolved"] == 105
    assert one["api_calls"] == 0


def test_scope_frozen_values_raw_fields_reciprocal_evidence_and_handoff():
    raw = ArticleExtraction.model_validate(runner.read(runner.BASE / "CANONICAL_PREDICTION.json"))
    projected = ArticleExtraction.model_validate(runner.read(runner.SNAPSHOT / "CANONICAL_PREDICTION.json"))
    decisions = runner.read(runner.SNAPSHOT / "MISSINGNESS_DECISIONS.json")
    runner.scope_check(raw, projected, decisions)
    changes = [d for d in decisions if d["changed"]]
    assert len(changes) == 24
    assert all(d["entity_type"] == "ArmResult" and d["after_status"] == "NOT_APPLICABLE"
               and d["applicability_evidence"]["evidence_ids"] for d in changes)
    handoff = runner.read(runner.SNAPSHOT / "PR5G2_EXTRACTION_INPUT.json")
    assert len(handoff) == 34
    assert all(f["gold_status"] == "PRESENT" and f["prediction_entity_id"]
        and f["prediction_status"] == "UNRESOLVED" and f["prediction_value"] is None
        and f["hybrid_classification"] == "NOT_EXTRACTED" for f in handoff)
    missing = runner.read(runner.SNAPSHOT / "MISSINGNESS_UNRESOLVED.json")
    assert len(missing) == 34 and all(f["gold_status"] == "NOT_REPORTED" for f in missing)
    assert Counter(f["field_id"] for f in missing) == {
        "armResult.n": 12, "comparisonResult.estimate": 10,
        "arm.analyzed_n": 3, "arm.received_n": 3, "arm.dropout_n": 3, "outcome.role": 3}
    assert all(f["decision"]["reason_code"] == "INSUFFICIENT_COVERAGE_KEEP_UNRESOLVED" for f in missing)
    proofs = runner.read(runner.SNAPSHOT / "COVERAGE_PROOFS.json")
    assert proofs and not any(p["coverage_sufficient"] for p in proofs)
    assert {f["decision"]["coverage_proof_id"] for f in missing} <= {p["proof_id"] for p in proofs}


def test_missingness_production_precedes_gold_read_and_receives_no_evaluation_targets(tmp_path, monkeypatch):
    production = runner.resolve_missingness
    observed = []
    def source_only(*args, **kwargs):
        assert len(args) == 1 and not kwargs
        assert isinstance(args[0], ArticleExtraction)
        observed.append("projection")
        return production(*args, **kwargs)
    monkeypatch.setattr(runner, "resolve_missingness", source_only)
    previous = runner.predecessor()
    # The runner's protected hashes inspect bytes only; actual load/validation of
    # Gold for evaluation cannot run before the production stage.
    from article_agent.evaluation.gold_contract import GoldStandardV2
    original = GoldStandardV2.model_validate
    def after_projection(*args, **kwargs):
        assert observed, "Gold was loaded before source-side projection"
        return original(*args, **kwargs)
    monkeypatch.setattr(GoldStandardV2, "model_validate", after_projection)
    with previous.api_disabled():
        runner.run(tmp_path / "run")
    assert observed == ["projection"]
