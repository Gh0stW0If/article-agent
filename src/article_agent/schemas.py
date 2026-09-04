from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    evidence_id: str
    study_id: str
    entity_type: str
    entity_id: str
    field_name: str
    extracted_value: str | int | float | None = None
    normalized_value: str | int | float | None = None
    code: str | int | float | None = None
    evidence_text: str
    page: int | str = "NR"
    section: str = "NR"
    confidence: float = 0.0
    needs_review: bool = True
    review_reason: str = ""
    extractor_version: str = "mvp-0.1"


class FieldValue(BaseModel):
    field_name: str
    value: str | int | float | None = "NR"
    code: str | int | float | None = "NR"
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    confidence: float = 0.0
    needs_review: bool = True
    reason: str = ""


class PageInfo(BaseModel):
    study_id: str
    source_pdf: Path
    page: int
    width: float = 0.0
    height: float = 0.0
    page_type: str = "native_text"
    text_density: float = 0.0
    is_scanned: bool = False
    is_table_dense: bool = False
    is_figure_dense: bool = False
    text_block_count: int = 0
    image_count: int = 0
    table_count: int = 0
    parser_backend: str = "pymupdf+pdfplumber"
    warnings: list[str] = Field(default_factory=list)


class TableInfo(BaseModel):
    table_id: str
    study_id: str
    source_pdf: Path
    page: int
    rows: list[list[str]] = Field(default_factory=list)
    header: list[str] = Field(default_factory=list)
    caption: str = "NR"
    bbox: tuple[float, float, float, float] | None = None
    parser_backend: str = "pdfplumber"


class FigureInfo(BaseModel):
    figure_id: str
    study_id: str
    source_pdf: Path
    page: int
    caption: str = "NR"
    bbox: tuple[float, float, float, float] | None = None
    summary: str = "NR"
    parser_backend: str = "pymupdf"
    needs_review: bool = True


class SectionInfo(BaseModel):
    section_id: str
    title: str
    normalized: str = "unknown"
    level: int = 1
    start_page: int
    end_page: int | None = None


class DocumentChunk(BaseModel):
    study_id: str
    source_pdf: Path
    page: int
    section: str = "unknown"
    source_type: Literal["text", "table", "figure_caption", "figure", "page_summary", "vision"] = "text"
    text: str
    chunk_id: str = ""
    section_path: list[str] = Field(default_factory=list)
    heading_level: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    block_index: int | None = None
    table_id: str | None = None
    figure_id: str | None = None
    caption: str | None = None
    context_prefix: str = ""
    parser_backend: str = "pdfplumber"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    study_id: str
    source_pdf: Path
    page_count: int
    parser_backend: str = "pymupdf+pdfplumber"
    parser_route: dict[str, Any] = Field(default_factory=dict)
    chunks: list[DocumentChunk] = Field(default_factory=list)
    pages: list[PageInfo] = Field(default_factory=list)
    sections: list[SectionInfo] = Field(default_factory=list)
    tables: list[TableInfo] = Field(default_factory=list)
    figures: list[FigureInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class StudyRecord(BaseModel):
    study_id: str
    source_pdf: str
    extraction_status: str = "completed_with_review"
    title: FieldValue
    year: FieldValue
    journal: FieldValue
    language: FieldValue
    first_author: FieldValue
    corresponding_author_email: FieldValue
    doi: FieldValue
    corresponding_author: FieldValue
    country_category: FieldValue
    setting: FieldValue
    disease_system: FieldValue
    acute_or_chronic: FieldValue
    surgical_or_procedural: FieldValue
    study_design: FieldValue
    center_count: FieldValue
    recruitment_start: FieldValue
    recruitment_end: FieldValue
    funding: FieldValue
    conflict_of_interest: FieldValue
    eligibility_status: FieldValue
    exclusion_reason: FieldValue
    disease_name: FieldValue
    country: FieldValue
    intervention_name: FieldValue
    control_name: FieldValue
    randomized_n: FieldValue
    primary_outcome: FieldValue
    treatment_sessions: FieldValue
    notes: str = "MVP extraction; review before final use."


class ArmRecord(BaseModel):
    study_id: str
    arm_id: str
    arm_name: str
    arm_role: str
    intervention_category: str = "NR"
    intervention_components: str = "NR"
    sample_randomized: str | int = "NR"
    sample_started: str | int = "NR"
    sample_analyzed_primary: str | int = "NR"
    dropout_n: str | int = "NR"
    dropout_reason: str = "NR"
    usual_care_components: str = "NR"
    is_acupuncture_arm: bool | str = "NR"
    notes: str = "MVP candidate"


class ComparisonRecord(BaseModel):
    study_id: str
    comparison_id: str
    intervention_arm_id: str
    control_arm_id: str
    comparison_label: str
    comparison_type_code: str = "E"
    comparison_type_label: str = "Other"
    control_type_code: str = "NR"
    control_type_label: str = "NR"
    is_primary_comparison: bool = True
    primary_comparison_reason: str = "MVP first detected comparison"
    analysis_priority: int = 1
    notes: str = "needs_review"


class OutcomeRecord(BaseModel):
    study_id: str
    outcome_id: str
    outcome_name: str
    instrument: str = "NR"
    is_primary_outcome: bool = False
    patient_important_category: str = "other"
    outcome_construct: str = "NR"
    outcome_selection_reason: str = "MVP evidence retrieval"
    notes: str = "needs_review"


class ReviewRecord(BaseModel):
    review_id: str
    study_id: str
    entity_type: str
    entity_id: str
    field_name: str
    proposed_value: str | int | float | None
    proposed_code: str | int | float | None
    evidence_text: str
    issue_type: str
    severity: Literal["info", "warning", "error"] = "warning"
    reviewer_decision: str = ""
    corrected_value: str = ""
    corrected_code: str = ""
    reviewer_notes: str = ""


class RunState(BaseModel):
    year: str | None = None
    article_id: str | None = None
    use_api: bool = False
    # ``pymupdf`` preserves the historical lightweight behavior.  ``auto``
    # enables the explicit PyMuPDF-audited Docling/MinerU routing layer.
    document_backend: Literal["pymupdf", "auto", "docling", "mineru"] = "pymupdf"
    pdf_paths: list[Path] = Field(default_factory=list)
    parsed_documents: list[ParsedDocument] = Field(default_factory=list)
    document_routes: list[dict[str, Any]] = Field(default_factory=list)
    normalized_documents: list[dict[str, Any]] = Field(default_factory=list)
    studies: list[StudyRecord] = Field(default_factory=list)
    arms: list[ArmRecord] = Field(default_factory=list)
    comparisons: list[ComparisonRecord] = Field(default_factory=list)
    outcomes: list[OutcomeRecord] = Field(default_factory=list)
    methods: list[dict] = Field(default_factory=list)
    acupuncture: list[dict] = Field(default_factory=list)
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    review: list[ReviewRecord] = Field(default_factory=list)
    legacy_sheet1: list[dict] = Field(default_factory=list)
    api_status: str = "not_requested"
    logs: list[dict] = Field(default_factory=list)
    output_dir: Path | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



