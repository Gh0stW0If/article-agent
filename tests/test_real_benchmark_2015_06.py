"""Pre-benchmark safety tests; these do not claim a successful real baseline."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_assembly_has_no_reference_or_evaluator_inputs():
    path = ROOT / "scripts/pr5d1_build_prediction.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "evaluation" not in (node.module or "")
            assert not {"GoldStandardV2", "evaluate_article"}.intersection(a.name for a in node.names)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not any("gold" in arg.arg.lower() for arg in node.args.args + node.args.kwonlyargs)


def test_responses_retry_requires_explicit_matching_transport_hash(tmp_path):
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    source = tmp_path / "src/article_agent/models.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic transport\n", encoding="utf-8")
    validate = module["validate_source_changes"]
    assert validate(tmp_path, []) == {}
    changed = ["src/article_agent/models.py", "tests/test_models.py"]
    with pytest.raises(ValueError):
        validate(tmp_path, changed)
    with pytest.raises(ValueError):
        validate(tmp_path, changed, "wrong-digest")
    accepted = validate(tmp_path, changed, module["digest"](source))
    assert accepted["sha256"] == module["digest"](source)
    with pytest.raises(ValueError):
        validate(tmp_path, changed + ["src/article_agent/outcome_canonicalizer.py"], accepted["sha256"])


def test_transport_retry_never_claims_unmodified_production():
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    run = {"benchmark_id": "example", "article_id": "example", "status": "BENCHMARK_NOT_RUN",
           "production_git_sha": "base", "authorized_transport_patch": {"sha256": "patch"}}
    result = module["technical_failure_summary"](run, {"model_configuration": {}, "forbidden_read_attempts": []}, "parser", [])
    assert result["production_modified"] is True
    assert result["authorized_transport_patch"] == run["authorized_transport_patch"]


def test_failed_production_cannot_create_prediction(tmp_path):
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_build_prediction.py"))
    (tmp_path / "PRODUCTION_RUN.json").write_text(json.dumps({"status": "BENCHMARK_NOT_RUN", "exit_code": 1}), encoding="utf-8")
    (tmp_path / "PRODUCTION_ISOLATION.json").write_text(json.dumps({"forbidden_read_attempts": []}), encoding="utf-8")
    with pytest.raises(AssertionError):
        module["build_prediction"](tmp_path / "nonexistent-production", tmp_path)
    assert not (tmp_path / "prediction.json").exists()


def test_technical_failure_is_unscored():
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    run = {"benchmark_id": "example", "article_id": "example", "status": "BENCHMARK_NOT_RUN", "production_git_sha": "sha"}
    isolation = {"forbidden_read_attempts": [], "model_configuration": {"trial_topology": "configured-model"}}
    result = module["technical_failure_summary"](run, isolation, "parser", ["API HTTP 401"] * 3)
    assert result["status"] == "BENCHMARK_NOT_RUN"
    assert result["prediction_sha256"] is None and result["metrics"] is None
    assert result["entity_metrics"] is None and not result["evaluator_executed"]
    assert result["requests"]["topology_attempts"] == 3 and result["requests"]["topology_retries"] == 2
    assert result["technical_failure"]["http_401_invalid_token"] == 3


def test_failure_report_cannot_relabel_success():
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    with pytest.raises(ValueError):
        module["technical_failure_summary"]({"status": "PRODUCTION_COMPLETE"}, {}, "parser", [])


def test_404_retry_is_reported_without_assuming_authentication_success():
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    run = {"benchmark_id": "example", "article_id": "example", "status": "BENCHMARK_NOT_RUN",
           "production_git_sha": "sha", "attempt": 2}
    isolation = {"forbidden_read_attempts": [], "model_configuration": {}}
    result = module["technical_failure_summary"](run, isolation, "parser", ["API HTTP 404 " * 4] * 3)
    assert result["technical_failure"]["http_status_counts"] == {"404": 12}
    assert result["technical_failure"]["http_401_invalid_token"] == 0
    assert result["requests"]["production_attempts"] == 2
    assert result["metrics"] is None and not result["evaluator_executed"]


def test_502_provider_failure_preserves_reported_messages_without_scoring():
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    run = {"benchmark_id": "example", "article_id": "example", "status": "BENCHMARK_NOT_RUN",
           "production_git_sha": "sha", "attempt": 3}
    errors = ['API HTTP 502: {"error":{"message":"Upstream access forbidden, please contact administrator","type":"upstream_error"}}'] * 2
    errors += ['API HTTP 502: {"error":{"message":"Upstream service temporarily unavailable","type":"upstream_error"}}']
    result = module["technical_failure_summary"](run, {"forbidden_read_attempts": [], "model_configuration": {}}, "parser", errors)
    assert result["technical_failure"]["http_status_counts"] == {"502": 3}
    assert result["technical_failure"]["upstream_messages"] == {
        "Upstream access forbidden, please contact administrator": 2,
        "Upstream service temporarily unavailable": 1,
    }
    assert result["metrics"] is None and not result["evaluator_executed"]


def test_log_redaction_does_not_publish_keys(tmp_path):
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    env = tmp_path / ".env"
    fake_key = "test-only-secret-not-a-real-key"
    env.write_text("OPENAI_API_KEY=" + fake_key, encoding="utf-8")
    redacted = module["redact"]("credential=" + fake_key + " Authorization: Bearer test-token", env)
    assert fake_key not in redacted and "test-token" not in redacted


def test_retry_uses_new_directories_and_preserves_failure(tmp_path):
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    first = module["attempt_paths"](tmp_path, 1)
    second = module["attempt_paths"](tmp_path, 2)
    assert not set(first).intersection(second)
    first[2].mkdir(parents=True)
    manifest = first[2] / "PRODUCTION_RUN.json"
    original = b'{"status":"BENCHMARK_NOT_RUN"}'
    manifest.write_bytes(original)
    previous = module["failed_predecessors"](tmp_path, 2)
    assert len(previous) == 1 and previous[0]["attempt"] == 1
    assert manifest.read_bytes() == original
    assert all(not path.exists() for path in second)


@pytest.mark.parametrize("status,frozen", [
    ("PRODUCTION_COMPLETE", False), ("RUNNING", False), ("BENCHMARK_NOT_RUN", True),
])
def test_retry_rejects_success_running_or_frozen_baseline(tmp_path, status, frozen):
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_run_isolated_production.py"))
    directory = module["attempt_paths"](tmp_path, 1)[2]
    directory.mkdir(parents=True)
    (directory / "PRODUCTION_RUN.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    if frozen:
        (directory / "prediction.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        module["failed_predecessors"](tmp_path, 2)


def test_existing_converter_assembly_revalidates_without_reference_input():
    from article_agent.domain.models import ArticleExtraction
    from article_agent.trial_topology_agent import TrialTopology, topology_to_canonical

    module = runpy.run_path(str(ROOT / "scripts/pr5d1_build_prediction.py"))
    topology = TrialTopology.model_validate({"number_of_arms": 2, "arms": [
        {"name": name, "source_label": name, "evidence": [
            {"source_id": "article", "quote": "Allocated to Alpha and Beta", "arm_text": name}
        ]} for name in ("Alpha", "Beta")
    ]})
    arm_graph = topology_to_canonical("synthetic", topology)
    bundle = {"article_id": "synthetic", "parser_backend": "synthetic", "metadata": {
        "title": "Synthetic trial", "doi": "10.0000/synthetic", "evidence": []},
        "outcomes": {"outcomes": [{"outcome_name": "Synthetic measure", "timepoint": "1 week",
                                   "arm": [{"arm_label": "Alpha", "value": 12}]}]}}
    original = deepcopy(bundle)
    result, _ = module["assemble"](bundle, topology.model_dump(), arm_graph.model_dump())
    assert ArticleExtraction.model_validate_json(result.model_dump_json()) == result
    assert result.arms == arm_graph.arms and result.interventions == arm_graph.interventions
    assert result.article.legacy_fields["production_source_bundle"] == original == bundle
    assert result.article.title.value == "Synthetic trial"
    assert len(result.outcomes) == 1 and len(result.arm_results) == 1


@pytest.fixture(scope="module")
def frozen_baseline():
    """Only the publishable local baseline, frozen Gold and registry; no outputs cache."""
    from article_agent.domain.models import ArticleExtraction
    from article_agent.evaluation import GoldStandardV2, evaluate_article
    from article_agent.evaluation.models import EvaluationReportV2
    from article_agent.evaluation.registry import load_registry

    directory = ROOT / "benchmarks/2015-06/baseline_v1"
    read = lambda name: (directory / name).read_bytes()
    prediction = ArticleExtraction.model_validate_json(read("prediction.json"))
    gold_bytes = (ROOT / "gold/2015-06/gold.json").read_bytes()
    gold = GoldStandardV2.model_validate_json(gold_bytes)
    registry = load_registry(ROOT / "schemas/evaluator-field-registry-v3.json")
    return {
        "directory": directory, "prediction": prediction, "gold": gold,
        "gold_bytes": gold_bytes, "registry": registry,
        "evaluation_bytes": read("evaluation.json"),
        "stored": EvaluationReportV2.model_validate_json(read("evaluation.json")),
        "replayed": evaluate_article(prediction, gold, registry),
        "summary": json.loads(read("SUMMARY.json")),
        "manifest": json.loads(read("RUN_MANIFEST.json")),
    }


def test_real_baseline_frozen_gold_and_prediction_contract(frozen_baseline):
    b = frozen_baseline
    assert b["gold"].state == "FROZEN"
    assert b["gold"].gold_id == "2015-06-gold-v1"
    assert b["gold"].gold_version == "GOLD_STANDARD/2.0.0"
    assert b["prediction"].schema_version == "ARTICLE_EXTRACTION/2.0"
    assert b["stored"].report_version == "EVALUATION_REPORT/2.0.0"
    assert b["manifest"]["status"] == "BENCHMARK_COMPLETE"
    assert b["manifest"]["prediction_frozen_before_evaluation"] is True
    assert hashlib.sha256(b["gold_bytes"]).hexdigest() == b["manifest"]["gold_json_sha256"]
    assert hashlib.sha256((b["directory"] / "prediction.json").read_bytes()).hexdigest() == b["manifest"]["prediction_sha256"]
    assert hashlib.sha256(b["evaluation_bytes"]).hexdigest() == b["manifest"]["evaluation_sha256"]
    assert hashlib.sha256((ROOT / "schemas/evaluator-field-registry-v3.json").read_bytes()).hexdigest() == b["manifest"]["registry_sha256"]


def test_real_baseline_prediction_serialize_revalidate(frozen_baseline):
    from article_agent.domain.models import ArticleExtraction
    prediction = frozen_baseline["prediction"]
    assert ArticleExtraction.model_validate_json(prediction.model_dump_json()) == prediction


def test_real_baseline_evaluator_is_offline_and_byte_identical(frozen_baseline, monkeypatch):
    from article_agent import models
    from article_agent.evaluation import evaluate_article
    def forbidden(*args, **kwargs):
        raise AssertionError("Benchmark evaluation must not call an API")
    monkeypatch.setattr(models.OpenAICompatibleClient, "chat_json", forbidden)
    monkeypatch.setattr(models.OpenAICompatibleClient, "chat_vision_json", forbidden)
    monkeypatch.setattr(models, "_curl_json", forbidden)
    monkeypatch.setattr(models.urllib.request, "urlopen", forbidden)
    b = frozen_baseline
    before = (b["directory"] / "prediction.json").read_bytes()
    first = (b["replayed"].model_dump_json(indent=2) + "\n").encode("utf-8")
    second = (evaluate_article(b["prediction"], b["gold"], b["registry"]).model_dump_json(indent=2) + "\n").encode("utf-8")
    assert first == second == b["evaluation_bytes"]
    assert (b["directory"] / "prediction.json").read_bytes() == before


@pytest.mark.parametrize("metric", [
    "hard_exact", "production_coverage", "supported_value_accuracy", "status_accuracy", "evidence_grounding",
])
def test_real_baseline_metrics_are_verbatim_evaluator_metrics(frozen_baseline, metric):
    b = frozen_baseline
    assert b["summary"]["metrics"][metric] == b["replayed"].metrics[metric] == b["stored"].metrics[metric]


def test_real_baseline_failure_entity_conflict_summaries(frozen_baseline):
    b = frozen_baseline
    for field in ("field_failure_counts", "entity_failure_counts"):
        assert b["summary"][field] == getattr(b["stored"], field) == getattr(b["replayed"], field)
    for field in ("entities", "conflicts"):
        assert b["summary"][field] == b["stored"].metrics[field] == b["replayed"].metrics[field]
    assert b["summary"]["performance_threshold"] is None
    assert b["summary"]["acceptance"]["no_performance_threshold"] is True


def test_real_baseline_reviewed_uncertainty_is_excluded(frozen_baseline):
    excluded = [f for f in frozen_baseline["stored"].field_results if f.gold_status == "REVIEW_REQUIRED"]
    assert {f.field_id for f in excluded} == {"study.centre_count", "study.participant_blinding"}
    assert all(not f.in_hard_denominator and not f.in_value_accuracy_denominator for f in excluded)


def test_real_baseline_declares_transport_exception_and_all_sol(frozen_baseline):
    b = frozen_baseline
    assert b["manifest"]["production_git_sha"] == "eefa90ff85935af980c2fedcc2917d4771a94e5e"
    assert b["manifest"]["api_mode"] == "responses"
    assert set(b["manifest"]["model_configuration"].values()) == {"gpt-5.6-sol"}
    assert b["manifest"]["authorized_transport_patch"]["path"] == "src/article_agent/models.py"
    assert b["manifest"]["tracked_git_status_at_start"].strip()
    assert b["summary"]["acceptance"]["production_unmodified"] is False
    assert b["summary"]["acceptance"]["extraction_algorithms_unmodified"] is True


def test_real_baseline_no_gold_input_or_raw_data_file_publication(frozen_baseline):
    b = frozen_baseline
    isolation = json.loads((b["directory"] / "PRODUCTION_ISOLATION.json").read_bytes())
    assert isolation["forbidden_read_attempts"] == []
    assert not isolation["gold_or_label_inputs_present"]
    assert not isolation["loader_monkeypatched"]
    source = json.loads((b["directory"] / "ISOLATED_SOURCE_MANIFEST.json").read_bytes())
    assert all(not ({"gold", "labels", "label"} & set(Path(name).parts)) for name in source["files"])
    assert not b["summary"]["production_audit"]["gold_used_for_postprocess_comparison"]
    pred = b["prediction"].model_dump(mode="json")
    def assert_no_annotation_keys(value):
        if isinstance(value, dict):
            assert not {"gold_id", "gold_path", "gold_values"}.intersection(value)
            for item in value.values():
                assert_no_annotation_keys(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_annotation_keys(item)
    assert_no_annotation_keys(pred)
    for path in b["directory"].iterdir():
        assert path.suffix in {".json", ".md"}
        assert not re.search(r"sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+", path.read_text(encoding="utf-8"))


def test_real_baseline_snapshot_hashes(frozen_baseline):
    directory = frozen_baseline["directory"]
    snapshot = json.loads((directory / "SNAPSHOT_MANIFEST.json").read_bytes())
    for name, digest in snapshot["files"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest


def test_real_baseline_audit_does_not_confuse_row_coverage_with_value_accuracy(frozen_baseline):
    b = frozen_baseline
    audit = b["summary"]["production_audit"]
    assert audit["raw_source_bundle_preserved"] and audit["arm_intervention_sample_flow_unchanged"]
    assert audit["source_integrity"]["mismatches"] == []
    source_records = b["prediction"].article.legacy_fields["production_source_bundle"]["outcomes"]["outcomes"]
    assert len(source_records) == audit["raw_outcome_count"]
    assert audit["outcome_request_status_counts"]["failed"] > 0
    assert all(not table["missing_row_ids"] for table in audit["row_coverage"])
    assert any(table["status"] == "skipped" for table in audit["row_coverage"])
    assert audit["complete_http_request_total"] is None
    # These are different denominators; row coverage cannot replace evaluation metrics.
    assert "coverage_note" in audit and "request_count_note" in audit


def test_snapshot_publisher_does_not_overwrite_existing_directory(frozen_baseline, tmp_path):
    module = runpy.run_path(str(ROOT / "scripts/pr5d1_2015_06_real_benchmark.py"))
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        module["freeze_snapshot"](frozen_baseline["directory"], existing)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
