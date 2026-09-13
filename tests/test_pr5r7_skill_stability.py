from __future__ import annotations

from scripts.pr5r7_skill_stability import (
    classify_contract,
    pairwise_metrics,
    value_stability,
)


def test_same_content_different_order_has_stable_set_overlap():
    metrics = pairwise_metrics({
        "run_a": {"a", "b"},
        "run_b": {"b", "a"},
        "run_c": {"a", "b"},
    })
    assert metrics["intersection"] == ["a", "b"]
    assert metrics["pairwise"]["run_a-run_b"]["jaccard"] == 1.0


def test_pairwise_extra_record_is_structure_drift():
    metrics = pairwise_metrics({
        "run_a": {"slot-1"},
        "run_b": {"slot-1", "slot-2"},
        "run_c": {"slot-1"},
    })
    assert metrics["pairwise"]["run_a-run_b"]["only_right"] == ["slot-2"]
    assert metrics["run_specific"]["run_b"] == ["slot-2"]


def test_pairwise_missing_content_is_run_specific():
    metrics = pairwise_metrics({
        "run_a": {"slot-1", "slot-a-only"},
        "run_b": {"slot-1"},
        "run_c": {"slot-1"},
    })
    assert metrics["run_specific"]["run_a"] == ["slot-a-only"]


def test_value_stability_distinguishes_different_values_without_gold():
    class Field:
        def __init__(self, value):
            self.value = value
            self.status = "PRESENT"

    class Result:
        def __init__(self, value):
            self.outcome_id = "o1"
            self.arm_id = "a1"
            self.comparison_id = "c1"
            self.timepoint = Field("Baseline")
            self.value = Field(value)
            self.value_kind = Field("mean")
            self.raw_value = Field(str(value))

    class Outcome:
        outcome_id = "o1"
        name = Field("Pain")
        instrument = Field("VAS")

    class Prediction:
        outcomes = [Outcome()]
        arm_results = [Result(1)]
        comparison_results = []

    class Prediction2(Prediction):
        arm_results = [Result(2)]

    result = value_stability({
        "run_a": Prediction(),
        "run_b": Prediction2(),
        "run_c": Prediction(),
    })
    assert result["counts"]["DIFFERENT_VALUE"] == 1


def test_value_stability_reports_missing_value_in_present_slot():
    class Field:
        def __init__(self, value):
            self.value = value
            self.status = "PRESENT"

    class Result:
        def __init__(self, value):
            self.outcome_id = "o1"
            self.arm_id = "a1"
            self.comparison_id = "c1"
            self.timepoint = Field("Baseline")
            self.value = Field(value)
            self.value_kind = Field("mean")
            self.raw_value = Field(str(value) if value is not None else "")

    class Outcome:
        outcome_id = "o1"
        name = Field("Pain")
        instrument = Field("VAS")

    class Prediction:
        outcomes = [Outcome()]
        comparison_results = []

    result = value_stability({
        "run_a": type("P", (Prediction,), {"arm_results": [Result(1)]})(),
        "run_b": type("P", (Prediction,), {"arm_results": [Result(None)]})(),
        "run_c": type("P", (Prediction,), {"arm_results": [Result(1)]})(),
    })
    assert result["counts"]["MISSING_IN_ONE_RUN"] == 1


def test_contract_with_missing_prompt_hash_is_not_provable():
    keys = (
        "parser_backend", "parser_output_hash", "markdown_hash",
        "retrieval_context_hash", "evidence_context_hash",
        "result_construction_version", "candidate_generation_path",
    )
    rows = {key: {"status": "SAME"} for key in keys}
    rows["skill_prompt_hashes"] = {"status": "NOT_AVAILABLE"}
    assert classify_contract(rows) == "CONTRACT_NOT_PROVABLE"


def test_contract_drift_is_not_attributed_to_stochastic_variance():
    keys = (
        "parser_backend", "parser_output_hash", "markdown_hash",
        "retrieval_context_hash", "evidence_context_hash",
        "result_construction_version", "candidate_generation_path",
    )
    rows = {key: {"status": "SAME"} for key in keys}
    rows["parser_backend"] = {"status": "DIFFERENT"}
    assert classify_contract(rows) == "RUN_CONTRACT_DRIFT"
