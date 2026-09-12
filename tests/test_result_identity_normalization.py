"""Generic, API-free identity tests. Result measurements never establish identity."""
from copy import deepcopy
from dataclasses import dataclass
import inspect
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.hybrid import FakeSemanticJudge, evaluate_article_hybrid, load_semantic_registry
from article_agent.evaluation.hybrid.models import HybridEntityMatchResult
from article_agent.evaluation.registry import load_registry
from article_agent.result_identity.matcher import candidate_compatibility, link_outcomes, link_results
from article_agent.result_identity.models import ResultIdentityProjection, SourceIdentityContext, SourceRowSemantics
from article_agent.result_identity.normalizers import (
    compare_timepoints, normalize_analysis, normalize_statistic, normalize_timepoint,
)
from article_agent.result_identity.projection import canonicalize_source_outcomes, project_results
from article_agent.result_identity.source_context import (
    cell_shape, context_from_table_blocks, explicit_header_blocks, reporting_statements,
)
from test_hybrid_semantic_evaluator import gold_fixture, prediction_fixture, present, synthetic


def tp(text):
    return normalize_timepoint(text)[0]


@pytest.mark.parametrize("a,b", [
    ("1 month", "1st month"), ("1 month", "the 1 st month"),
    ("1 month", "first month"), ("month 1", "at the first month"),
    ("3 months", "3rd month"), ("3 months", "third month"),
    ("3 months", "3d month"), ("month 3", "3 months"),
    ("7 weeks", "7th week"), ("baseline", "baseline"),
])
def test_timepoint_canonical_exact(a, b):
    assert compare_timepoints(tp(a), tp(b)).status == "EXACT"


@pytest.mark.parametrize("a,b,status", [
    ("3 months", "3 months after surgery", "COMPATIBLE"),
    ("baseline", "before treatment", "COMPATIBLE"),
    ("pre-treatment", "before treatment", "EXACT"),
    ("3 months after surgery", "3 months after operation", "EXACT"),
    ("baseline", "1 month", "CONTRADICTORY"),
    ("1 month", "3 months", "CONTRADICTORY"),
    ("3 months after randomization", "3 months after treatment", "CONTRADICTORY"),
    ("3 months after treatment", "3 months after treatment completion", "CONTRADICTORY"),
    ("1 month", "4 weeks", "CONTRADICTORY"),
    ("early visit", "1 month", "UNKNOWN"),
])
def test_timepoint_compatibility_not_grade(a, b, status):
    assert compare_timepoints(tp(a), tp(b)).status == status


def test_timepoint_raw_anchor_and_conflicts_preserved():
    normalized, events = normalize_timepoint("3d month after surgery")
    assert (normalized.value, normalized.unit, normalized.anchor, normalized.relation) == (3, "month", "surgery", "after")
    assert "TIMEPOINT_ORDINAL_FORMAT_NORMALIZED" in [e.rule for e in events]
    assert normalize_timepoint("1 month", 3, "months")[0].blockers == ["TIMEPOINT_STRUCTURED_TEXT_CONFLICT"]
    assert tp("3 months before surgery").blockers
    assert normalize_timepoint(None, 6, "weeks")[0].value == 6


def source_block(label="Pain", values=("100 ± 2", "200 ± 3"), headers=("Mean (SD)", "Mean (SD)")):
    columns = [{"column_index": 0, "header_path": ["Outcome"],
                "source_cells": [{"row_id": "r", "raw_value": label}]}]
    for i, (value, header) in enumerate(zip(values, headers), 1):
        columns.append({"column_index": i, "arm_label": f"Group {i}", "header_path": [header],
                        "source_cells": [{"row_id": "r", "raw_value": value}]})
    return SimpleNamespace(table_id="T", source_data_row_ids=["r"], column_map=columns)


