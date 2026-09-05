from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
MINERU_ROOT = ROOT / "MinerU method"
if str(MINERU_ROOT) not in sys.path:
    sys.path.insert(0, str(MINERU_ROOT))

from article_agent.domain import Article, ArticleExtraction, ComparisonResult, Study, legacy_bundle_to_canonical
from article_agent.domain import (
    Arm, ArmResult, CanonicalField, ConflictCandidate, Evidence, EvidenceTarget,
    FieldStatus, Intervention, Outcome, Comparison, merge_field_observation,
)
from mineru_method.schemas import (
    AcupunctureProtocol,
    ConsortFlowExtraction,
    EvidenceQuote,
    ExtractionBundle,
    MetadataExtraction,
    OutcomeArm,
    OutcomeComparison,
    OutcomeExtraction,
    OutcomeStatistic,
    RiskOfBiasExtraction,
)


def legacy_bundle() -> ExtractionBundle:
    return ExtractionBundle(
        article_id="2015-01",
        parser_backend="mineru",
        metadata=MetadataExtraction(
            title="Example RCT",
            publication_year=2015,
            journal="Example Journal",
            first_author="Example Author",
            country="Spain",
            intervention="Acupuncture",
            control="Sham acupuncture",
            evidence=[
                EvidenceQuote(
                    field_id="title",
                    quote="Example RCT",
                    source="markdown",
                )
            ],
        ),
        acupuncture=AcupunctureProtocol(
            treatment_frequency_raw="once weekly",
            treatment_frequency_value=1,
            treatment_frequency_unit=2,
            total_sessions=9,
        ),
        risk_of_bias=RiskOfBiasExtraction(
            randomized_sample_intervention_raw=82,
            randomized_sample_control_raw=82,
            total_randomized=164,
        ),
        outcomes=OutcomeExtraction(
            outcomes=[
                OutcomeStatistic(
                    table_id="table-2",
                    row_id="table-2:r001",
                    outcome_name="Pain intensity",
                    measurement_instrument="VAS",
                    outcome_observation_timepoint_raw="post-treatment",
                    statistic_type="continuous",
                    arm=[
                        OutcomeArm(
                            arm_id="acupuncture",
                            arm_label="Acupuncture",
                            role="intervention",
                            n=82,
                            value=25.0,
                            sd=10.0,
                        ),
                        OutcomeArm(
                            arm_id="sham",
                            arm_label="Sham acupuncture",
                            role="control",
                            n=82,
                            value=40.0,
                            sd=12.0,
                        ),
                    ],
                    comparison=OutcomeComparison(
                        relation="intervention_vs_control",
                        intervention_arm_id="acupuncture",
                        control_arm_id="sham",
                        comparator_arm_ids=["sham"],
                        contrast="Acupuncture vs sham",
                    ),
                    analysis_set="ITT",
                    record_role="primary",
                    between_group_measure="MD",
                    outcome_between_group_estimate=-15.0,
                    outcome_between_group_lower=-18.0,
                    outcome_between_group_upper=-12.0,
                    outcome_p_value=0.001,
                    outcome_p_value_comparator="=",
                    source_values=["25.0 (10.0)", "40.0 (12.0)", "MD -15.0"],
                    source_evidence="Pain VAS was 25.0 versus 40.0 after treatment.",
                )
            ]
        ),
        consort_flow=ConsortFlowExtraction(randomized_n=164),
    )


def test_minimal_canonical_model_serializes() -> None:
    canonical = ArticleExtraction(
        article=Article(article_id="a1", title=present("Trial")),
        studies=[Study(study_id="s1", article_id="a1")],
    )

    assert canonical.model_dump(mode="json")["schema_version"] == "ARTICLE_EXTRACTION/2.0"


def test_canonical_model_rejects_dangling_references() -> None:
    with pytest.raises(ValidationError, match="unknown id"):
        ArticleExtraction(
            article=Article(article_id="a1"),
            studies=[Study(study_id="s1", article_id="a1", arm_ids=["missing-arm"])],
        )


def test_source_conflicts_remain_representable_for_evaluation() -> None:
    result = ComparisonResult(
        comparison_result_id="cr1",
        comparison_id="c1",
        outcome_id="o1",
        confidence_interval_lower=present(5.0),
        confidence_interval_upper=present(-5.0),
        p_value=present(722.0),
    )

    assert result.confidence_interval_lower.value == 5.0
    assert result.confidence_interval_upper.value == -5.0
    assert result.p_value.value == 722.0


