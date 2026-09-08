import importlib.util
import json
from pathlib import Path

from article_agent.trial_topology_agent import topology_to_canonical
from test_arm_details import fixture


def test_default_runner_reuses_frozen_topology(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "scripts/pr3_arm_details_acceptance_v2.py"
    spec = importlib.util.spec_from_file_location("acceptance_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    source, topology, _ = fixture()
    aid = "2015-06"
    frozen_dir = tmp_path / "frozen" / aid
    frozen_dir.mkdir(parents=True)
    frozen_path = frozen_dir / "trial_topology.json"
    frozen_path.write_text(topology.model_dump_json(), encoding="utf-8")
    (frozen_dir / "article.md").write_text(source, encoding="utf-8")
    clients = []
    monkeypatch.setattr(runner, "load_env_file", lambda: None)
    monkeypatch.setattr(runner, "OpenAICompatibleClient", lambda **kw: clients.append(kw))
    def forbidden(*args, **kwargs):
        raise AssertionError("topology API must not be called")
    monkeypatch.setattr(runner, "run_topology", forbidden)
    calls = []
    def details(article_id, markdown, frozen, output, client):
        calls.append(article_id)
        return topology_to_canonical(article_id, frozen)
    monkeypatch.setattr(runner, "run_arm_details", details)
    assert runner.main([aid, "--topology-root", str(tmp_path / "frozen"),
        "--markdown-root", str(tmp_path / "frozen"), "--output-root", str(tmp_path / "out")]) == 0
    assert calls == [aid]
    assert len(clients) == 1
    entry = json.loads((tmp_path / "out/SUMMARY.json").read_text())[0]
    assert entry["article_id"] == aid
    assert entry["topology_api_called"] is False
    assert entry["canonical_revalidation"] == "passed"
    assert set(entry["arms"][0]["sample_flow"]) == set(runner.FLOW_FIELDS)
    assert entry["retries"] == 0
    assert entry["validation_failures"] == []
    assert frozen_path.read_text(encoding="utf-8") == topology.model_dump_json()
