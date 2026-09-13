from __future__ import annotations

import json
from pathlib import Path

from scripts.pr5r6_reproducibility import (
    RUN_NAMES,
    compare_runs,
    copy_source_snapshot,
)


def _snapshot(**overrides):
    base = {
        "parser_output_hash": "parser",
        "article_markdown_hash": "markdown",
        "retrieval_context_hash": "context",
        "evidence_context_hash": "evidence",
        "skill_raw_output_hash": "skill",
        "candidate_count": 3,
        "result_counts": {
            "outcomes": 2,
            "arm_results": 15,
            "comparisons": 2,
            "comparison_results": 12,
        },
        "final_prediction_hash": "prediction",
    }
    base.update(overrides)
    return base


def test_layer_comparison_identifies_first_difference():
    runs = {
        "run_a": _snapshot(),
        "run_b": _snapshot(skill_raw_output_hash="different-skill"),
        "run_c": _snapshot(skill_raw_output_hash="different-skill"),
    }
    comparison = compare_runs(runs)
    assert comparison["pairwise"]["run_b"]["first_difference"] == "skill_raw_output"
    assert comparison["pairwise"]["run_c"]["first_difference"] == "skill_raw_output"
    assert comparison["interpretation"] == "LLM Skill raw-output variance"


def test_layer_comparison_detects_downstream_count_drift():
    runs = {
        "run_a": _snapshot(),
        "run_b": _snapshot(
            candidate_count=4,
            result_counts={
                "outcomes": 2,
                "arm_results": 16,
                "comparisons": 2,
                "comparison_results": 12,
            },
        ),
        "run_c": _snapshot(),
    }
    comparison = compare_runs(runs)
    assert comparison["pairwise"]["run_b"]["first_difference"] == "candidate_count"
    assert comparison["interpretation"] == "construction/merger or downstream variance"


def test_source_snapshot_excludes_gold_label_and_outputs(tmp_path: Path):
    destination = tmp_path / "isolated"
    copied = copy_source_snapshot(destination)
    assert copied
    assert not (destination / "Datas/label").exists()
    assert not (destination / "gold").exists()
    assert not (destination / "outputs").exists()
    assert not any(
        Path(relative).parts[:2] == ("Datas", "label")
        or Path(relative).parts[:1] in {("gold",), ("outputs",)}
        for relative in copied
    )


def test_compare_runs_is_deterministic_and_uses_all_three_runs():
    runs = {name: _snapshot() for name in RUN_NAMES}
    first = compare_runs(runs)
    second = compare_runs(json.loads(json.dumps(runs)))
    assert first == second
    assert first["all_layers_equal"] is True
    assert first["interpretation"] == "no observed drift in compared layers"
