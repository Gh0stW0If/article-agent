import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "entity_attachment_audit.py"
    spec = importlib.util.spec_from_file_location("entity_attachment_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_parent_correct_but_merger_changes_parent():
    m = _module()
    stage, root = m.locate_first_failure({
        "candidate": {"outcome": "O1", "needs_arm": True, "arm": "A1"},
        "candidate_parent": ("O1", "A1"),
        "construction_parent": ("O1", "A1"),
        "binding_parent": ("O1", "A1"),
        "merger_parent": ("O2", "A1"),
        "final_parent": ("O2", "A1"),
    })
    assert (stage, root) == ("MERGER", "PARENT_CHANGED_DURING_MERGE")


def test_candidate_missing_outcome_is_skill_extraction():
    m = _module()
    assert m.locate_first_failure({"candidate": {"value": 3}}) == (
        "SKILL_EXTRACTION", "PARENT_INCOMPLETE_AT_EXTRACTION"
    )


def test_result_construction_binding_error():
    m = _module()
    stage, root = m.locate_first_failure({
        "candidate": {"outcome": "O1", "needs_arm": True, "arm": "A1"},
        "candidate_parent": ("O1", "A1"),
        "construction_parent": ("O1", "A2"),
        "binding_parent": ("O1", "A2"),
        "merger_parent": ("O1", "A2"),
        "final_parent": ("O1", "A2"),
    })
    assert (stage, root) == ("RESULT_CONSTRUCTION", "PARENT_CHANGED_DURING_RESULT_CONSTRUCTION")


def test_final_projection_or_evaluator_only():
    m = _module()
    assert m.locate_first_failure({
        "candidate": {"outcome": "O1"},
        "candidate_parent": ("O1",),
        "construction_parent": ("O1",),
        "binding_parent": ("O1",),
        "merger_parent": ("O1",),
        "final_parent": ("O2",),
    }) == ("FINAL_PROJECTION", "WRONG_OUTCOME")
    assert m.locate_first_failure({
        "candidate": {"outcome": "O1"},
        "candidate_parent": ("O1",),
        "construction_parent": ("O1",),
        "binding_parent": ("O1",),
        "merger_parent": ("O1",),
        "final_parent": ("O1",),
        "evaluator_mapping_error": True,
    }) == ("EVALUATOR_ONLY", "OTHER")


def test_missing_artifact_is_not_available_not_guessed():
    m = _module()
    assert m.locate_first_failure({"artifact_available": False}) == (
        "UNKNOWN", "ARTIFACT_NOT_AVAILABLE"
    )