@pytest.mark.parametrize("block,statements,expected", [
    (source_block(), (), "mean"),
    (source_block(headers=("Group 1", "Group 2")), ("Continuous data were expressed as mean ± standard deviation (SD).",), "mean"),
    (source_block(headers=("Group 1", "Group 2")), (), None),
    (source_block(headers=("Median (SE)", "Median (SE)")), ("Continuous data were expressed as mean ± SD.",), None),
    (source_block(label="Median pain"), ("Continuous data were expressed as mean ± SD.",), None),
    (source_block(values=("100", "200")), (), None),
    (source_block(label="Number of responders (n, %)", values=("21 (60.0)", "29 (85.29)")), (), "event_count"),
    (source_block(label="Number of patients", values=("21 (60.0)", "29 (85.29)")), (), None),
])
def test_statistic_requires_source_structure(block, statements, expected):
    context = context_from_table_blocks([block], statements)
    assert context.rows[0].statistic_kind == expected
    value, events, blockers = normalize_statistic("other", context.rows)
    assert value == (expected or "other")
    assert not blockers
    assert bool(events) == bool(expected)


def test_statistic_conflict_and_number_blind_shapes():
    row = SourceRowSemantics(table_id="T", row_id="r", row_label="Pain", statistic_kind="mean", source_refs=["T:r"])
    assert normalize_statistic("median", [row])[2] == ["STATISTIC_SOURCE_CONFLICT"]
    assert normalize_statistic("other")[0] == "other"
    assert cell_shape("999.1 ± 5") == cell_shape("1.2 ± 333")
    a = context_from_table_blocks([source_block(values=("999.1 ± 5", "1.2 ± 333"))])
    b = context_from_table_blocks([source_block(values=("5.5 ± 2", "77 ± 0.4"))])
    assert a == b
    assert reporting_statements("Quantitative data were expressed as mean ± standard deviation (SD).")


def graph(edit=None):
    g = gold_fixture()
    return prediction_fixture(g, edit)


def projections(edit=None):
    return project_results(graph(edit))


def paired(g, p, parents=None, outcomes=None):
    return link_results(p, g,
        parents if parents is not None else {(x.parent_type, x.parent_id): x.parent_id for x in p},
        outcomes if outcomes is not None else {x.canonical_outcome_id: x.canonical_outcome_id for x in p})


def matched(links):
    return [m for m in links.matches if m["match_status"] == "MATCHED"]


def test_result_projection_preserves_raw_evidence_status_and_roundtrip():
    p = graph(lambda t: t["arm_results"][0].update(timepoint={**present("3d month"), "raw_value": "the 3d month"}))
    raw = p.model_dump_json()
    projected = project_results(p)[0]
    assert projected.raw_timepoint.raw_value == "the 3d month"
    assert projected.raw_timepoint.value == "3d month"
    assert projected.raw_timepoint.status == "PRESENT"
    assert projected.raw_timepoint.evidence_ids
    assert projected.canonical_timepoint.value == 3
    assert ResultIdentityProjection.model_validate_json(projected.model_dump_json()) == projected
    assert p.model_dump_json() == raw
    assert ArticleExtraction.model_validate_json(raw) == p


def test_unknown_comparison_qualifier_does_not_block_unique_identity():
    g = projections(lambda t: t["comparison_results"][0].update(effect_measure={"status": "NOT_REPORTED"}, analysis_set={"status": "UNRESOLVED"}))
    p = projections(lambda t: t["comparison_results"][0].update(effect_measure={"status": "UNRESOLVED"}, analysis_set={"status": "UNRESOLVED"}))
    assert len(matched(paired(g, p))) == 2


@pytest.mark.parametrize("field,value,reason", [
    ("timepoint", "3 months", "TIMEPOINT_CONTRADICTION"),
    ("analysis_set", "PPS", "ANALYSIS_SET_CONTRADICTION"),
    ("value_kind", "median", "STATISTIC_KIND_CONTRADICTION"),
    ("value_kind", "other", "STATISTIC_KIND_AMBIGUOUS"),
])
def test_qualifier_contradictions_and_other_abstain(field, value, reason):
    links = paired(projections(), projections(lambda t: t["arm_results"][0].update({field: present(value)})))
    assert len(matched(links)) == 1
    assert any(reason in a.reason_codes for a in links.audit)


