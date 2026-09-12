"""Generic result-surface tests; fixtures do not depend on the real benchmark."""
from copy import deepcopy
import inspect
import json
from pathlib import Path

import pytest

from article_agent.domain.models import (
    Article, ArticleExtraction, Study, Arm, Outcome, ArmResult, Comparison, ComparisonResult,
    CanonicalField, Evidence, EvidenceTarget, ConflictCandidate,
)
from article_agent.result_surface import normalize_result_surfaces
from article_agent.result_surface.field_binding import (
    bind_comparison_scalar, comparison_definitions, parse_p_surface, unwrap_surface,
)
from article_agent.result_surface.statistic_surface import recognize_mean
from article_agent.result_surface.surface_normalization import contrast_surface, normalize_contrast_conflict


def present(value, *ids):
    return CanonicalField(status="PRESENT", value=value, raw_value=str(value), evidence_ids=list(ids))


def fixture(p_values=("0.3", "0.107", "<0.001"), mean_header="Mean (SD)", mean_cell="23.4 (5.6)"):
    ids = ["trial-S-A", "trial-S-B", "trial-S-C"]
    labels = ["Group A", "Group B", "Group C"]
    table, row = "outcomes-table", "outcomes-table:r002"
    arms = [Arm(arm_id=aid, study_id="trial-S", label=present(label),
                legacy_fields={"topology": {"source_label": label, "name": label}})
            for aid, label in zip(ids, labels)]
    ar = ArmResult(arm_result_id="measurement", arm_id=ids[0], outcome_id="volume",
        value_kind=present("other", "kind-source"), value=present(23.4), standard_deviation=present(5.6),
        source_table_id=table, source_row_id=row, timepoint=present("6 weeks"))
    comp = Comparison(comparison_id="reported-contrast", study_id="trial-S",
        arm_ids=[ids[0], ids[2]], contrast=present("Group A vs Group C"))
    container = json.dumps([mean_cell, "67.8 (1.2)", "42.3 (2.1)", *p_values])
    cr = ComparisonResult(comparison_result_id="contrast-result", comparison_id=comp.comparison_id,
        outcome_id="volume", raw_value=present(container, "p-source"),
        p_value=present(parse_p_surface(p_values[1])["numeric_value"]), timepoint=present("6 weeks"),
        legacy_fields={"source_observations": [{"table_id": table, "row_id": row}]})
    evidence = [
        Evidence(evidence_id="kind-source", quote="Source row: " + mean_cell, source_type="table",
                 source_id=row, table_id=table, row_id=row,
                 targets=[EvidenceTarget(entity_type="ArmResult", entity_id=ar.arm_result_id, field_id="value_kind")]),
        Evidence(evidence_id="p-source", quote="Source row: " + container, source_type="table",
                 source_id=row, table_id=table, row_id=row,
                 targets=[EvidenceTarget(entity_type="ComparisonResult", entity_id=cr.comparison_result_id, field_id="raw_value")]),
    ]
    graph = ArticleExtraction(article=Article(article_id="trial"),
        studies=[Study(study_id="trial-S", article_id="trial", arm_ids=ids, outcome_ids=["volume"])],
        arms=arms, outcomes=[Outcome(outcome_id="volume", study_id="trial-S", name=present("Synthetic volume"))],
        arm_results=[ar], comparisons=[comp], comparison_results=[cr], evidence=evidence)
    cells = ["Synthetic volume", mean_cell, "67.8 (1.2)", "42.3 (2.1)", *p_values]
    headers = [["Outcome"], *[[label, mean_header] for label in labels], ["P1"], ["P2"], ["P3"]]
    columns = [{"column_index": i, "header_path": h,
                "arm_label": labels[i - 1] if 1 <= i <= 3 else "NR",
                "statistic": "p_value" if i > 3 else "value",
                "source_cells": [{"row_id": row, "raw_value": cells[i], "column_index": i,
                                  "colspan": 1, "rowspan": 1}]} for i, h in enumerate(headers)]
    context = {"tables": [{"table_id": table, "column_map": columns, "caption": "",
        "footnote": "P1: Group A vs Group B; P2: Group A vs Group C; P3: Group B vs Group C.",
        "source_ref": "synthetic.md", "raw_table": "synthetic table", "header_rows": []}],
        "reporting_statements": [], "source_ref": "synthetic.md", "source_document_sha256": "synthetic"}
    return graph, context


