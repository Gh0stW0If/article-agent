"""Canonical domain entities for medical RCT extraction.

These models deliberately do not replace the existing extraction schemas.
They provide a normalized, reference-checked projection for evaluation,
storage, and future APIs while the legacy ``ExtractionBundle`` remains stable.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Evidence(CanonicalModel):
    evidence_id: str = Field(min_length=1)
    field_paths: list[str] = Field(default_factory=list)
    quote: str = Field(min_length=1)
    source_type: Literal["markdown", "table", "figure", "bibliographic", "other"]
    source_id: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    table_id: str | None = None
    row_id: str | None = None
    figure_id: str | None = None
    cell_refs: list[str] = Field(default_factory=list)
    support_type: Literal["direct", "derived"] = "direct"
    derivation: str | None = None
    legacy_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derived_evidence_has_derivation(self) -> "Evidence":
        if self.support_type == "derived" and not self.derivation:
            raise ValueError("derived evidence requires derivation")
        return self


class Article(CanonicalModel):
    article_id: str = Field(min_length=1)
    title: str | None = None
    doi: str | None = None
    publication_year: int | None = Field(default=None, ge=1600, le=3000)
    journal: str | None = None
    language: str | None = None
    authors: list[str] = Field(default_factory=list)
    correspondence: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Study(CanonicalModel):
    study_id: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    design: str | None = None
    condition: str | None = None
    countries: list[str] = Field(default_factory=list)
    centre_count: int | None = Field(default=None, ge=1)
    randomized_n: int | None = Field(default=None, ge=0)
    analysis_sets: list[str] = Field(default_factory=list)
    arm_ids: list[str] = Field(default_factory=list)
    intervention_ids: list[str] = Field(default_factory=list)
    outcome_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Intervention(CanonicalModel):
    intervention_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    name: str | None = None
    kind: str | None = None
    description: str | None = None
    components: list[str] = Field(default_factory=list)
    frequency_raw: str | None = None
    frequency_value: float | None = Field(default=None, ge=0)
    frequency_unit: str | None = None
    duration_raw: str | None = None
    duration_value: float | None = Field(default=None, ge=0)
    duration_unit: str | None = None
    total_sessions: int | None = Field(default=None, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Arm(CanonicalModel):
    arm_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    label: str | None = None
    role: Literal["intervention", "control", "comparator", "other", "unknown"] = "unknown"
    intervention_ids: list[str] = Field(default_factory=list)
    randomized_n: int | None = Field(default=None, ge=0)
    received_n: int | None = Field(default=None, ge=0)
    analyzed_n: int | None = Field(default=None, ge=0)
    dropout_n: int | None = Field(default=None, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Outcome(CanonicalModel):
    outcome_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    instrument: str | None = None
    role: Literal[
        "primary",
        "secondary",
        "safety",
        "subgroup",
        "sensitivity",
        "baseline",
        "administrative",
        "other",
        "unknown",
    ] = "unknown"
    direction: Literal["higher_better", "lower_better", "neutral", "unknown"] = "unknown"
    unit: str | None = None
    scale_min: float | None = None
    scale_max: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scale_is_ordered(self) -> "Outcome":
        if self.scale_min is not None and self.scale_max is not None and self.scale_min > self.scale_max:
            raise ValueError("scale_min cannot exceed scale_max")
        return self


class ArmResult(CanonicalModel):
    arm_result_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    timepoint_raw: str | None = None
    timepoint_value: float | None = Field(default=None, ge=0)
    timepoint_unit: str | None = None
    analysis_set: str | None = None
    value_kind: Literal["baseline", "endpoint", "change", "event", "count", "other", "unknown"] = "unknown"
    value: float | None = None
    standard_deviation: float | None = Field(default=None, ge=0)
    change_from_baseline: float | None = None
    dispersion_lower: float | None = None
    dispersion_upper: float | None = None
    n: int | None = Field(default=None, ge=0)
    event_count: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    raw_value: str | None = None
    source_table_id: str | None = None
    source_row_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    derived: bool = False
    derivation: str | None = None
    legacy_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derived_result_has_derivation(self) -> "ArmResult":
        if self.derived and not self.derivation:
            raise ValueError("derived arm result requires derivation")
        if self.event_count is not None and self.denominator is not None and self.event_count > self.denominator:
            raise ValueError("event_count cannot exceed denominator")
        return self


class Comparison(CanonicalModel):
    comparison_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    relation: Literal[
        "intervention_vs_control",
        "arm_vs_arm",
        "multi_arm",
        "within_arm",
        "overall",
        "not_applicable",
        "other",
        "unknown",
    ] = "unknown"
    arm_ids: list[str] = Field(default_factory=list)
    intervention_arm_id: str | None = None
    comparator_arm_ids: list[str] = Field(default_factory=list)
    contrast: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class ComparisonResult(CanonicalModel):
    comparison_result_id: str = Field(min_length=1)
    comparison_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    timepoint_raw: str | None = None
    timepoint_value: float | None = Field(default=None, ge=0)
    timepoint_unit: str | None = None
    analysis_set: str | None = None
    effect_measure: str | None = None
    estimate: float | None = None
    confidence_interval_lower: float | None = None
    confidence_interval_upper: float | None = None
    p_value: float | None = None
    p_value_comparator: Literal["=", "<", "<=", ">", ">=", "unknown"] = "unknown"
    raw_value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    derived: bool = False
    derivation: str | None = None
    legacy_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derived_result_has_derivation(self) -> "ComparisonResult":
        # Conflicting or reversed source intervals must remain representable in
        # the canonical layer so an evaluator can flag them without the adapter
        # silently swapping or discarding either bound.
        if self.derived and not self.derivation:
            raise ValueError("derived comparison result requires derivation")
        return self


class ArticleExtraction(CanonicalModel):
    schema_version: Literal["ARTICLE_EXTRACTION/1.0"] = "ARTICLE_EXTRACTION/1.0"
    source_format: Literal["canonical", "legacy_extraction_bundle"] = "canonical"
    source_record_id: str | None = None
    parser_backend: str | None = None
    article: Article
    studies: list[Study] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)
    arms: list[Arm] = Field(default_factory=list)
    outcomes: list[Outcome] = Field(default_factory=list)
    arm_results: list[ArmResult] = Field(default_factory=list)
    comparisons: list[Comparison] = Field(default_factory=list)
    comparison_results: list[ComparisonResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    adapter_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def identifiers_and_references_are_consistent(self) -> "ArticleExtraction":
        collections = {
            "study_id": self.studies,
            "intervention_id": self.interventions,
            "arm_id": self.arms,
            "outcome_id": self.outcomes,
            "arm_result_id": self.arm_results,
            "comparison_id": self.comparisons,
            "comparison_result_id": self.comparison_results,
            "evidence_id": self.evidence,
        }
        identifiers: dict[str, set[str]] = {}
        for attribute, items in collections.items():
            values = [getattr(item, attribute) for item in items]
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {attribute}")
            identifiers[attribute] = set(values)

        study_ids = identifiers["study_id"]
        intervention_ids = identifiers["intervention_id"]
        arm_ids = identifiers["arm_id"]
        outcome_ids = identifiers["outcome_id"]
        comparison_ids = identifiers["comparison_id"]
        evidence_ids = identifiers["evidence_id"]

        for study in self.studies:
            if study.article_id != self.article.article_id:
                raise ValueError(f"study {study.study_id} references a different article")
            self._require_all("study.arm_ids", study.arm_ids, arm_ids)
            self._require_all("study.intervention_ids", study.intervention_ids, intervention_ids)
            self._require_all("study.outcome_ids", study.outcome_ids, outcome_ids)
        for intervention in self.interventions:
            self._require("intervention.study_id", intervention.study_id, study_ids)
        for arm in self.arms:
            self._require("arm.study_id", arm.study_id, study_ids)
            self._require_all("arm.intervention_ids", arm.intervention_ids, intervention_ids)
        for outcome in self.outcomes:
            self._require("outcome.study_id", outcome.study_id, study_ids)
        for result in self.arm_results:
            self._require("arm_result.outcome_id", result.outcome_id, outcome_ids)
            self._require("arm_result.arm_id", result.arm_id, arm_ids)
        for comparison in self.comparisons:
            self._require("comparison.study_id", comparison.study_id, study_ids)
            self._require_all("comparison.arm_ids", comparison.arm_ids, arm_ids)
            if comparison.intervention_arm_id:
                self._require("comparison.intervention_arm_id", comparison.intervention_arm_id, arm_ids)
            self._require_all("comparison.comparator_arm_ids", comparison.comparator_arm_ids, arm_ids)
        for result in self.comparison_results:
            self._require("comparison_result.comparison_id", result.comparison_id, comparison_ids)
            self._require("comparison_result.outcome_id", result.outcome_id, outcome_ids)

        evidence_owners: list[CanonicalModel] = [
            self.article,
            *self.studies,
            *self.interventions,
            *self.arms,
            *self.outcomes,
            *self.arm_results,
            *self.comparisons,
            *self.comparison_results,
        ]
        for owner in evidence_owners:
            self._require_all(
                f"{owner.__class__.__name__}.evidence_ids",
                getattr(owner, "evidence_ids", []),
                evidence_ids,
            )
        return self

    @staticmethod
    def _require(label: str, value: str, available: set[str]) -> None:
        if value not in available:
            raise ValueError(f"{label} references unknown id: {value}")

    @classmethod
    def _require_all(cls, label: str, values: list[str], available: set[str]) -> None:
        for value in values:
            cls._require(label, value, available)
