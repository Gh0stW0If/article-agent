"""Serializable deterministic evaluator results."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComparatorResult(ReportModel):
    matched: bool
    comparator: str
    normalized_gold: Any = None
    normalized_prediction: Any = None
    diagnostic: str | None = None


class EntityMatchResult(ReportModel):
    entity_type: str
    gold_entity_id: str | None = None
    prediction_entity_id: str | None = None
    match_status: Literal["MATCHED", "MISSING", "EXTRA", "AMBIGUOUS", "SPLIT", "MERGED"]
    match_method: str | None = None
    identity_key: dict[str, Any] = Field(default_factory=dict)
    diagnostic: str | None = None


class FieldResult(ReportModel):
    target_id: str
    entity_type: str
    gold_entity_id: str
    prediction_entity_id: str | None = None
    field_id: str
    comparator: str | None
    evaluation_tier: str
    support_status: str
    gold_status: str
    prediction_status: str | None = None
    status_match: bool = False
    value_match: bool | None = None
    evidence_grounded: bool | None = None
    classification: str | None = None
    additional_failures: list[str] = Field(default_factory=list)
    in_hard_denominator: bool = False
    in_value_accuracy_denominator: bool = False
    gold_value: Any = None
    prediction_value: Any = None
    diagnostic: str | None = None


class EvaluationReportV2(ReportModel):
    report_version: Literal["EVALUATION_REPORT/2.0.0"] = "EVALUATION_REPORT/2.0.0"
    article_id: str
    article_schema_version: str = "ARTICLE_EXTRACTION/2.0"
    gold_version: str = "GOLD_STANDARD/2.0.0"
    registry_version: str = "EVALUATOR_FIELD_REGISTRY/3.0.0"
    gold_state: Literal["DRAFT", "FROZEN"]
    entity_matches: list[EntityMatchResult]
    field_results: list[FieldResult]
    entity_failures: list[dict[str, Any]]
    conflict_results: list[dict[str, Any]]
    metrics: dict[str, Any]
    field_failure_counts: dict[str, int]
    entity_failure_counts: dict[str, int]