@pytest.mark.parametrize("cell,header,statements,expected", [
    ("23.4 (5.6)", "Mean (SD)", [], True),
    ("23.4 ± 5.7", "Mean ± SD", [], True),
    ("23.4 ± 5.7", "Treatment", ["Quantitative data were expressed as mean ± standard deviation (SD)."], True),
    ("23.4", "", [], False),
    ("23.4 ± 5.7", "", [], False),
    ("23 (45%)", "n (%)", [], False),
    ("23 (45)", "n (%)", ["Quantitative data were expressed as mean ± standard deviation."], False),
    ("23.4 (5.7)", "Median (IQR)", [], False),
    ("23.4 ± 5.7", "Mean ± SE", ["Quantitative data were expressed as mean ± standard deviation."], False),
    ("23.4 (5.7)", "", ["Quantitative data were expressed as mean ± standard deviation."], False),
])
def test_statistic_needs_explicit_source_relation(cell, header, statements, expected):
    assert bool(recognize_mean(cell, header, statements)) is expected


@pytest.mark.parametrize("raw,op,value,canonical", [
    ("P<0.001", "<", 0.001, "<0.001"), ("p < 0.001", "<", 0.001, "<0.001"),
    ("<0.001", "<", 0.001, "<0.001"), ("P = 0.107", "=", 0.107, "0.107"),
    ("p=0.107", "=", 0.107, "0.107"), ("0.107", "=", 0.107, "0.107"),
    ("p ≤ 0.050", "<=", 0.05, "<=0.05"), ("P=1e-3", "=", 0.001, "0.001"),
])
def test_p_surface_keeps_raw_and_operator(raw, op, value, canonical):
    parsed = parse_p_surface(raw)
    assert parsed == {"raw_scalar": raw, "operator": op, "numeric_value": value, "canonical_scalar": canonical}


@pytest.mark.parametrize("raw", ["[0.2, 0.3]", "p=2", "nan", "-0.3", "P<0.001; P=0.1", "95% CI (0.1, 0.3)", "P1"])
def test_invalid_p_surface_abstains(raw):
    assert parse_p_surface(raw) is None


def test_singleton_unwrap_preserves_source():
    raw = ["P<0.001"]
    value, rules, blocker = unwrap_surface(raw)
    assert value == "P<0.001" and rules == ["SINGLETON_SOURCE_WRAPPER_UNWRAPPED"] and blocker is None
    assert raw == ["P<0.001"]
    assert unwrap_surface('["P<0.001"]') == (value, rules, blocker)


def test_multivalue_no_binding_abstains():
    graph, context = fixture()
    context["tables"] = []
    bound = bind_comparison_scalar(graph.comparison_results[0], graph, context)
    assert bound["binding_result"] == "AMBIGUOUS"
    assert bound["selected_source_scalar"] is None
    assert "SOURCE_BINDING_AMBIGUOUS" in bound["blockers"]


def test_comparison_column_not_number_equality():
    graph, context = fixture(p_values=("0.107", "0.107", "0.9"))
    bound = bind_comparison_scalar(graph.comparison_results[0], graph, context)
    assert bound["column_index"] == 5 and bound["header_path"] == ["P2"]
    assert bound["selected_source_scalar"] == "0.107"
    assert bound["comparison_definition"][0]["arm_ids"] == ["trial-S-A", "trial-S-C"]


def test_gold_matching_number_in_wrong_column_not_selected():
    gold_expected = "0.107"  # Audit/test only; not passed into the binder.
    graph, context = fixture(p_values=(gold_expected, "0.8", "0.9"))
    bound = bind_comparison_scalar(graph.comparison_results[0], graph, context)
    assert bound["column_index"] == 5
    assert bound["canonical_scalar"] == "0.8" != gold_expected


def test_missing_or_contradictory_comparator_definition_abstains():
    graph, context = fixture()
    table = context["tables"][0]
    table["footnote"] = ""
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"
    table["footnote"] = "P2: Group A vs Group C; P2: Group A vs Group B"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"
    table["footnote"] = "P2: Group A vs Group C; P2: unidentified comparison"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"


def test_duplicate_comparison_columns_or_rows_abstain():
    graph, context = fixture()
    context["tables"][0]["footnote"] += "; P1: Group A vs Group C"
    # Both possible columns are never arbitrated by their values.
    context["tables"][0]["footnote"] = "P1: Group A vs Group C; P2: Group A vs Group C"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"
    graph, context = fixture()
    context["tables"].append(deepcopy(context["tables"][0]))
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"


