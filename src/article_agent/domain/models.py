"""Canonical, evidence-bearing domain entities for medical RCT extraction."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FieldStatus(str, Enum):
    PRESENT = "PRESENT"
    NOT_REPORTED = "NOT_REPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    UNRESOLVED = "UNRESOLVED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


T = TypeVar("T")


class ConflictCandidate(CanonicalModel, Generic[T]):
    value: T | None = None
    raw_value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class CanonicalField(CanonicalModel, Generic[T]):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True,
        json_schema_extra={"allOf": [
            {"if": {"properties": {"status": {"const": "PRESENT"}}, "required": ["status"]},
             "then": {"required": ["value"], "properties": {"value": {"not": {"type": "null"}}}}},
            {"if": {"properties": {"status": {"const": "SOURCE_CONFLICT"}}, "required": ["status"]},
             "then": {"required": ["conflict_candidates"], "properties": {
                 "conflict_candidates": {"minItems": 2}, "value": {"type": "null"}}},
             "else": {"properties": {"conflict_candidates": {"maxItems": 0}}}},
        ]},
    )
    status: FieldStatus
    value: T | None = None
    raw_value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    conflict_candidates: list[ConflictCandidate[T]] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_is_structurally_valid(self) -> "CanonicalField[T]":
        if self.status == FieldStatus.PRESENT and self.value is None:
            raise ValueError("PRESENT requires a value")
        if self.status == FieldStatus.SOURCE_CONFLICT:
            if self.value is not None:
                raise ValueError("SOURCE_CONFLICT must not expose a resolved value")
            if len(self.conflict_candidates) < 2:
                raise ValueError("SOURCE_CONFLICT requires at least two candidates")
            distinct_count = len({_candidate_identity(item) for item in self.conflict_candidates})
            if distinct_count < 2:
                raise ValueError("SOURCE_CONFLICT requires at least two distinct candidates")
            if distinct_count != len(self.conflict_candidates):
                raise ValueError("SOURCE_CONFLICT contains duplicate candidates; merge their evidence")
        elif self.conflict_candidates:
            raise ValueError("conflict_candidates are only valid for SOURCE_CONFLICT")
        return self


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _candidate_identity(candidate: ConflictCandidate[Any]) -> str:
    value = candidate.value
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return json.dumps(
        value if value is not None else {"raw_value": candidate.raw_value},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _field_candidate(field: CanonicalField[Any]) -> ConflictCandidate[Any]:
    return ConflictCandidate(
        value=field.value, raw_value=field.raw_value, evidence_ids=field.evidence_ids
    )


def merge_field_observation(
    existing: CanonicalField[T], incoming: CanonicalField[T]
) -> CanonicalField[T]:
    """Merge source observations without silently overwriting disagreement."""

    if existing.status == FieldStatus.SOURCE_CONFLICT or incoming.status == FieldStatus.SOURCE_CONFLICT:
        candidates: list[ConflictCandidate[T]] = []
        for field in (existing, incoming):
            source_candidates = (
                field.conflict_candidates
                if field.status == FieldStatus.SOURCE_CONFLICT
                else ([_field_candidate(field)] if field.status == FieldStatus.PRESENT else [])
            )
            for candidate in source_candidates:
                identity = _candidate_identity(candidate)
                matched = next((item for item in candidates if _candidate_identity(item) == identity), None)
                if matched:
                    matched.evidence_ids = _unique(matched.evidence_ids + candidate.evidence_ids)
                else:
                    candidates.append(ConflictCandidate[T](**candidate.model_dump()))
        if len(candidates) == 1:
            candidate = candidates[0]
            return CanonicalField[T](
                status=FieldStatus.PRESENT,
                value=candidate.value,
                raw_value=candidate.raw_value,
                evidence_ids=candidate.evidence_ids,
            )
        return CanonicalField[T](
            status=FieldStatus.SOURCE_CONFLICT,
            evidence_ids=_unique(existing.evidence_ids + incoming.evidence_ids
                                 + [eid for candidate in candidates for eid in candidate.evidence_ids]),
            conflict_candidates=candidates,
        )

    if existing.status == FieldStatus.PRESENT and incoming.status == FieldStatus.PRESENT:
        if existing.value == incoming.value:
            return CanonicalField[T](
                status=FieldStatus.PRESENT,
                value=existing.value,
                raw_value=existing.raw_value or incoming.raw_value,
                evidence_ids=_unique(existing.evidence_ids + incoming.evidence_ids),
            )
        return CanonicalField[T](
            status=FieldStatus.SOURCE_CONFLICT,
            evidence_ids=_unique(existing.evidence_ids + incoming.evidence_ids),
            conflict_candidates=[_field_candidate(existing), _field_candidate(incoming)],
        )

    if existing.status == FieldStatus.PRESENT:
        return existing.model_copy(deep=True)
    if incoming.status == FieldStatus.PRESENT:
        return incoming.model_copy(deep=True)
    if existing.status == incoming.status:
        return CanonicalField[T](
            status=existing.status,
            value=existing.value if existing.value == incoming.value else None,
            raw_value=existing.raw_value or incoming.raw_value,
            evidence_ids=_unique(existing.evidence_ids + incoming.evidence_ids),
        )
    return CanonicalField[T](
        status=FieldStatus.REVIEW_REQUIRED,
        raw_value=existing.raw_value or incoming.raw_value,
        evidence_ids=_unique(existing.evidence_ids + incoming.evidence_ids),
    )


class EvidenceTarget(CanonicalModel):
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    field_id: str = Field(min_length=1)


class Evidence(CanonicalModel):
    evidence_id: str = Field(min_length=1)
    targets: list[EvidenceTarget] = Field(default_factory=list)
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


def unresolved_field(raw_value: str | None = None) -> CanonicalField[Any]:
    return CanonicalField(status=FieldStatus.UNRESOLVED, raw_value=raw_value)


class Article(CanonicalModel):
    article_id: str = Field(min_length=1)
    title: CanonicalField[str] = Field(default_factory=unresolved_field)
    doi: CanonicalField[str] = Field(default_factory=unresolved_field)
    publication_year: CanonicalField[int] = Field(default_factory=unresolved_field)
    journal: CanonicalField[str] = Field(default_factory=unresolved_field)
    language: CanonicalField[str] = Field(default_factory=unresolved_field)
    authors: CanonicalField[list[str]] = Field(default_factory=unresolved_field)
    correspondence: CanonicalField[list[str]] = Field(default_factory=unresolved_field)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Study(CanonicalModel):
    study_id: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    design: CanonicalField[str] = Field(default_factory=unresolved_field)
    condition: CanonicalField[str] = Field(default_factory=unresolved_field)
    countries: CanonicalField[list[str]] = Field(default_factory=unresolved_field)
    centre_count: CanonicalField[int] = Field(default_factory=unresolved_field)
    randomized_n: CanonicalField[int] = Field(default_factory=unresolved_field)
    random_sequence_method: CanonicalField[str] = Field(default_factory=unresolved_field)
    random_sequence_code: CanonicalField[int] = Field(default_factory=unresolved_field)
    allocation_concealment: CanonicalField[str] = Field(default_factory=unresolved_field)
    allocation_concealment_code: CanonicalField[int] = Field(default_factory=unresolved_field)
    participant_blinding: CanonicalField[str] = Field(default_factory=unresolved_field)
    practitioner_blinding: CanonicalField[str] = Field(default_factory=unresolved_field)
    outcome_assessor_blinding: CanonicalField[str] = Field(default_factory=unresolved_field)
    statistician_blinding: CanonicalField[str] = Field(default_factory=unresolved_field)
    primary_analysis_set: CanonicalField[str] = Field(default_factory=unresolved_field)
    missing_data_method: CanonicalField[str] = Field(default_factory=unresolved_field)
    arm_ids: list[str] = Field(default_factory=list)
    intervention_ids: list[str] = Field(default_factory=list)
    outcome_ids: list[str] = Field(default_factory=list)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Intervention(CanonicalModel):
    intervention_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    name: CanonicalField[str] = Field(default_factory=unresolved_field)
    kind: CanonicalField[str] = Field(default_factory=unresolved_field)
    description: CanonicalField[str] = Field(default_factory=unresolved_field)
    components: CanonicalField[list[str]] = Field(default_factory=unresolved_field)
    frequency_raw: CanonicalField[str] = Field(default_factory=unresolved_field)
    frequency_value: CanonicalField[float] = Field(default_factory=unresolved_field)
    frequency_unit: CanonicalField[str] = Field(default_factory=unresolved_field)
    duration_raw: CanonicalField[str] = Field(default_factory=unresolved_field)
    duration_value: CanonicalField[float] = Field(default_factory=unresolved_field)
    duration_unit: CanonicalField[str] = Field(default_factory=unresolved_field)
    total_sessions: CanonicalField[int] = Field(default_factory=unresolved_field)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Arm(CanonicalModel):
    arm_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    label: CanonicalField[str] = Field(default_factory=unresolved_field)
    role: CanonicalField[str] = Field(default_factory=unresolved_field)
    intervention_ids: list[str] = Field(default_factory=list)
    randomized_n: CanonicalField[int] = Field(default_factory=unresolved_field)
    received_n: CanonicalField[int] = Field(default_factory=unresolved_field)
    analyzed_n: CanonicalField[int] = Field(default_factory=unresolved_field)
    dropout_n: CanonicalField[int] = Field(default_factory=unresolved_field)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class Outcome(CanonicalModel):
    outcome_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    name: CanonicalField[str] = Field(default_factory=unresolved_field)
    instrument: CanonicalField[str] = Field(default_factory=unresolved_field)
    role: CanonicalField[str] = Field(default_factory=unresolved_field)
    direction: CanonicalField[str] = Field(default_factory=unresolved_field)
    unit: CanonicalField[str] = Field(default_factory=unresolved_field)
    scale_min: CanonicalField[float] = Field(default_factory=unresolved_field)
    scale_max: CanonicalField[float] = Field(default_factory=unresolved_field)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class ArmResult(CanonicalModel):
    arm_result_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    timepoint: CanonicalField[str] = Field(default_factory=unresolved_field)
    timepoint_value: CanonicalField[float] = Field(default_factory=unresolved_field)
    timepoint_unit: CanonicalField[str] = Field(default_factory=unresolved_field)
    analysis_set: CanonicalField[str] = Field(default_factory=unresolved_field)
    value_kind: CanonicalField[str] = Field(default_factory=unresolved_field)
    value: CanonicalField[float] = Field(default_factory=unresolved_field)
    standard_deviation: CanonicalField[float] = Field(default_factory=unresolved_field)
    change_from_baseline: CanonicalField[float] = Field(default_factory=unresolved_field)
    dispersion_lower: CanonicalField[float] = Field(default_factory=unresolved_field)
    dispersion_upper: CanonicalField[float] = Field(default_factory=unresolved_field)
    n: CanonicalField[int] = Field(default_factory=unresolved_field)
    event_count: CanonicalField[int] = Field(default_factory=unresolved_field)
    denominator: CanonicalField[int] = Field(default_factory=unresolved_field)
    raw_value: CanonicalField[str] = Field(default_factory=unresolved_field)
    source_table_id: str | None = None
    source_row_id: str | None = None
    derived: bool = False
    derivation: str | None = None
    legacy_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derived_result_has_derivation(self) -> "ArmResult":
        if self.derived and not self.derivation:
            raise ValueError("derived arm result requires derivation")
        if (
            self.event_count.status == FieldStatus.PRESENT
            and self.denominator.status == FieldStatus.PRESENT
            and self.event_count.value is not None
            and self.denominator.value is not None
            and self.event_count.value > self.denominator.value
        ):
            raise ValueError("event_count cannot exceed denominator")
        return self


class Comparison(CanonicalModel):
    comparison_id: str = Field(min_length=1)
    study_id: str = Field(min_length=1)
    relation: CanonicalField[str] = Field(default_factory=unresolved_field)
    arm_ids: list[str] = Field(default_factory=list)
    intervention_arm_id: str | None = None
    comparator_arm_ids: list[str] = Field(default_factory=list)
    contrast: CanonicalField[str] = Field(default_factory=unresolved_field)
    legacy_fields: dict[str, Any] = Field(default_factory=dict)


class ComparisonResult(CanonicalModel):
    comparison_result_id: str = Field(min_length=1)
    comparison_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    timepoint: CanonicalField[str] = Field(default_factory=unresolved_field)
    timepoint_value: CanonicalField[float] = Field(default_factory=unresolved_field)
    timepoint_unit: CanonicalField[str] = Field(default_factory=unresolved_field)
    analysis_set: CanonicalField[str] = Field(default_factory=unresolved_field)
    effect_measure: CanonicalField[str] = Field(default_factory=unresolved_field)
    estimate: CanonicalField[float] = Field(default_factory=unresolved_field)
    confidence_interval_lower: CanonicalField[float] = Field(default_factory=unresolved_field)
    confidence_interval_upper: CanonicalField[float] = Field(default_factory=unresolved_field)
    p_value: CanonicalField[float] = Field(default_factory=unresolved_field)
    p_value_comparator: CanonicalField[str] = Field(default_factory=unresolved_field)
    raw_value: CanonicalField[str] = Field(default_factory=unresolved_field)
    derived: bool = False
    derivation: str | None = None
    legacy_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derived_result_has_derivation(self) -> "ComparisonResult":
        if self.derived and not self.derivation:
            raise ValueError("derived comparison result requires derivation")
        return self


class ArticleExtraction(CanonicalModel):
    schema_version: Literal["ARTICLE_EXTRACTION/2.0"] = "ARTICLE_EXTRACTION/2.0"
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
        entity_groups: list[tuple[str, str, list[CanonicalModel]]] = [
            ("Article", "article_id", [self.article]),
            ("Study", "study_id", list(self.studies)),
            ("Intervention", "intervention_id", list(self.interventions)),
            ("Arm", "arm_id", list(self.arms)),
            ("Outcome", "outcome_id", list(self.outcomes)),
            ("ArmResult", "arm_result_id", list(self.arm_results)),
            ("Comparison", "comparison_id", list(self.comparisons)),
            ("ComparisonResult", "comparison_result_id", list(self.comparison_results)),
        ]
        by_type: dict[str, dict[str, CanonicalModel]] = {}
        for entity_type, id_field, items in entity_groups:
            ids = [getattr(item, id_field) for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {id_field}")
            by_type[entity_type] = dict(zip(ids, items, strict=True))

        study_ids = set(by_type["Study"])
        intervention_ids = set(by_type["Intervention"])
        arm_ids = set(by_type["Arm"])
        outcome_ids = set(by_type["Outcome"])
        comparison_ids = set(by_type["Comparison"])
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("duplicate evidence_id")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}

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

        for entity_type, _, items in entity_groups:
            for entity in items:
                for field_id, field_value in entity:
                    if isinstance(field_value, CanonicalField):
                        self._require_all(
                            f"{entity_type}.{field_id}.evidence_ids",
                            field_value.evidence_ids,
                            evidence_ids,
                        )
                        for candidate in field_value.conflict_candidates:
                            self._require_all(
                                f"{entity_type}.{field_id}.conflict_candidates.evidence_ids",
                                candidate.evidence_ids,
                                evidence_ids,
                            )

        for item in self.evidence:
            for target in item.targets:
                entity = by_type.get(target.entity_type, {}).get(target.entity_id)
                if entity is None:
                    raise ValueError(
                        f"evidence target references unknown entity: {target.entity_type}/{target.entity_id}"
                    )
                if target.field_id not in type(entity).model_fields:
                    raise ValueError(f"evidence target references unknown field: {target.field_id}")
                if not isinstance(getattr(entity, target.field_id), CanonicalField):
                    raise ValueError(f"evidence target field is not canonical: {target.field_id}")
                field = getattr(entity, target.field_id)
                linked_ids = field.evidence_ids + [eid for candidate in field.conflict_candidates for eid in candidate.evidence_ids]
                if item.evidence_id not in linked_ids:
                    raise ValueError("evidence target is not reciprocated by CanonicalField.evidence_ids")

        for entity_type, id_field, items in entity_groups:
            for entity in items:
                entity_id = getattr(entity, id_field)
                for field_name, field in entity:
                    if not isinstance(field, CanonicalField):
                        continue
                    linked_evidence_ids = field.evidence_ids + [
                        eid for candidate in field.conflict_candidates
                        for eid in candidate.evidence_ids
                    ]
                    expected_target = EvidenceTarget(
                        entity_type=entity_type, entity_id=entity_id, field_id=field_name,
                    )
                    for evidence_id in set(linked_evidence_ids):
                        if expected_target not in evidence_by_id[evidence_id].targets:
                            raise ValueError(
                                f"{entity_type}.{field_name} evidence {evidence_id} "
                                "does not contain reciprocal EvidenceTarget"
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
