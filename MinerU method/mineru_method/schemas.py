from __future__ import annotations

from enum import Enum, IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TableClassification(StrictModel):
    """Semantic classification returned by the table-routing LLM.

    This is deliberately separate from :class:`OutcomeStatistic`: table
    routing must finish before row-wise outcome extraction starts, and the
    classification response should not be able to populate any Excel-facing
    outcome value.  ``unknown`` is reserved for a genuinely insufficient
    table context or a failed/invalid classifier response.
    """

    table_category: Literal[
        "outcome", "safety", "subgroup", "sensitivity", "baseline", "flow", "other", "unknown"
    ] = "unknown"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str = "NR"


class YesNoNR(IntEnum):
    YES = 1
    NO = 2
    NOT_REPORTED = 3


class DeqiType(IntEnum):
    YES = 1
    NO = 2
    NOT_REPORTED = 3
    NOT_APPLICABLE = 4


class ShamType(IntEnum):
    PENETRATING_NEEDLE = 1
    NON_PENETRATING_NEEDLE = 2
    NON_NEEDLE = 3
    HIGH_INTENSITY_NO_SHAM = 4
    USUAL_CARE_NO_SHAM = 5
    LOW_INTENSITY_NO_SHAM = 6


class MissingDataMethod(IntEnum):
    COMPLETE_CASE = 1
    ALL_AVAILABLE = 2
    MEAN_IMPUTATION = 3
    LOCF = 4
    REGRESSION = 5
    MULTIPLE_IMPUTATION = 6
    MAXIMUM_LIKELIHOOD = 7
    WEIGHTING = 8
    COMBINATION = 9
    MIXED_EFFECT_MODEL = 10
    OTHER = 11
    NO_MISSING_DATA = 12
    NOT_REPORTED = 13


class PrimaryAnalysis(IntEnum):
    ITT_OR_MITT = 1
    AVAILABLE_CASE = 2
    PER_PROTOCOL = 3
    NOT_REPORTED = 4


class EvidenceQuote(StrictModel):
    field_id: str = Field(description="被此证据支持的 canonicalFieldId")
    quote: str = Field(min_length=1, description="输入上下文中的逐字短引文")
    page: int | None = Field(default=None, ge=1)
    source: Literal["markdown", "table", "figure", "crossref"]
    support_type: Literal["direct", "derived"] = Field(
        default="direct",
        description="direct=引文直接报告该值；derived=由引文中的全部前提唯一推导",
    )
    derivation: str | None = Field(
        default=None,
        description="仅用于derived；写明可复算的公式、单位转换或唯一映射",
    )


class MetadataExtraction(StrictModel):
    title: str = "NR"
    publication_year: int | None = None
    language: str = "NR"
    journal: str = "NR"
    first_author: str = "NR"
    author_contact: str = "NR"
    disease_name: str = "NR"
    country: str = "NR"
    intervention: str = "NR"
    control: str = "NR"
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class AcupunctureProtocol(StrictModel):
    control_type_transformed: ShamType | None = Field(
        default=None,
        description="Sheet1 AA；仅在证据足以分类时填写，否则为 null",
    )
    control_type_components: list[ShamType] = Field(
        default_factory=list,
        description="对照组包含多个机制时分别编码，例如非穿刺假针+常规治疗=[2,5]",
    )
    acupuncture_type: int | None = None
    stimulation_type: int | None = None
    point_selection_scheme: int | None = None
    treatment_frequency_raw: str = "NR"
    treatment_frequency_value: float | None = None
    treatment_frequency_unit: int | None = Field(default=None, description="1=天, 2=周, 3=小时")
    treatment_duration_raw: str = "NR"
    treatment_duration_value: float | None = None
    treatment_duration_unit: int | None = Field(default=None, description="1=天, 2=周")
    total_sessions: int | None = None
    deqi: DeqiType = DeqiType.NOT_REPORTED
    needle_depth_raw: str = "NR"
    retention_time_raw: str = "NR"
    retention_time_value: float | None = None
    practitioner_experience_years: float | None = None
    practitioner_experience_raw: str = "NR"
    practitioner_experience_comparator: Literal["=", "<", "<=", ">", ">=", "NR"] = "NR"
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class RiskOfBiasExtraction(StrictModel):
    random_sequence_method: str = "NR"
    random_sequence_class: int = Field(default=8, ge=1, le=9)
    allocation_concealment: str = "NR"
    allocation_concealment_class: int = Field(default=5, ge=1, le=6)
    participant_blinding: YesNoNR = YesNoNR.NOT_REPORTED
    outcome_assessor_blinding: YesNoNR = YesNoNR.NOT_REPORTED
    randomized_sample_intervention_raw: int | None = None
    randomized_sample_control_raw: int | None = None
    total_randomized: int | None = None
    primary_analysis: PrimaryAnalysis = PrimaryAnalysis.NOT_REPORTED
    missing_data_method: MissingDataMethod = MissingDataMethod.NOT_REPORTED
    evidence: list[EvidenceQuote] = Field(default_factory=list)

    @model_validator(mode="after")
    def randomized_total_is_consistent(self) -> "RiskOfBiasExtraction":
        if self.randomized_sample_intervention_raw is not None and self.randomized_sample_control_raw is not None:
            represented_arm_sum = self.randomized_sample_intervention_raw + self.randomized_sample_control_raw
            # The legacy sheet exposes only one intervention and one control
            # slot, while RCTs may contain additional comparator arms.  A total
            # above the represented two-arm sum is therefore valid; a total
            # below it is arithmetically impossible and remains fail-closed.
            if self.total_randomized is not None and self.total_randomized < represented_arm_sum:
                raise ValueError(
                    f"total_randomized={self.total_randomized} but represented arm sum={represented_arm_sum}"
                )
        return self