def test_duplicate_arm_alias_and_wrong_field_row_abstain():
    graph, context = fixture()
    graph.arms[1].legacy_fields["topology"]["source_label"] = "Group A"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"
    graph, context = fixture()
    graph.evidence[1].row_id = "a-different-row"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"


def test_no_p_kind_or_multiple_statistic_roles_never_treated_as_p():
    graph, context = fixture()
    graph.comparison_results[0].estimate = present(0.107)
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["blockers"] == ["MULTI_STATISTIC_RAW_ROLE_AMBIGUOUS"]
    graph, context = fixture()
    for c in context["tables"][0]["column_map"]:
        c["statistic"] = "effect"
        c["header_path"] = [h.replace("P", "Effect") for h in c["header_path"]]
    context["tables"][0]["footnote"] = context["tables"][0]["footnote"].replace("P", "Effect")
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"


def narrative_fixture():
    graph, context = fixture(p_values=("0.3", "<0.001", "0.9"))
    context["tables"] = []
    graph.comparison_results[0].raw_value.value = '["P<0.001"]'
    graph.comparison_results[0].raw_value.raw_value = '["P<0.001"]'
    graph.evidence[1].quote = "Group A vs. Group C, P<0.001"
    return graph, context


def test_narrative_singleton_uses_local_named_comparison():
    graph, context = narrative_fixture()
    bound = bind_comparison_scalar(graph.comparison_results[0], graph, context)
    assert bound["canonical_scalar"] == "<0.001"
    assert bound["operations"] == ["SINGLETON_SOURCE_WRAPPER_UNWRAPPED"]
    assert bound["source_proof"][0]["evidence_id"] == "p-source"


def test_narrative_same_number_wrong_comparison_cannot_bind():
    graph, context = narrative_fixture()
    graph.evidence[1].quote = "Group A vs. Group B, P<0.001"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"
    graph.evidence[1].quote = "Group A vs. Group C, P<0.001; Group A vs. Group C, P=0.9"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"
    graph.evidence[1].quote = "Group A vs. Group C, P<0.001; Group A vs. Group C, P<0.001"
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"


def conflict(a, b):
    return CanonicalField(status="SOURCE_CONFLICT", evidence_ids=["a", "b"],
        conflict_candidates=[ConflictCandidate(value=a, raw_value=a, evidence_ids=["a"]),
                             ConflictCandidate(value=b, raw_value=b, evidence_ids=["b"])])


def test_case_whitespace_unicode_vs_punctuation_equivalent():
    result = normalize_contrast_conflict(conflict("Group 1 vs Group 2", "  group 1  vs. group 2 "))
    assert result == "group 1 vs group 2"
    assert contrast_surface("Ａ vs. Ｂ") == "a vs b"


@pytest.mark.parametrize("a,b", [
    ("Group 1 vs Group 2", "Group 1 vs Group 3"),
    ("Group 1 vs Group 2", "Group 2 vs Group 1"),
    ("intervention vs control", "intervention + control"),
    ("week 1", "week 3"),
    ("A-B vs C", "AB vs C"),
    ("dose 0.1 vs 0.2", "dose 01 vs 02"),
])
def test_semantic_differences_keep_conflict(a, b):
    assert normalize_contrast_conflict(conflict(a, b)) is None


def test_full_projection_source_immutable_references_valid():
    graph, context = fixture()
    original, source = graph.model_dump_json(), deepcopy(context)
    result = normalize_result_surfaces(graph, context)
    projected = result.prediction
    assert graph.model_dump_json() == original and context == source
    assert projected.arm_results[0].value_kind.value == "mean"
    assert projected.arm_results[0].value_kind.raw_value == "other"
    assert projected.arm_results[0].legacy_fields["result_surface"]["raw_fields"]["value_kind"]["value"] == "other"
    assert projected.comparison_results[0].raw_value.value == "0.107"
    assert projected.evidence[:len(graph.evidence)] == graph.evidence
    assert projected.arms == graph.arms and projected.outcomes == graph.outcomes
    assert projected.comparison_results[0].p_value_comparator.status == "UNRESOLVED"
    assert ArticleExtraction.model_validate_json(projected.model_dump_json()) == projected
    # Every new operation is evidence-bearing and reciprocated.
    for evidence in projected.evidence[len(graph.evidence):]:
        assert evidence.support_type == "derived" and evidence.derivation
        assert evidence.targets and evidence.legacy_fields["source_evidence_ids"]