@pytest.mark.parametrize("status", ["SOURCE_CONFLICT", "REVIEW_REQUIRED"])
def test_uncertain_structured_timepoint_does_not_disappear(status):
    field = synthetic.conflict((1, 2)) if status == "SOURCE_CONFLICT" else {"status": status}
    p = projections(lambda t: t["arm_results"][0].update(timepoint_value=field))
    assert "TIMEPOINT_VALUE_SOURCE_UNCERTAINTY" in p[0].identity_blockers
    assert len(matched(paired(projections(), p))) == 1


def test_analysis_populations_remain_distinct():
    assert normalize_analysis("per-protocol")[0] == "PPS"
    assert len({normalize_analysis(x)[0] for x in ("ITT", "FAS", "PPS", "modified ITT")}) == 4


def test_parent_outcome_type_and_derived_isolation():
    g = projections()
    p = projections(lambda t: t["arm_results"][0].update(arm_id=t["arms"][1]["arm_id"]))
    assert len(matched(paired(g, p))) == 1
    assert not matched(paired(g, g, parents={}))
    assert not matched(paired(g, g, outcomes={}))
    p = projections(lambda t: t["arm_results"][0].update(outcome_id=t["outcomes"][1]["outcome_id"]))
    assert len(matched(paired(g, p))) == 1
    p = projections(lambda t: t["arm_results"][0].update(derived=True, derivation="Synthetic computation"))
    assert len(matched(paired(g, p))) == 1
    assert not candidate_compatibility(g[0], g[1], {}, {}).safe


def test_missing_outcome_row_not_blame_unrelated_ambiguous_statistic():
    g = projections()[:1]
    p = [g[0].model_copy(update={"canonical_outcome_id": "unmapped", "canonical_statistic_kind": "event_count"})]
    links = paired(g, p, outcomes={})
    assert not matched(links)
    assert "MISSING_OUTCOME" in next(a for a in links.audit if a.side == "Gold").reason_codes
    # The Outcome itself is mapped, but there is no source result for it.
    links = paired(g, p, outcomes={g[0].canonical_outcome_id: g[0].canonical_outcome_id})
    assert "MISSING_RESULT_IN_PREDICTION" in next(a for a in links.audit if a.side == "Gold").reason_codes


def test_unique_degree_one_no_maximum_matching_or_value_tiebreaker():
    g = projections()[:1]
    p = [g[0], g[0].model_copy(update={"entity_id": "ar-duplicate"})]
    assert not matched(paired(g, p))
    assert all("MULTIPLE_SAFE_CANDIDATES" in a.reason_codes for a in paired(g, p).audit)
    g2 = [g[0], g[0].model_copy(update={"entity_id": "ar-other"})]
    assert not matched(paired(g2, p))


def test_identity_never_uses_result_values_or_statistical_evidence():
    original = graph()
    def alter(t):
        t["arm_results"][0].update(
            value=present(-777), standard_deviation=present(9999), n=present(888),
            dispersion_lower=present(-999), dispersion_upper=present(999),
            change_from_baseline=present(123), event_count=present(2), denominator=present(3),
            raw_value=present("Entirely different numerical representation"),
            legacy_fields={"value": "do not read", "source_observations": [{"value": 400}]})
        t["comparison_results"][0].update(
            estimate=present(888), confidence_interval_lower=present(777),
            confidence_interval_upper=present(999), p_value=present(0.99), raw_value=present("Different CI/P"))
    changed = graph(alter)
    assert project_results(original) == project_results(changed)
    assert paired(project_results(original), project_results(original)) == paired(project_results(original), project_results(changed))
    # Same values with a different timepoint must still contradict.
    p = projections(lambda t: t["arm_results"][0].update(timepoint=present("12 months")))
    assert len(matched(paired(project_results(original), p))) == 1
    assert any("TIMEPOINT_CONTRADICTION" in a.reason_codes for a in paired(project_results(original), p).audit)