class OutcomeArm(StrictModel):
    """Evidence-bearing identity for one arm in an outcome row.

    The legacy Sheet3 projection still uses the scalar intervention/control
    fields below ``OutcomeStatistic``.  This small nested structure keeps the
    original arm label and supports trials with more than two arms without
    forcing an A/B comparison into two anonymous scalar slots.
    """

    arm_id: str = "NR"
    arm_label: str = "NR"
    role: Literal["intervention", "control", "comparator", "other", "NR"] = "NR"
    n: int | None = Field(default=None, ge=0)
    # Semantic aliases used by the lossless outcome prompt.  ``estimate`` is
    # retained for the Excel-facing projection; these fields preserve the
    # distinction between a reported arm value, its explicit SD and a change
    # from baseline without forcing downstream consumers to parse strings.
    value: float | None = None
    sd: float | None = Field(default=None, ge=0)
    change: float | None = None
    estimate: float | None = None
    lower: float | None = None
    upper: float | None = None
    event_count: int | None = Field(default=None, ge=0)


class OutcomeComparison(StrictModel):
    """The comparison represented by one outcome record."""

    relation: Literal[
        "intervention_vs_control",
        "arm_vs_arm",
        "multi_arm",
        "within_arm",
        "overall",
        "not_applicable",
        "NR",
    ] = "NR"
    intervention_arm_id: str = "NR"
    control_arm_id: str = "NR"
    comparator_arm_ids: list[str] = Field(default_factory=list)
    contrast: str = "NR"


class OutcomeAnalysisSet(str, Enum):
    """Stable analysis-set labels used in the provenance layer.

    ``OutcomeStatistic.analysis_population`` remains the Excel-compatible
    population field.  ``analysis_set`` preserves source labels such as FAS,
    PPS, LOCF and MMRM instead of conflating them with ITT/PP.
    """

    # This enum is intentionally not used as a Pydantic field type: source
    # analysis labels are open-ended and must be preserved rather than coerced
    # to a guessed category.  It documents the common values for callers.
    ITT = "ITT"
    MITT = "mITT"
    PP = "PP"
    FAS = "FAS"
    PPS = "PPS"
    AVAILABLE_CASE = "available_case"
    LOCF = "LOCF"
    MMRM = "MMRM"
    OTHER = "other"
    NOT_REPORTED = "NR"