def test_bare_numeric_or_no_mean_context_does_not_change_other():
    graph, context = fixture(mean_header="", mean_cell="23.4 ± 5.6")
    projected = normalize_result_surfaces(graph, context)
    assert projected.prediction.arm_results[0].value_kind == graph.arm_results[0].value_kind
    assert projected.statistic_events[0]["changed"] is False
    assert projected.statistic_events[0]["blocker"] == "EXPLICIT_MEAN_SD_SUPPORT_ABSENT"


def test_missing_scalar_fields_not_filled():
    graph, context = fixture()
    graph.arm_results[0].value = CanonicalField(status="UNRESOLVED")
    graph.comparison_results[0].p_value = CanonicalField(status="UNRESOLVED")
    projected = normalize_result_surfaces(graph, context).prediction
    assert projected.arm_results[0].value.status == "UNRESOLVED"
    assert projected.comparison_results[0].p_value.status == "UNRESOLVED"
    assert projected.comparison_results[0].raw_value == graph.comparison_results[0].raw_value


def test_production_api_gold_free_no_network_no_study_specific_rules():
    assert list(inspect.signature(normalize_result_surfaces).parameters) == ["prediction", "source_context"]
    assert list(inspect.signature(bind_comparison_scalar).parameters) == ["result", "graph", "context"]
    folder = Path(__file__).resolve().parents[1] / "src/article_agent/result_surface"
    for path in folder.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert all(forbidden not in text for forbidden in (
            "2015-06", "CIC", "bladder balance", "Group 1", "Group 2", '"P1"', '"P2"', '"P3"',
            "GoldStandard", "LiveSemanticJudge", "OpenAICompatibleClient", "from ..evaluation"))


def test_projection_is_repeatable():
    graph, context = fixture()
    a, b = normalize_result_surfaces(graph, context), normalize_result_surfaces(graph, context)
    assert a.prediction.model_dump_json() == b.prediction.model_dump_json()
    assert a.statistic_events == b.statistic_events and a.source_bindings == b.source_bindings


def test_projection_graph_idempotent_and_inequality_auditable():
    graph, context = narrative_fixture()
    first = normalize_result_surfaces(graph, context).prediction
    second = normalize_result_surfaces(first, context).prediction
    assert first.model_dump_json() == second.model_dump_json()
    result = first.comparison_results[0]
    assert result.raw_value.value == "<0.001"
    assert result.raw_value.raw_value == '["P<0.001"]'
    assert result.p_value.raw_value == "P<0.001" and result.p_value.value == 0.001
    assert result.p_value_comparator.status == "UNRESOLVED"
    assert result.legacy_fields["result_surface"]["raw_fields"]["raw_value"]["value"] == '["P<0.001"]'


def test_conflict_projection_preserves_candidates_and_all_evidence():
    graph, context = fixture()
    c = graph.comparisons[0]
    c.contrast = conflict("Group A vs Group C", "group a vs. group c")
    for eid, quote in [("a", "Group A vs Group C"), ("b", "group a vs. group c")]:
        graph.evidence.append(Evidence(evidence_id=eid, quote=quote, source_type="markdown", source_id=eid,
            targets=[EvidenceTarget(entity_type="Comparison", entity_id=c.comparison_id, field_id="contrast")]))
    original = ArticleExtraction.model_validate_json(graph.model_dump_json())
    projected = normalize_result_surfaces(original, context).prediction
    normalized = projected.comparisons[0]
    assert normalized.contrast.status == "PRESENT"
    assert {"a", "b"} <= set(normalized.contrast.evidence_ids)
    assert normalized.legacy_fields["result_surface"]["raw_fields"]["contrast"] == c.contrast.model_dump(mode="json")
    assert projected.evidence[:len(original.evidence)] == original.evidence
    assert original.comparisons[0].contrast.status == "SOURCE_CONFLICT"


def test_span_and_existing_numeric_disagreement_abstain():
    graph, context = fixture()
    context["tables"][0]["column_map"][5]["source_cells"][0]["colspan"] = 2
    assert bind_comparison_scalar(graph.comparison_results[0], graph, context)["binding_result"] == "AMBIGUOUS"
    graph, context = fixture()
    graph.comparison_results[0].p_value.value = 0.99
    out = normalize_result_surfaces(graph, context)
    assert out.prediction.comparison_results[0].raw_value == graph.comparison_results[0].raw_value
    assert any(b["blockers"] == ["EXISTING_VALUE_AND_SCOPED_SOURCE_DISAGREE"] for b in out.source_bindings)
    graph.arm_results[0].value.value = 90.0
    out = normalize_result_surfaces(graph, context)
    assert out.prediction.arm_results[0].value_kind.value == "other"
