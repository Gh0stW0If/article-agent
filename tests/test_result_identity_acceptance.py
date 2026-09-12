"""Frozen-article regression: replay identity only, without extraction or online judging."""
import importlib.util
import json
from pathlib import Path
import socket

from article_agent.domain.models import ArticleExtraction
from article_agent.result_identity.models import SourceIdentityContext

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pr5f1_acceptance", ROOT / "scripts/pr5f1_result_identity_acceptance.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
SNAPSHOT = ROOT / "benchmarks/2015-06/result_identity_v1"


def test_frozen_baseline_and_two_complete_offline_replays(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline replay attempted a network call")
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    protected = runner.frozen_hashes()
    runner.baseline_check(tmp_path / "baseline")
    context = SourceIdentityContext.model_validate_json(
        (SNAPSHOT / "SOURCE_IDENTITY_CONTEXT.json").read_text(encoding="utf-8"))
    first, second = tmp_path / "first", tmp_path / "second"
    a = runner.run(first, context, baseline_reproduced=True)
    b = runner.run(second, context, baseline_reproduced=True)
    assert a == b
    for name in runner.FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes() == (SNAPSHOT / name).read_bytes()
    for entity in ("ArmResult", "ComparisonResult"):
        assert a["after"]["hybrid_entity_metrics"][entity]["matched"] > 0
    assert a["identity_unresolved_hard"]["after"] < a["identity_unresolved_hard"]["before"]
    assert a["conflicts"]["conflict_detected"] == a["conflicts"]["candidate_set_exact"] == 2
    assert a["previous_successful_identity_pairs_preserved"]
    assert not a["numerical_values_used_for_identity"]
    assert not a["production_rerun"]
    assert a["api_calls"] == 0
    assert runner.frozen_hashes() == protected


def test_raw_other_retained_unjudged_fields_not_invented_and_audit_complete():
    raw = ArticleExtraction.model_validate_json((runner.RAW / "prediction.json").read_text(encoding="utf-8"))
    normalization = json.loads((SNAPSHOT / "RESULT_IDENTITY_NORMALIZATION.json").read_text(encoding="utf-8"))
    report = json.loads((SNAPSHOT / "HYBRID_REPORT.json").read_text(encoding="utf-8"))
    rows = {p["entity_id"]: p for p in normalization["results"] if p["side"] == "Prediction"}
    rescued = [r for r in raw.arm_results if r.value_kind.value == "other"
               and rows[r.arm_result_id]["canonical_statistic_kind"] == "mean"]
    assert rescued
    for result in rescued:
        assert rows[result.arm_result_id]["raw_statistic_kind"]["value"] == "other"
        assert rows[result.arm_result_id]["raw_statistic_kind"]["status"] == result.value_kind.status
        field = next(f for f in report["field_results"]
                     if f["prediction_entity_id"] == result.arm_result_id and f["field_id"] == "armResult.value_kind")
        assert field["prediction_value"] == "other"  # scoring never receives the projection value
    unavailable = [j for j in report["semantic_judgments"] if j["status"] == "JUDGE_UNAVAILABLE"]
    assert unavailable
    assert all(j["attempts"] == 0 and j["result"] is None
               and j["technical_errors"] == ["FROZEN_FIELD_JUDGMENT_ABSENT_API_DISABLED"] for j in unavailable)
    audit = json.loads((SNAPSHOT / "RESULT_IDENTITY_BEFORE_AFTER.json").read_text(encoding="utf-8"))
    for side in ("Gold", "Prediction"):
        selected = [a["selected_pair"] for a in audit if a["side"] == side and a["selected_pair"]]
        assert len({p["gold_id"] for p in selected}) == len(selected)
        assert len({p["prediction_id"] for p in selected}) == len(selected)
    assert all(a["reason_codes"] for a in audit)
    unresolved = json.loads((SNAPSHOT / "RESULT_IDENTITY_UNRESOLVED.json").read_text(encoding="utf-8"))
    assert all(not set(a["reason_codes"]) & {"ENTITY_MISSING", "IDENTITY_UNRESOLVED", "NO_CANDIDATE"} for a in unresolved)