def test_identity_input_allowlist_and_no_gold_parameter():
    assert list(inspect.signature(canonicalize_source_outcomes).parameters) == ["graph", "source_context"]
    assert list(inspect.signature(project_results).parameters) == ["graph", "source_context", "outcomes"]
    p = projections()[0]
    for forbidden in ("value", "standard_deviation", "confidence_interval_lower", "p_value", "estimate", "event_count"):
        with pytest.raises(ValidationError):
            ResultIdentityProjection.model_validate({**p.model_dump(), forbidden: 100})
    with pytest.raises(TypeError, match="identity-only"):
        candidate_compatibility(graph().arm_results[0], p, {}, {})


def test_projector_cannot_even_read_result_measurement_attributes():
    g = graph()
    allowed = {
        "arm_result_id", "comparison_result_id", "arm_id", "comparison_id", "outcome_id",
        "timepoint", "timepoint_value", "timepoint_unit", "analysis_set", "value_kind",
        "effect_measure", "derived", "source_table_id", "source_row_id", "legacy_fields",
    }
    class IdentityReadGuard:
        def __init__(self, wrapped):
            self.wrapped = wrapped
        def __getattr__(self, name):
            if name not in allowed:
                raise AssertionError("Forbidden result measurement access: " + name)
            return getattr(self.wrapped, name)
    guarded = SimpleNamespace(
        outcomes=g.outcomes, evidence=g.evidence,
        arm_results=[IdentityReadGuard(r) for r in g.arm_results],
        comparison_results=[IdentityReadGuard(r) for r in g.comparison_results])
    assert project_results(guarded) == project_results(g)


def test_unknown_qualifier_competitor_blocks_otherwise_safe_link():
    g = projections()[:1]
    p = [g[0], g[0].model_copy(update={"entity_id": "unparsed-visit",
        "canonical_timepoint": tp("unclear visit")})]
    links = paired(g, p)
    assert not matched(links)  # cannot discard the unknown visit just to choose the other
    assert any(not c.safe and c.viable for c in links.candidates)


def outcome_graph(names=("Number of responders", "Rate of responders"), *, same_source=True, instrument=None):
    t = graph().model_dump(mode="json")
    for i, (o, name) in enumerate(zip(t["outcomes"], names)):
        o.update(name=present(name), instrument=present(instrument[i]) if instrument else {"status": "UNRESOLVED"})
    synthetic.add_evidence(t)
    for e in t["evidence"]:
        if e["targets"][0]["entity_type"] == "Outcome" and e["targets"][0]["field_id"] == "name":
            e.update(table_id="T", row_id="r" if same_source else e["targets"][0]["entity_id"])
    return ArticleExtraction.model_validate(t)


def test_source_backed_statistic_wrappers_group_not_synonym_similarity():
    p = outcome_graph()
    raw = p.model_dump_json()
    normalized = canonicalize_source_outcomes(p)
    assert len(normalized.groups) == 1
    assert all(o.canonical_concept == "responders" for o in normalized.projections)
    assert p.model_dump_json() == raw
    # Different wording requires explicit source structure, not a clinical dictionary.
    p = outcome_graph(("Number of responders", "Rate of patients responding"))
    assert len(canonicalize_source_outcomes(p).groups) == 2
    context = SourceIdentityContext(rows=[SourceRowSemantics(table_id="T", row_id="r",
        row_label="Number of responders / Rate of patients responding", construct_label="responders",
        measurement_definition="Explicit same response definition", source_refs=["T:r"])])
    assert len(canonicalize_source_outcomes(p, context).groups) == 1


