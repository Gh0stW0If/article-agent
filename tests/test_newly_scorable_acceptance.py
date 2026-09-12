"""Real frozen-cache acceptance, no online calls; never assert preferred grades."""
import json
from pathlib import Path
import socket

from test_incremental_adjudication import runner
from article_agent.evaluation.hybrid.semantic_judge import digest

SNAPSHOT = runner.SNAPSHOT


def test_frozen_new_judgments_two_offline_replays(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Frozen adjudication replay attempted an API call")
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    initial = runner.protected_hashes()
    runner.check_baseline(tmp_path / "baseline")
    inputs = runner.load_inputs()
    plan = runner.get_plan(inputs)
    new = runner.read(SNAPSHOT / "NEWLY_ADJUDICATED_JUDGMENTS.json")
    first, second = tmp_path / "first", tmp_path / "second"
    a = runner.finalize(first, inputs, plan, new, initial)
    b = runner.finalize(second, inputs, plan, new, initial)
    assert a == b
    for name in runner.FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes() == (SNAPSHOT / name).read_bytes()
    assert a["frozen_mapping_unchanged"]
    assert a["old_judgments_unchanged"]
    assert a["evaluation_backlog_before"] == len(plan["targets"])
    assert a["offline_replay_api_calls"] == 0
    for metric in ("hybrid_entity_metrics", "hybrid_production_coverage", "hybrid_status_accuracy"):
        assert a["before"][metric] == a["after"][metric]
    assert runner.protected_hashes() == initial


def test_old_cache_payloads_preserved_and_handoff_semantic_only():
    old = runner.read(runner.OLD)
    combined = runner.read(SNAPSHOT / "semantic_judgments.json")
    new = runner.read(SNAPSHOT / "NEWLY_ADJUDICATED_JUDGMENTS.json")
    by_key = {r["input_sha256"]: r for r in combined}
    assert len(by_key) == len(combined) == len(old) + len(new)
    assert all(digest(r) == digest(by_key[r["input_sha256"]]) for r in old)
    targets = runner.read(SNAPSHOT / "NEWLY_SCORABLE_TARGETS.json")["targets"]
    assert set(r["input_sha256"] for r in new) <= {t["cache_key"] for t in targets}
    assert all(r["judge_type"] == "FIELD" for r in new)
    handoff = runner.read(SNAPSHOT / "PR5G_EXTRACTION_CANDIDATES.json")
    new_by_id = {r["judgment_id"]: r for r in new}
    assert {c["judgment_id"] for c in handoff} == {
        r["judgment_id"] for r in new if r["status"] == "SUCCESS"
        and r["result"]["grade"] in {"PARTIAL", "ERROR", "WRONG"}}
    assert all(c["grade"] in {"PARTIAL", "ERROR", "WRONG"}
               and new_by_id[c["judgment_id"]]["result"]["grade"] == c["grade"] for c in handoff)
    summary = runner.read(SNAPSHOT / "SUMMARY.json")
    assert sum(summary["supported_value_accuracy_breakdown"].values()) == summary["after"]["hybrid_supported_value_accuracy"]["denominator"]
    failures = [r for r in new if r["status"] == "JUDGE_UNAVAILABLE"]
    assert all(r["result"] is None and r["error_code"] == "SEMANTIC_JUDGE_ERROR" for r in failures)


def test_real_cli_dry_run_cannot_create_live_client(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "safe_output", lambda _: tmp_path / "dry")
    def forbidden(*args, **kwargs):
        raise AssertionError("Dry-run attempted online adjudication")
    monkeypatch.setattr(runner, "adjudicate", forbidden)
    assert runner.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "New API judgments required: 34" in output
    assert "Existing cached judgments retained: 42" in output
    assert (tmp_path / "dry/planned_api_calls.json").exists()