def test_legacy_adapter_is_non_mutating_and_preserves_results() -> None:
    legacy = legacy_bundle()
    before = legacy.model_dump(mode="json")

    canonical = legacy_bundle_to_canonical(legacy)

    assert legacy.model_dump(mode="json") == before
    assert canonical.source_format == "legacy_extraction_bundle"
    assert canonical.article.title.value == "Example RCT"
    assert canonical.studies[0].randomized_n.value == 164
    assert len(canonical.arms) == 2
    assert len(canonical.outcomes) == 1
    assert len(canonical.arm_results) == 2
    assert len(canonical.comparisons) == 1
    assert len(canonical.comparison_results) == 1
    assert canonical.comparison_results[0].estimate.value == -15.0
    assert canonical.evidence


def test_published_json_schema_matches_model() -> None:
    expected = ArticleExtraction.model_json_schema()
    published = json.loads((ROOT / "schemas/article-extraction.schema.json").read_text(encoding="utf-8"))
    assert published == expected


def test_evaluator_field_registry_has_unique_fields_and_known_entities() -> None:
    registry = json.loads(
        (ROOT / "registry/evaluator-field-registry.json").read_text(encoding="utf-8")
    )
    fields = registry["fields"]
    field_ids = [item["fieldId"] for item in fields]
    assert len(field_ids) == len(set(field_ids))
    assert {item["entity"] for item in fields} <= {
        "Article", "Study", "Arm", "Intervention", "Outcome",
        "ArmResult", "Comparison", "ComparisonResult", "Evidence",
    }
    assert all(item["pathPattern"].startswith("$.") and "jsonPointer" not in item for item in fields)
    assert registry["canonicalSchemaVersion"] == "ARTICLE_EXTRACTION/2.0"
    assert registry["schemaVersion"] == "2.0.0"
    assert all({"enabled", "tier", "comparator"} <= item["evaluation"].keys() for item in fields)
    assert all("allowed" in item["sourceConflict"] for item in fields)
    models = {cls.__name__: cls for cls in (Article, Study, Arm, Intervention, Outcome, ArmResult, Comparison, ComparisonResult, Evidence)}
    for item in fields:
        name = item["pathPattern"].rsplit(".", 1)[1]
        assert name in models[item["entity"]].model_fields
    for cls in (Article, Study, Arm, Intervention, Outcome, ArmResult, Comparison, ComparisonResult):
        for name, field in cls.model_fields.items():
            if isinstance(field.annotation, type) and issubclass(field.annotation, CanonicalField):
                assert any(item["entity"] == cls.__name__ and item["pathPattern"].endswith("." + name) for item in fields)


def present(value, eid=None, raw=None):
    return CanonicalField(status=FieldStatus.PRESENT, value=value,
                          raw_value=str(value) if raw is None else raw,
                          evidence_ids=[eid] if eid else [])


def test_present_serializes_normalized_raw_and_evidence():
    field = CanonicalField[int](status="PRESENT", value=38, raw_value="n=38", evidence_ids=["E1"])
    assert json.loads(field.model_dump_json()) == {
        "status": "PRESENT", "value": 38, "raw_value": "n=38", "evidence_ids": ["E1"], "conflict_candidates": [],
    }


@pytest.mark.parametrize("status", ["NOT_REPORTED", "NOT_APPLICABLE", "INSUFFICIENT_CONTEXT", "UNRESOLVED", "REVIEW_REQUIRED"])
def test_missing_status_allows_null(status):
    assert CanonicalField[int](status=status).value is None


def test_present_requires_normalized_value():
    with pytest.raises(ValidationError, match="PRESENT requires"):
        CanonicalField[int](status="PRESENT")


@pytest.mark.parametrize("candidates", [[], [{"value": 38}], [{"value": 38}, {"value": 38, "raw_value": "n=38"}]])
def test_source_conflict_requires_two_distinct_candidates(candidates):
    with pytest.raises(ValidationError, match="at least two"):
        CanonicalField[int](status="SOURCE_CONFLICT", conflict_candidates=candidates)


def test_unresolved_plus_present():
    result = merge_field_observation(CanonicalField[int](status="UNRESOLVED", raw_value="NR"), present(38, "E1"))
    assert result.status == FieldStatus.PRESENT
    assert result.value == 38


def test_equal_observations_merge_evidence_without_mutation():
    first, second = present(38, "E1"), present(38, "E2", "n=38")
    before = first.model_dump()
    merged = merge_field_observation(first, second)
    assert merged.status == FieldStatus.PRESENT
    assert merged.value == 38 and merged.evidence_ids == ["E1", "E2"]
    assert first.model_dump() == before


def test_conflict_serializes_both_values():
    conflict = merge_field_observation(present(38, "E1", "n=38"), present(34, "E2", "n=34"))
    assert json.loads(conflict.model_dump_json()) == {
        "status": "SOURCE_CONFLICT", "value": None, "raw_value": None, "evidence_ids": ["E1", "E2"],
        "conflict_candidates": [
            {"value": 38, "raw_value": "n=38", "evidence_ids": ["E1"]},
            {"value": 34, "raw_value": "n=34", "evidence_ids": ["E2"]},
        ],
    }


