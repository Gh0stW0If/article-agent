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
        article=Article(article_id="a1", title="Trial"),
        studies=[Study(study_id="s1", article_id="a1")],
    )

    assert canonical.model_dump(mode="json")["schema_version"] == "ARTICLE_EXTRACTION/1.0"


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
        confidence_interval_lower=5.0,
        confidence_interval_upper=-5.0,
        p_value=722.0,
    )

    assert result.confidence_interval_lower == 5.0
    assert result.confidence_interval_upper == -5.0
    assert result.p_value == 722.0


def test_legacy_adapter_is_non_mutating_and_preserves_results() -> None:
    legacy = legacy_bundle()
    before = legacy.model_dump(mode="json")

    canonical = legacy_bundle_to_canonical(legacy)

    assert legacy.model_dump(mode="json") == before
    assert canonical.source_format == "legacy_extraction_bundle"
    assert canonical.article.title == "Example RCT"
    assert canonical.studies[0].randomized_n == 164
    assert len(canonical.arms) == 2
    assert len(canonical.outcomes) == 1
    assert len(canonical.arm_results) == 2
    assert len(canonical.comparisons) == 1
    assert len(canonical.comparison_results) == 1
    assert canonical.comparison_results[0].estimate == -15.0
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
    assert all(item["jsonPointer"].startswith("/") for item in fields)