class OutcomeRecordRole(str, Enum):
    """Role of a source row in the article's Results evidence."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    SAFETY = "safety"
    SUBGROUP = "subgroup"
    SENSITIVITY = "sensitivity"
    BASELINE = "baseline"
    ADMINISTRATIVE = "administrative"
    OTHER = "other"
    NOT_REPORTED = "NR"


class OutcomeStatistic(StrictModel):
    # Provenance/identity fields are deliberately part of the record, not a
    # sidecar.  They let downstream grouping distinguish the same numeric
    # result repeated in different tables or rows.
    table_id: str = Field(default="NR", description="来源表稳定ID，例如 table-2")
    row_id: str = Field(default="NR", description="来源表行稳定ID，例如 table-2:r004")
    outcome_name: str
    measurement_instrument: str = "NR"
    outcome_observation_timepoint_raw: str
    outcome_observation_timepoint_value: float | None = None
    outcome_observation_timepoint_unit: int | None = Field(default=None, description="1=天,2=月,3=年,4=周,5=小时")
    statistic_type: Literal["continuous", "binary", "ordinal", "other"]
    analysis_population: Literal["ITT", "mITT", "PP", "available_case", "other", "NR"] = "NR"
    intervention_estimate: float | None = None
    intervention_variance_lower: float | None = None
    intervention_variance_upper: float | None = None
    intervention_n: int | None = None
    control_estimate: float | None = None
    control_variance_lower: float | None = None
    control_variance_upper: float | None = None
    control_n: int | None = None
    between_group_measure: Literal["MD", "SMD", "OR", "RR", "RD", "HR", "percent_change", "other", "NR"] = "NR"
    outcome_between_group_estimate: float | None = None
    outcome_between_group_lower: float | None = None
    outcome_between_group_upper: float | None = None
    outcome_p_value: float | None = None
    outcome_p_value_comparator: Literal["=", "<", "<=", ">", ">=", "NR"] = "NR"
    effect_size_name: str = "NR"
    arm: list[OutcomeArm] = Field(
        default_factory=list,
        description="该行出现的全部试验臂及其原文身份；不能由金标准补写",
    )
    comparison: OutcomeComparison = Field(
        default_factory=OutcomeComparison,
        description="该记录实际表示的组间/组内比较",
    )
    analysis_set: str = Field(
        default="NR",
        description="原文分析集标签，如 FAS、PPS、LOCF、MMRM；无证据为NR",
    )
    record_role: Literal[
        "primary", "secondary", "safety", "subgroup", "sensitivity",
        "baseline", "administrative", "other", "NR",
    ] = "NR"
    # Lossless source-layer fields.  These mirror the outcome prompt contract
    # and deliberately remain alongside the Excel-compatible projections so
    # post-processing/evaluation can inspect the exact cells without having
    # to reconstruct them from a shortened quote or a normalized value.
    source_values: list[str] = Field(
        default_factory=list,
        description="当前表格行中逐字复制的所有数值/效应/P/CI单元格，保持原顺序",
    )
    source_evidence: str = Field(
        default="NR",
        description="当前表/行的连续逐字证据，不跨行拼接",
    )
    source_cells: list[dict[str, Any]] = Field(
        default_factory=list,
        description="确定性表头映射下的原始单元格、行列坐标和表头路径",
    )
    p_value_cells: list[dict[str, Any]] = Field(
        default_factory=list,
        description="当前行所有P值单元格及其列来源；outcome_p_value仅为兼容投影",
    )
    derived: bool = Field(
        default=False,
        description="是否由当前行证据做了唯一可复算推导",
    )
    derivation: str | None = Field(
        default=None,
        description="derived=true时的公式、输入单元格或唯一映射；否则为null",
    )
    conflict_group_id: str | None = Field(
        default=None,
        description="重复/冲突记录的稳定组标识；抽取阶段不依据Gold生成",
    )
    evidence: list[EvidenceQuote] = Field(default_factory=list)


class OutcomeExtraction(StrictModel):
    outcomes: list[OutcomeStatistic] = Field(default_factory=list)


class OutcomePostProcessDecision(StrictModel):
    """LLM annotations for one already-extracted outcome row.

    The decision deliberately contains no replacement numeric values.  The
    pipeline attaches the original ``OutcomeStatistic`` by ``source_index`` so
    post-processing can annotate and compare a row without overwriting it.
    """

    source_index: int = Field(ge=0, description="原始 outcomes 数组中的零基索引")
    normalized_outcome_name: str = "NR"
    normalized_measurement_instrument: str = "NR"
    normalized_timepoint: str = "NR"
    comparison_relation: str = "NR"
    duplicate_group: str | None = None
    gold_row_ids: list[str] = Field(default_factory=list)
    conflict_status: Literal["none", "conflict", "unresolved", "not_checked"] = "unresolved"
    annotation_status: Literal["none", "conflict", "unresolved", "not_checked"] = "unresolved"
    conflict_fields: list[str] = Field(default_factory=list)
    conflict_reason: str = ""


class OutcomePostProcessBatch(StrictModel):
    records: list[OutcomePostProcessDecision] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class OutcomePostProcessRecord(StrictModel):
    """A lossless source row plus LLM post-processing annotations."""

    source_index: int = Field(ge=0)
    source_outcome: OutcomeStatistic
    normalized_outcome_name: str = "NR"
    normalized_measurement_instrument: str = "NR"
    normalized_timepoint: str = "NR"
    comparison_relation: str = "NR"
    duplicate_group: str | None = None
    conflict_group_id: str | None = None
    gold_row_ids: list[str] = Field(default_factory=list)
    conflict_status: Literal["none", "conflict", "unresolved", "not_checked"] = "unresolved"
    annotation_status: Literal["none", "conflict", "unresolved", "not_checked"] = "unresolved"
    conflict_fields: list[str] = Field(default_factory=list)
    conflict_reason: str = ""
    processing_status: Literal["processed", "not_processed"] = "processed"
    value_preserved: bool = True


class OutcomeConflictGroup(StrictModel):
    """A semantic identity group containing repeated or conflicting rows."""

    conflict_group_id: str
    source_indices: list[int] = Field(default_factory=list)
    source_row_ids: list[str] = Field(default_factory=list)
    identity_key: str
    group_status: Literal["duplicate", "conflict", "unresolved"] = "unresolved"
    conflict_fields: list[str] = Field(default_factory=list)
    reason: str = ""


class CanonicalOutcomeRecord(StrictModel):
    """One independently selected canonical row plus all retained sources."""

    canonical_id: str
    source_indices: list[int] = Field(default_factory=list)
    conflict_group_id: str | None = None
    selection_status: Literal["selected", "conflict", "unresolved"] = "selected"
    selection_basis: Literal[
        "single_source", "most_complete_evidence", "direct_source_priority", "unresolved"
    ] = "unresolved"
    selection_reason: str = ""
    outcome: OutcomeStatistic


class OutcomeCanonicalDataset(StrictModel):
    """Canonical view generated from article evidence, never from gold values."""

    schema_version: str = "OUTCOME_CANONICAL/1.0"
    source_outcome_count: int = Field(ge=0)
    canonical_outcome_count: int = Field(ge=0)
    conflict_group_count: int = Field(ge=0)
    gold_used: bool = False
    records: list[CanonicalOutcomeRecord] = Field(default_factory=list)
    conflict_groups: list[OutcomeConflictGroup] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GoldOutcomeConflict(StrictModel):
    gold_row_id: str
    conflict_status: Literal["conflict", "unresolved"] = "conflict"
    source_indices: list[int] = Field(default_factory=list)
    conflict_fields: list[str] = Field(default_factory=list)
    reason: str = ""


class OutcomePostProcessing(StrictModel):
    """Post-extraction outcome annotations; raw rows are never replaced."""

    schema_version: str = "OUTCOME_POSTPROCESS/1.1"
    status: Literal["success", "partial", "failed"] = "failed"
    source_outcome_count: int = Field(ge=0)
    processed_outcome_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    duplicate_group_count: int = Field(ge=0)
    gold_comparison: Literal["provided", "unavailable"] = "unavailable"
    gold_rows: list[dict[str, Any]] = Field(default_factory=list)
    records: list[OutcomePostProcessRecord] = Field(default_factory=list)
    gold_conflicts: list[GoldOutcomeConflict] = Field(default_factory=list)
    canonical_dataset: OutcomeCanonicalDataset | None = None
    notes: list[str] = Field(default_factory=list)


class FlowArm(StrictModel):
    arm_name: str
    randomized_n: int | None = None
    received_n: int | None = None
    analyzed_n: int | None = None
    dropout_n: int | None = None
    dropout_reasons: list["FlowEvent"] = Field(default_factory=list)
    follow_up_completed_n: dict[str, int] = Field(default_factory=dict)
    other_missing_data: list["FlowEvent"] = Field(default_factory=list)


class FlowEvent(StrictModel):
    stage: str
    n: int | None = None
    reason: str


class FlowEvidence(StrictModel):
    quote: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    source: Literal["figure", "markdown"] = "figure"
    support_type: Literal["direct", "derived"] = "direct"
    derivation: str | None = None


class ConsortFlowExtraction(StrictModel):
    screened_n: int | None = None
    randomized_n: int | None = None
    arms: list[FlowArm] = Field(default_factory=list)
    evidence: list[FlowEvidence] = Field(default_factory=list)


class ExtractionBundle(StrictModel):
    article_id: str
    parser_backend: str
    metadata: MetadataExtraction
    acupuncture: AcupunctureProtocol
    risk_of_bias: RiskOfBiasExtraction
    outcomes: OutcomeExtraction
    consort_flow: ConsortFlowExtraction | None = None
    cross_check_issues: list[str] = Field(default_factory=list)