def test_repeated_value_in_conflict_merges_evidence_even_if_raw_differs():
    first = merge_field_observation(present(38, "E1", "n=38"), present(34, "E2"))
    before = first.model_dump()
    merged = merge_field_observation(first, present(38, "E3", "38 participants"))
    assert len(merged.conflict_candidates) == 2
    assert merged.conflict_candidates[0].evidence_ids == ["E1", "E3"]
    assert first.model_dump() == before
    again = merge_field_observation(present(34, "E4"), merged)
    assert len(again.conflict_candidates) == 2
    assert next(c for c in again.conflict_candidates if c.value == 34).evidence_ids == ["E4", "E2"]


def test_adapter_maps_methods_and_treats_nr_as_unresolved():
    source = legacy_bundle().model_dump(mode="json")
    source["risk_of_bias"].update(random_sequence_method="Computer generated", random_sequence_class=1,
        allocation_concealment="Opaque envelopes", allocation_concealment_class=1,
        participant_blinding=1, outcome_assessor_blinding=2, primary_analysis=1, missing_data_method=5)
    study = legacy_bundle_to_canonical(source).studies[0]
    assert study.random_sequence_method.value == "Computer generated"
    assert study.random_sequence_code.value == 1
    assert study.allocation_concealment.value == "Opaque envelopes"
    assert study.allocation_concealment_code.value == 1
    assert study.participant_blinding.value == "YES"
    assert study.outcome_assessor_blinding.value == "NO"
    assert study.primary_analysis_set.value == "ITT_OR_MITT"
    assert study.missing_data_method.value == "REGRESSION"
    defaults = legacy_bundle_to_canonical(legacy_bundle()).studies[0]
    for name in ("random_sequence_method", "random_sequence_code", "allocation_concealment", "allocation_concealment_code",
                 "participant_blinding", "outcome_assessor_blinding", "practitioner_blinding", "statistician_blinding",
                 "primary_analysis_set", "missing_data_method"):
        assert getattr(defaults, name).status == FieldStatus.UNRESOLVED
    assert defaults.random_sequence_method.raw_value == "NR"


def test_adapter_merges_study_and_arm_count_conflicts_and_preserves_mapping():
    from copy import deepcopy
    source = {
        "article_id": "synthetic", "metadata": {"intervention": "A"},
        "risk_of_bias": {"total_randomized": 38, "randomized_sample_intervention_raw": 38,
            "evidence": [{"field_id": "total_randomized", "quote": "38 randomized", "source": "markdown"}]},
        "consort_flow": {"randomized_n": 34, "arms": [{"arm_name": "A", "randomized_n": 34,
            "evidence": [{"field_id": "randomized_n", "quote": "A: n=34", "source": "figure"}]}],
            "evidence": [{"field_id": "randomized_n", "quote": "34 randomized", "source": "figure"}]},
    }
    before = deepcopy(source)
    result = legacy_bundle_to_canonical(source)
    assert source == before
    assert result.studies[0].randomized_n.status == FieldStatus.SOURCE_CONFLICT
    assert {c.value for c in result.studies[0].randomized_n.conflict_candidates} == {38, 34}
    assert len(result.arms) == 1
    assert result.arms[0].randomized_n.status == FieldStatus.SOURCE_CONFLICT
    assert all(c.evidence_ids for c in result.studies[0].randomized_n.conflict_candidates)


def test_repeated_arm_alias_merges_label_observations():
    source = legacy_bundle().model_dump(mode="json")
    from copy import deepcopy
    extra = deepcopy(source["outcomes"]["outcomes"][0])
    extra["arm"][0]["arm_label"] = "Another source label"
    extra["arm"][0]["n"] = 34
    source["outcomes"]["outcomes"].append(extra)
    result = legacy_bundle_to_canonical(source)
    assert len(result.arms) == 2
    assert result.arms[0].label.status == FieldStatus.SOURCE_CONFLICT
    assert result.arms[0].randomized_n.value == 82
    assert result.arm_results[2].n.value == 34


def test_field_evidence_targets_are_specific_and_reciprocal():
    result = legacy_bundle_to_canonical(legacy_bundle())
    evidence = {e.evidence_id: e for e in result.evidence}
    title = result.article.title
    assert title.evidence_ids
    assert not result.article.journal.evidence_ids
    assert evidence[title.evidence_ids[0]].targets == [
        EvidenceTarget(entity_type="Article", entity_id="2015-01", field_id="title")]
    row_evidence = result.arm_results[0].value.evidence_ids
    assert row_evidence
    assert any(t.entity_type == "ArmResult" and t.field_id == "value" for t in evidence[row_evidence[0]].targets)


