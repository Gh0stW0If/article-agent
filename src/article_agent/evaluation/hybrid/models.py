"""Versioned, separate hybrid contracts. PR5B report types are not extended."""
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class HybridModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticGrade(str, Enum):
    EXACT = "EXACT"
    EQUIVALENT = "EQUIVALENT"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"
    WRONG = "WRONG"


GRADE_SCORES = {
    SemanticGrade.EXACT: 1.0, SemanticGrade.EQUIVALENT: 1.0,
    SemanticGrade.PARTIAL: 0.5, SemanticGrade.ERROR: 0.25, SemanticGrade.WRONG: 0.0,
}


class SemanticJudgment(HybridModel):
    """Wire response deliberately has no writable score."""
    grade: SemanticGrade
    reason: str = Field(min_length=1)
    matched_information: list[str]
    missing_information: list[str]
    incorrect_information: list[str]

    @computed_field
    @property
    def score(self) -> float:
        return GRADE_SCORES[self.grade]


class SemanticEntityJudgment(HybridModel):
    same_entity: bool | None
    decision: Literal["SAME", "DIFFERENT", "AMBIGUOUS"]
    reason: str = Field(min_length=1)
    identity_information: list[str]
    differences: list[str]

    @model_validator(mode="after")
    def consistent(self):
        expected = {"SAME": True, "DIFFERENT": False, "AMBIGUOUS": None}[self.decision]
        if self.same_entity is not expected:
            raise ValueError("same_entity must agree with decision (AMBIGUOUS uses null)")
        return self


class JudgmentArtifact(HybridModel):
    judgment_id: str
    input_sha256: str
    prompt_version: str
    prompt_sha256: str
    model: str
    judge_type: Literal["FIELD", "ENTITY", "RESULT_IDENTITY_FIELD"]
    field_id: str | None = None
    entity_type: str | None = None
    canonical_input: dict[str, Any]
    gold_representation: dict[str, Any]
    prediction_representation: dict[str, Any]
    result: dict[str, Any] | None = None
    status: Literal["SUCCESS", "JUDGE_UNAVAILABLE"]
    error_code: Literal["SEMANTIC_JUDGE_ERROR"] | None = None
    attempts: int = 0
    technical_errors: list[str] = Field(default_factory=list)


class HybridEntityMatchResult(HybridModel):
    entity_type: str
    gold_entity_id: str | None = None
    prediction_entity_id: str | None = None
    match_status: Literal["MATCHED", "MISSING", "EXTRA", "AMBIGUOUS", "SPLIT", "MERGED"]
    match_method: str | None = None
    identity_key: dict[str, Any] = Field(default_factory=dict)
    diagnostic: str | None = None
    semantic_judgment_ids: list[str] = Field(default_factory=list)


class HybridFieldResult(HybridModel):
    target_id: str
    entity_type: str
    gold_entity_id: str
    prediction_entity_id: str | None = None
    field_id: str
    gold_status: str
    prediction_status: str | None = None
    deterministic_classification: str | None
    routed_deterministic_classification: str | None
    hybrid_classification: str | None
    semantic_grade: SemanticGrade | None = None
    semantic_score: float | None = None
    semantic_method: Literal["DETERMINISTIC_EXACT", "LLM"] | None = None
    semantic_judgment_id: str | None = None
    status_match: bool
    value_acceptable: bool | None = None
    evidence_grounded: bool | None = None
    gold_value: Any = None
    prediction_value: Any = None
    evaluation_tier: str
    support_status: str
    in_hard_denominator: bool
    in_value_accuracy_denominator: bool
    additional_failures: list[str] = Field(default_factory=list)


class HybridEvaluationReportV1(HybridModel):
    report_version: Literal["HYBRID_EVALUATION_REPORT/1.0.0"] = "HYBRID_EVALUATION_REPORT/1.0.0"
    article_schema_version: Literal["ARTICLE_EXTRACTION/2.0"] = "ARTICLE_EXTRACTION/2.0"
    gold_version: Literal["GOLD_STANDARD/2.0.0"] = "GOLD_STANDARD/2.0.0"
    article_id: str
    prediction_sha256: str
    gold_sha256: str
    gold_id: str
    base_registry_version: Literal["EVALUATOR_FIELD_REGISTRY/3.0.0"] = "EVALUATOR_FIELD_REGISTRY/3.0.0"
    semantic_registry_version: Literal["HYBRID_SEMANTIC_REGISTRY/1.0.0"] = "HYBRID_SEMANTIC_REGISTRY/1.0.0"
    semantic_judge: dict[str, Any]
    deterministic_reference: dict[str, Any]
    entity_matches: list[HybridEntityMatchResult]
    field_results: list[HybridFieldResult]
    conflict_results: list[dict[str, Any]]
    semantic_judgments: list[JudgmentArtifact]
    metrics: dict[str, Any]
