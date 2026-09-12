"""Internal identity-only projections; no clinical result values are accepted."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class IdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RawIdentityField(IdentityModel):
    status: str
    value: str | float | None = None
    raw_value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class NormalizationEvent(IdentityModel):
    field: str
    rule: str
    explanation: str
    source_refs: list[str] = Field(default_factory=list)
    deterministic: bool = True


class TimepointIdentity(IdentityModel):
    kind: Literal["baseline", "follow_up", "unknown"] = "unknown"
    value: float | None = None
    unit: str | None = None
    anchor: str | None = None
    relation: str | None = None
    blockers: list[str] = Field(default_factory=list)


class SourceRowSemantics(IdentityModel):
    table_id: str
    row_id: str
    row_label: str
    statistic_kind: str | None = None
    construct_label: str | None = None
    measurement_definition: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)


class SourceIdentityContext(IdentityModel):
    rows: list[SourceRowSemantics] = Field(default_factory=list)
    reporting_statements: list[str] = Field(default_factory=list)
    source_document_sha256: str | None = None


class OutcomeIdentityProjection(IdentityModel):
    outcome_id: str
    study_id: str
    raw_name: RawIdentityField
    canonical_concept: str | None = None
    statistic_wrapper: str | None = None
    instrument: str | None = None
    unit: str | None = None
    definition: str | None = None
    source_blocks: list[str] = Field(default_factory=list)
    normalization_events: list[NormalizationEvent] = Field(default_factory=list)
    identity_blockers: list[str] = Field(default_factory=list)


class OutcomeNormalization(IdentityModel):
    projections: list[OutcomeIdentityProjection]
    canonical_ids: dict[str, str]
    groups: dict[str, list[str]]
    decisions: list[dict] = Field(default_factory=list)


class ResultIdentityProjection(IdentityModel):
    entity_type: Literal["ArmResult", "ComparisonResult"]
    entity_id: str
    parent_type: Literal["Arm", "Comparison"]
    parent_id: str
    raw_outcome_id: str
    canonical_outcome_id: str
    raw_timepoint: RawIdentityField
    raw_timepoint_value: RawIdentityField
    raw_timepoint_unit: RawIdentityField
    canonical_timepoint: TimepointIdentity
    raw_analysis_set: RawIdentityField
    canonical_analysis_set: str | None = None
    raw_statistic_kind: RawIdentityField
    canonical_statistic_kind: str | None = None
    derived: bool
    source_refs: list[str] = Field(default_factory=list)
    normalization_events: list[NormalizationEvent] = Field(default_factory=list)
    identity_blockers: list[str] = Field(default_factory=list)


class Compatibility(IdentityModel):
    status: Literal["EXACT", "COMPATIBLE", "UNKNOWN", "CONTRADICTORY"]
    reason: str


class CandidateDecision(IdentityModel):
    entity_type: str
    gold_id: str
    prediction_id: str
    dimensions: dict[str, Compatibility]
    viable: bool
    safe: bool


class ResultLinkAudit(IdentityModel):
    entity_type: str
    side: Literal["Gold", "Prediction"]
    entity_id: str
    before_status: str
    after_status: str
    before_candidates: list[str]
    after_candidates: list[str]
    selected_pair: dict[str, str] | None = None
    reason_codes: list[str]
    candidate_decisions: list[CandidateDecision]


class ResultLinking(IdentityModel):
    matches: list[dict]
    candidates: list[CandidateDecision]
    audit: list[ResultLinkAudit]