@pytest.mark.parametrize("candidate_only", [False, True])
def test_dangling_field_and_candidate_evidence_rejected(candidate_only):
    field = present("Trial", "missing-evidence")
    if candidate_only:
        field = CanonicalField[str](status="SOURCE_CONFLICT", conflict_candidates=[
            ConflictCandidate(value="Trial", evidence_ids=["missing-evidence"]), ConflictCandidate(value="Other")])
    with pytest.raises(ValidationError, match="unknown id"):
        ArticleExtraction(article=Article(article_id="a1", title=field))


@pytest.mark.parametrize("target", [
    {"entity_type": "Article", "entity_id": "missing", "field_id": "title"},
    {"entity_type": "NoEntity", "entity_id": "a1", "field_id": "title"},
    {"entity_type": "Article", "entity_id": "a1", "field_id": "missing"},
    {"entity_type": "Article", "entity_id": "a1", "field_id": "article_id"},
])
def test_invalid_evidence_targets_rejected(target):
    with pytest.raises(ValidationError, match="evidence target"):
        ArticleExtraction(article=Article(article_id="a1", title=present("Trial", "E1")), evidence=[
            Evidence(evidence_id="E1", quote="Trial", source_id="source", source_type="markdown", targets=[target])])


def test_adapter_keeps_zero_and_invalid_raw_counts():
    result = legacy_bundle_to_canonical({"article_id": "a1", "risk_of_bias": {"total_randomized": 0},
                                       "consort_flow": {"randomized_n": "3.5"}})
    assert result.studies[0].randomized_n.value == 0
    assert result.studies[0].legacy_fields["consort_flow"]["randomized_n"] == "3.5"


def test_adapter_preserves_nonstandard_bibliographic_source():
    result = legacy_bundle_to_canonical({"article_id": "a", "metadata": {
        "title": "Trial", "evidence": [{"field_id": "title", "quote": "Trial", "source": "PubMed PMID 123"}]}})
    assert result.evidence[0].source_type == "other"
    assert result.evidence[0].legacy_fields["source"] == "PubMed PMID 123"
    assert result.article.title.evidence_ids == [result.evidence[0].evidence_id]


def test_conflict_candidate_only_evidence_can_have_explicit_target():
    title = CanonicalField[str](status="SOURCE_CONFLICT", conflict_candidates=[
        {"value": "Trial", "evidence_ids": ["E1"]}, {"value": "Other", "evidence_ids": ["E2"]}])
    canonical = ArticleExtraction(article=Article(article_id="a", title=title), evidence=[
        Evidence(evidence_id=eid, quote=quote, source_type="markdown", source_id="s", targets=[
            EvidenceTarget(entity_type="Article", entity_id="a", field_id="title")])
        for eid, quote in [("E1", "Trial"), ("E2", "Other")]])
    assert len(canonical.article.title.conflict_candidates) == 2


def test_numeric_conflict_candidate_matches_int_and_float():
    conflict = merge_field_observation(present(38, "E1"), present(34, "E2"))
    result = merge_field_observation(conflict, present(38.0, "E3"))
    assert len(result.conflict_candidates) == 2
    assert result.conflict_candidates[0].evidence_ids == ["E1", "E3"]


def test_json_schema_exposes_status_constraints():
    constraints = CanonicalField[int].model_json_schema()["allOf"]
    assert constraints[0]["then"]["required"] == ["value"]
    assert constraints[1]["then"]["properties"]["conflict_candidates"]["minItems"] == 2


@pytest.mark.parametrize("candidate_only", [False, True])
def test_field_evidence_requires_reciprocal_target(candidate_only):
    title = present("Trial", "E1")
    if candidate_only:
        title = CanonicalField[str](status="SOURCE_CONFLICT", conflict_candidates=[
            {"value": "Trial", "evidence_ids": ["E1"]}, {"value": "Other"},
        ])
    with pytest.raises(ValidationError, match="Article.title evidence E1 does not contain reciprocal EvidenceTarget"):
        ArticleExtraction(
            article=Article(article_id="a1", title=title),
            evidence=[Evidence(evidence_id="E1", quote="Trial", source_type="markdown",
                               source_id="source", targets=[])],
        )


def test_shared_evidence_requires_target_for_every_linking_field():
    article = Article(article_id="a1", title=present("Trial", "E1"), journal=present("Journal", "E1"))
    evidence = Evidence(evidence_id="E1", quote="Trial, Journal", source_type="markdown", source_id="source",
                        targets=[EvidenceTarget(entity_type="Article", entity_id="a1", field_id="title")])
    with pytest.raises(ValidationError, match="Article.journal evidence E1 does not contain reciprocal EvidenceTarget"):
        ArticleExtraction(article=article, evidence=[evidence])
    evidence.targets.append(EvidenceTarget(entity_type="Article", entity_id="a1", field_id="journal"))
    ArticleExtraction(article=article, evidence=[evidence])