@pytest.mark.parametrize("different", ["source", "instrument", "unit", "uncertain"])
def test_outcome_merge_abstains_on_insufficient_or_conflicting_measurement(different):
    p = outcome_graph(same_source=different != "source",
                      instrument=("VAS", "NRS") if different == "instrument" else None)
    t = p.model_dump(mode="json")
    if different == "unit":
        t["outcomes"][0]["unit"] = present("mm")
        t["outcomes"][1]["unit"] = present("cm")
    if different == "uncertain":
        t["outcomes"][0]["instrument"] = {"status": "REVIEW_REQUIRED"}
    synthetic.add_evidence(t)
    for e in t["evidence"]:
        if e["targets"][0]["entity_type"] == "Outcome" and e["targets"][0]["field_id"] == "name":
            e.update(table_id="T", row_id="r" if different != "source" else e["targets"][0]["entity_id"])
    assert len(canonicalize_source_outcomes(ArticleExtraction.model_validate(t)).groups) == 2


def test_locked_alias_member_not_replaced_or_duplicated():
    p = canonicalize_source_outcomes(outcome_graph())
    g = canonicalize_source_outcomes(outcome_graph(("responders", "different")))
    ids = list(p.canonical_ids)
    locked = HybridEntityMatchResult(entity_type="Outcome", gold_entity_id=ids[0],
        prediction_entity_id=ids[1], match_status="MATCHED", match_method="FROZEN")
    matches, mapping = link_outcomes(p, g, [locked], {p.projections[0].study_id: g.projections[0].study_id})
    successful = [m for m in matches if m["match_status"] == "MATCHED"]
    assert successful == [locked.model_dump(mode="json")]
    assert mapping == {p.canonical_ids[ids[1]]: ids[0]}


def test_duplicate_child_after_outcome_grouping_still_abstains():
    p = outcome_graph()
    t = p.model_dump(mode="json")
    child = deepcopy(t["arm_results"][0])
    child.update(arm_result_id="duplicate", outcome_id=t["outcomes"][1]["outcome_id"])
    t["arm_results"].append(child)
    synthetic.add_evidence(t)
    for e in t["evidence"]:
        if e["targets"][0]["entity_type"] == "Outcome" and e["targets"][0]["field_id"] == "name":
            e.update(table_id="T", row_id="r")
    p = ArticleExtraction.model_validate(t)
    pp = project_results(p)
    assert pp[0].canonical_outcome_id == pp[1].canonical_outcome_id
    assert not [m for m in matched(paired(pp[:1], pp)) if m["entity_type"] == "ArmResult"]


@pytest.mark.parametrize("invalid", ["duplicate", "dangling", "type"])
def test_opt_in_scorer_rejects_invalid_precomputed_match(invalid):
    g = gold_fixture()
    p = g.truth
    m = {"entity_type": "Arm", "gold_entity_id": g.truth.arms[0].arm_id,
         "prediction_entity_id": p.arms[0].arm_id, "match_status": "MATCHED"}
    rows = [m, m] if invalid == "duplicate" else [{**m, "prediction_entity_id": "unknown"}] if invalid == "dangling" else [{**m, "entity_type": "Unknown"}]
    with pytest.raises((ValueError, ValidationError)):
        evaluate_article_hybrid(p, g, load_registry(), load_semantic_registry(),
                                FakeSemanticJudge(lambda _: pytest.fail("No API")), precomputed_matches=rows)


def test_header_adapter_keeps_original_blocks_unchanged():
    @dataclass
    class Block:
        rows: tuple = (("Outcome", "Group 1", "Group 2"), ("Score", "1 ± 2", "3 ± 4"))
        header_rows: tuple = ()
        column_map: tuple = ()
        table_id: str = "table-X"
        source: str = "source"
    b = Block()
    def parse(rows, source):
        assert rows == (b.rows[0],)
        return [{"arm_label": "Group 1"}, {"arm_label": "Group 2"}]
    def attach(columns, rows, ids, source):
        assert ids == ("table-X:r002",)
        return columns
    adapted = explicit_header_blocks([b], parse, attach)[0]
    assert b.column_map == () and b.header_rows == ()
    assert adapted.rows == b.rows and adapted.header_rows == (b.rows[0],)
    assert explicit_header_blocks([b], lambda *_: [], attach)[0] == b
