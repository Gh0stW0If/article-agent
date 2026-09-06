"""Offline topology tests use synthetic allocation statements, never Gold or private articles."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from article_agent.domain import ArticleExtraction, FieldStatus, legacy_bundle_to_canonical
from article_agent.trial_topology_agent import (
    TrialTopology, extract_trial_topology, topology_to_canonical, validate_and_order, run_topology,
)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def chat_json(self, messages, temperature=0.0):
        self.requests.append(json.loads(messages[1]["content"]))
        return deepcopy(self.response)


def allocation(names):
    text = "Patients were randomized to " + ", ".join(f"group {i} ({name})" for i, name in enumerate(names, 1)) + "."
    response = {"number_of_arms": len(names), "arms": [
        {"source_label": f"group {i}", "name": name, "role": None, "aliases": [], "evidence": [
            {"source_id": "article", "quote": text, "arm_text": f"group {i} ({name})"}]
        } for i, name in enumerate(names, 1)
    ]}
    return text, response


@pytest.mark.parametrize("count", [2, 3, 4, 7])
def test_multi_arm_topology(count):
    text, response = allocation([f"Treatment {i}" for i in range(count)])
    result = extract_trial_topology({"article": text}, FakeClient(response))
    assert result.number_of_arms == count
    canonical = topology_to_canonical("trial", result)
    assert len(canonical.studies) == 1 and len(canonical.arms) == count
    assert canonical.studies[0].arm_ids == [f"trial-S1-A{i:02d}" for i in range(1, count + 1)]
    assert all(a.randomized_n.status == FieldStatus.UNRESOLVED for a in canonical.arms)
    ArticleExtraction.model_validate_json(canonical.model_dump_json())


def test_stable_arm_ids_do_not_depend_on_name():
    text, response = allocation(["Treatment A", "Treatment B"])
    topology = extract_trial_topology({"article": text}, FakeClient(response))
    before = topology_to_canonical("trial", topology)
    renamed = topology.model_copy(deep=True)
    renamed.arms[0].name = "Normalized display name"
    after = topology_to_canonical("trial", renamed)
    assert [a.arm_id for a in before.arms] == [a.arm_id for a in after.arms]


def test_arm_order_deterministic_despite_llm_permutation():
    text, response = allocation(["Z treatment", "A treatment", "M treatment"])
    baseline = extract_trial_topology({"article": text}, FakeClient(response))
    response["arms"].reverse()
    shuffled = extract_trial_topology({"article": text}, FakeClient(response))
    assert shuffled == baseline
    assert [a.name for a in shuffled.arms] == ["Z treatment", "A treatment", "M treatment"]


def test_no_automatic_pairwise_comparison_generation():
    text, response = allocation(["A", "B", "C", "D"])
    canonical = topology_to_canonical("trial", extract_trial_topology({"article": text}, FakeClient(response)))
    assert canonical.comparisons == []
    assert canonical.comparison_results == []
    assert canonical.interventions == []
    assert canonical.outcomes == [] and canonical.arm_results == []


def test_2015_06_regression(tmp_path):
    # Synthetic restatement of the reviewed allocation, not a Gold fixture.
    names = ["CIC", "EA + CIC", "Sham acupuncture + CIC"]
    text, response = allocation(names)
    canonical = run_topology("2015-06", text, tmp_path, FakeClient(response))
    assert canonical.article.article_id == "2015-06"
    assert len(canonical.studies) == 1
    assert [a.label.value for a in canonical.arms] == names
    assert [a.arm_id for a in canonical.arms] == ["2015-06-S1-A01", "2015-06-S1-A02", "2015-06-S1-A03"]
    assert len(canonical.comparisons) == 0
    assert json.loads((tmp_path / "topology.manifest.json").read_text())["number_of_arms"] == 3


@pytest.mark.parametrize("count", [2, 3])
def test_adapter_uses_topology_arms_not_legacy_pair_or_result_aliases(count):
    names = ["CIC", "EA + CIC", "Sham acupuncture + CIC"][:count]
    text, response = allocation(names)
    topology = extract_trial_topology({"article": text}, FakeClient(response))
    source = {"article_id": "trial", "metadata": {"intervention": names[1], "control": names[0]},
              "outcomes": {"outcomes": [{"outcome_name": "Score", "arm": [
                  {"arm_id": "source-arm", "arm_label": names[0], "value": 12},
                  {"arm_id": "unknown-alias", "arm_label": "Unresolved legacy alias", "value": 20},
              ]}]}}
    before = deepcopy(source)
    result = legacy_bundle_to_canonical(source, topology=topology)
    assert source == before
    assert len(result.arms) == count
    assert [a.label.value for a in result.arms] == names
    assert result.studies[0].arm_ids == [a.arm_id for a in result.arms]
    assert len(result.arm_results) == 1
    assert result.arm_results[0].arm_id == "trial-S1-A01"
    assert result.adapter_warnings
    assert result.outcomes[0].legacy_fields["arm"][1]["value"] == 20
    assert result.comparisons == []
    assert all(a.intervention_ids == [] for a in result.arms)


def test_missing_or_fabricated_topology_does_not_fallback_to_two():
    client = FakeClient({"number_of_arms": 0, "arms": []})
    with pytest.raises(ValueError, match="no two-arm fallback"):
        extract_trial_topology({"article": "Allocation unknown"}, client, retries=1)
    assert len(client.requests) == 2
    assert client.requests[1]["validation_feedback"]
    text, response = allocation(["A", "B"])
    response["arms"][0]["evidence"][0]["quote"] = "Fabricated source"
    with pytest.raises(ValueError, match="verbatim"):
        extract_trial_topology({"article": text}, FakeClient(response), retries=0)


def test_count_mismatch_and_llm_assigned_ids_rejected():
    _, response = allocation(["A", "B"])
    response["number_of_arms"] = 3
    with pytest.raises(ValidationError):
        TrialTopology.model_validate(response)
    response["number_of_arms"] = 2
    response["arms"][0]["arm_id"] = "LLM-invented-ID"
    with pytest.raises(ValidationError):
        TrialTopology.model_validate(response)


def test_request_does_not_truncate_sources():
    text, response = allocation(["A", "B"])
    text = "Large source context " * 10000 + text
    client = FakeClient(response)
    extract_trial_topology({"article": text}, client)
    assert client.requests[0]["sources"]["article"] == text


def test_topology_schema_matches_published():
    root = Path(__file__).resolve().parents[1]
    assert json.loads((root / "schemas/trial-topology.schema.json").read_text(encoding="utf-8")) == TrialTopology.model_json_schema()


@pytest.mark.parametrize("article_id,names", [
    ("2015-04", ["Body acupuncture", "Sa-am acupuncture", "Usual care"]),
    ("2015-05", ["Auricular acupuncture + usual care", "Placebo + usual care", "Usual care"]),
])
def test_other_three_arm_trials_do_not_regress_to_two(article_id, names):
    text, response = allocation(names)
    topology = extract_trial_topology({"article": text}, FakeClient(response))
    canonical = legacy_bundle_to_canonical({"article_id": article_id}, topology=topology)
    assert len(canonical.arms) == 3
    assert [arm.label.value for arm in canonical.arms] == names


def test_quota_failure_does_not_retry_or_invent_topology():
    class NoQuotaClient:
        calls = 0
        def chat_json(self, messages, temperature=0.0):
            self.calls += 1
            raise RuntimeError("insufficient_user_quota")
    client = NoQuotaClient()
    with pytest.raises(RuntimeError, match="quota unavailable"):
        extract_trial_topology({"article": "trial text"}, client, retries=2)
    assert client.calls == 1
