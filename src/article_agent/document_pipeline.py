"""Hybrid document parsing and evidence-preserving normalization.

The project historically used :func:`article_agent.pdf.parse_pdf` as a
single, dependency-light parser.  This module adds an explicit decision layer
around that parser instead of silently pretending that an optional backend is
available.  The decision is based only on PyMuPDF observations (text layer,
encoding health, layout and formula signals), and every fallback is recorded in
the returned models.

Heavy engines are optional.  Docling, MinerU, RT-DETR/DocLayout-YOLO,
UniMERNet and TableFormer/StructTable can be enabled by installing the
corresponding package or setting a command/model path.  When an optional
component is unavailable, the deterministic parser remains usable and the
warning is attached to the artifact rather than being hidden.
"""

from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, Field

from .schemas import DocumentChunk, ParsedDocument, TableInfo

try:  # PyMuPDF is a mandatory project dependency, but keep import graceful.
    import fitz  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    fitz = None  # type: ignore


class TextLayerPageFeatures(BaseModel):
    """Observations for one PDF page used by the backend router."""

    page: int
    characters: int = 0
    words: int = 0
    text_blocks: int = 0
    image_blocks: int = 0
    native_text: bool = False
    replacement_characters: int = 0
    replacement_ratio: float = 0.0
    formula_markers: int = 0
    column_count: int = 1
    encoding_issues: list[str] = Field(default_factory=list)


class PdfTextLayerReport(BaseModel):
    """PDF-level text/geometry audit before selecting a parser backend."""

    schema_version: str = "PDF_TEXT_LAYER/1.0"
    source_pdf: Path
    page_count: int
    native_text_pages: int = 0
    text_coverage: float = 0.0
    scanned_page_ratio: float = 0.0
    replacement_char_ratio: float = 0.0
    formula_density: float = 0.0
    multi_column_pages: int = 0
    encoding_issues: list[str] = Field(default_factory=list)
    pages: list[TextLayerPageFeatures] = Field(default_factory=list)


class ParserRoute(BaseModel):
    """Auditable backend decision."""

    schema_version: str = "PARSER_ROUTE/1.0"
    source_pdf: Path
    preferred_backend: Literal["docling", "mineru", "pymupdf"]
    effective_backend: str
    reason_codes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    text_layer: PdfTextLayerReport
    optional_backends: dict[str, bool] = Field(default_factory=dict)
    forced_backend: str | None = None
    fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class LayoutBlock(BaseModel):
    """Normalized block used for retrieval and downstream extraction."""

    block_id: str
    page: int
    kind: Literal["text", "heading", "table", "figure", "formula", "unknown"] = "text"
    text: str = ""
    bbox: tuple[float, float, float, float] | None = None
    reading_order: int = 0
    section: str = "unknown"
    parser_backend: str = "heuristic"
    detector_backend: str = "heuristic-bbox"
    confidence: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormulaArtifact(BaseModel):
    formula_id: str
    page: int
    raw: str
    latex: str | None = None
    number: str | None = None
    parser_backend: str = "unimernet-unavailable"
    status: Literal["parsed", "preserved", "unavailable", "needs_review"] = "preserved"
    evidence_chunk_id: str | None = None


class TableArtifact(BaseModel):
    table_id: str
    page_start: int
    page_end: int
    caption: str = "NR"
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    html: str = ""
    otsl: str = ""
    stitched_from: list[str] = Field(default_factory=list)
    parser_backend: str = "deterministic-rows"
    structure_backend: str = "deterministic-rows"
    has_spans: bool = False
    warnings: list[str] = Field(default_factory=list)


class NormalizedDocument(BaseModel):
    """Lossless-ish normalized representation for retrieval/indexing."""

    schema_version: str = "NORMALIZED_DOCUMENT/1.0"
    study_id: str
    source_pdf: Path
    parser_backend: str
    route: ParserRoute | None = None
    blocks: list[LayoutBlock] = Field(default_factory=list)
    formulas: list[FormulaArtifact] = Field(default_factory=list)
    tables: list[TableArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_FORMULA_PATTERNS = (
    re.compile(r"\\(?:frac|sqrt|sum|int|prod|alpha|beta|gamma|theta|times|leq|geq|begin|end)"),
    re.compile(r"\$(?:[^$\n]{2,})\$|\\\((?:[^\n]{2,})\\\)"),
    re.compile(r"[∑∫√≤≥±×÷≈∞]"),
    re.compile(r"\b(?:equation|eq\.?|formula)\s*\(?\d*[A-Za-z]?\)?", re.I),
)
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s*)?\d{1,4}\s*$", re.I)
_WATERMARK_RE = re.compile(r"^\s*(?:accepted manuscript|copyright|doi:\s*10\.|www\.|preprint)\b", re.I)
_HEADING_RE = re.compile(r"^(?:[A-Z][A-Z\s\-:&]{2,80}|(?:abstract|introduction|methods?|results?|discussion|references?)\b)", re.I)


def _formula_count(text: str) -> int:
    return sum(len(pattern.findall(text)) for pattern in _FORMULA_PATTERNS)


def _column_count(blocks: Sequence[dict[str, Any]], width: float) -> int:
    """Estimate columns from text block centers without a ML dependency."""

    centers: list[float] = []
    for block in blocks:
        bbox = block.get("bbox") or []
        if len(bbox) >= 4:
            centers.append((float(bbox[0]) + float(bbox[2])) / 2)
    if len(centers) < 6 or width <= 0:
        return 1
    left = sum(center < width * 0.46 for center in centers)
    right = sum(center > width * 0.54 for center in centers)
    if left >= 3 and right >= 3:
        return 2
    # A three-column article is rare but easy to signal when three separated
    # clusters are present.  The router only needs to know that it is complex.
    centers = sorted(centers)
    gaps = [(b - a, index) for index, (a, b) in enumerate(zip(centers, centers[1:]))]
    if gaps:
        largest, index = max(gaps)
        if largest > width * 0.18 and index >= 2 and len(centers) - index - 1 >= 2:
            return 2
    return 1


def inspect_pdf_text_layer(pdf_path: Path) -> PdfTextLayerReport:
    """Inspect text encoding and layout using PyMuPDF only.

    ``native_text`` is intentionally conservative: a page with only a tiny
    selectable caption is not considered a complete text layer.  Replacement
    characters, embedded NULs and image-only pages are surfaced explicitly so
    callers can route to OCR/VLM rather than silently producing corrupted
    Markdown.
    """

    if fitz is None:
        raise RuntimeError("PyMuPDF is required for PDF text-layer routing")
    pdf_path = Path(pdf_path)
    pages: list[TextLayerPageFeatures] = []
    with fitz.open(str(pdf_path)) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text") or ""
            raw = page.get_text("rawdict") or {}
            blocks = [block for block in raw.get("blocks", []) if block.get("type") == 0]
            image_blocks = [block for block in raw.get("blocks", []) if block.get("type") == 1]
            words = page.get_text("words") or []
            characters = len(text.strip())
            replacement = text.count("\ufffd")
            control_chars = sum(1 for char in text if ord(char) < 9 or (13 < ord(char) < 32))
            issues: list[str] = []
            if replacement:
                issues.append("replacement_character")
            if "\x00" in text:
                issues.append("nul_character")
            if control_chars:
                issues.append("control_character")
            if image_blocks and characters < 80:
                issues.append("image_only_or_scanned")
            native = characters >= 80 and len(words) >= 8 and replacement / max(characters, 1) <= 0.02
            pages.append(TextLayerPageFeatures(
                page=page_number,
                characters=characters,
                words=len(words),
                text_blocks=len(blocks),
                image_blocks=len(image_blocks),
                native_text=native,
                replacement_characters=replacement,
                replacement_ratio=round(replacement / max(characters, 1), 6),
                formula_markers=_formula_count(text),
                column_count=_column_count(blocks, float(page.rect.width)),
                encoding_issues=issues,
            ))
    page_count = len(pages)
    native_pages = sum(page.native_text for page in pages)
    total_chars = sum(page.characters for page in pages)
    replacement_chars = sum(page.replacement_characters for page in pages)
    total_formulas = sum(page.formula_markers for page in pages)
    total_words = sum(page.words for page in pages)
    multi_column = sum(page.column_count >= 2 for page in pages)
    issues = sorted({issue for page in pages for issue in page.encoding_issues})
    return PdfTextLayerReport(
        source_pdf=pdf_path,
        page_count=page_count,
        native_text_pages=native_pages,
        text_coverage=round(native_pages / max(page_count, 1), 4),
        scanned_page_ratio=round(sum("image_only_or_scanned" in page.encoding_issues for page in pages) / max(page_count, 1), 4),
        replacement_char_ratio=round(replacement_chars / max(total_chars, 1), 6),
        formula_density=round(total_formulas / max(total_words, 1), 6),
        multi_column_pages=multi_column,
        encoding_issues=issues,
        pages=pages,
    )


def _optional_backends() -> dict[str, bool]:
    return {
        "docling": importlib.util.find_spec("docling") is not None,
        "mineru": bool(shutil.which("mineru") or shutil.which("magic-pdf")) or importlib.util.find_spec("mineru") is not None,
        "layout_rtdetr": importlib.util.find_spec("ultralytics") is not None,
        "layout_doclayout_yolo": importlib.util.find_spec("doclayout_yolo") is not None,
        "unimernet": importlib.util.find_spec("unimernet") is not None,
        "tableformer": importlib.util.find_spec("tableformer") is not None,
        "structtable": importlib.util.find_spec("structtable") is not None,
    }


def route_pdf(pdf_path: Path, *, force_backend: str | None = None, report: PdfTextLayerReport | None = None) -> ParserRoute:
    """Choose Docling for clean native text and MinerU for hard PDFs.

    The thresholds are deliberately explicit and are stored in ``reason_codes``
    so a later benchmark can tune them without changing the extraction data.
    ``force_backend`` is useful for controlled A/B tests and is never inferred
    from the gold workbook.
    """

    report = report or inspect_pdf_text_layer(pdf_path)
    forced = (force_backend or "").strip().lower() or None
    optional = _optional_backends()
    reasons: list[str] = []
    if forced in {"pymupdf", "docling", "mineru"}:
        preferred = forced
        reasons.append("forced_backend")
        confidence = 1.0
    else:
        complex_layout = report.multi_column_pages / max(report.page_count, 1) >= 0.25
        scanned = report.scanned_page_ratio > 0.05 or report.text_coverage < 0.85
        formulas = report.formula_density >= 0.02 or any(page.formula_markers >= 3 for page in report.pages)
        encoding = report.replacement_char_ratio > 0.01 or bool(set(report.encoding_issues) & {"replacement_character", "nul_character"})
        if scanned:
            reasons.append("scanned_or_incomplete_text_layer")
        if complex_layout:
            reasons.append("multi_column_layout")
        if formulas:
            reasons.append("formula_dense")
        if encoding:
            reasons.append("text_encoding_anomaly")
        preferred = "mineru" if (scanned or complex_layout or formulas or encoding) else "docling"
        confidence = 0.9 if preferred == "mineru" and reasons else 0.85 if preferred == "docling" else 0.5
        if not reasons:
            reasons.append("complete_native_text_layer_low_formula_density")
    warnings: list[str] = []
    effective = preferred
    if preferred == "docling" and not optional["docling"]:
        effective = "pymupdf-fallback:docling-unavailable"
        warnings.append("Docling is not installed; deterministic PyMuPDF parser will be used")
    elif preferred == "mineru" and not optional["mineru"]:
        effective = "pymupdf-fallback:mineru-unavailable"
        warnings.append("MinerU/magic-pdf command is not available; deterministic PyMuPDF parser will be used")
    return ParserRoute(
        source_pdf=Path(pdf_path),
        preferred_backend=preferred,  # type: ignore[arg-type]
        effective_backend=effective,
        reason_codes=reasons,
        confidence=confidence,
        text_layer=report,
        optional_backends=optional,
        forced_backend=forced,
        fallback_used=effective != preferred,
        warnings=warnings,
    )


def _clean_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).strip())


def _escape_cell(value: str) -> str:
    return html.escape(_clean_cell(value), quote=True)


def rows_to_html(rows: Sequence[Sequence[str]], *, header_rows: int = 1) -> str:
    """Serialize row matrices to deterministic HTML.

    Existing HTML from MinerU/Docling is preserved by callers.  This fallback
    intentionally does not invent spans; it emits a regular table and records
    ``has_spans=False`` so an extractor cannot mistake it for TableFormer data.
    """

    normalized = [[_clean_cell(cell) for cell in row] for row in rows if row and any(_clean_cell(cell) for cell in row)]
    if not normalized:
        return "<table></table>"
    width = max(len(row) for row in normalized)
    normalized = [row + [""] * (width - len(row)) for row in normalized]
    parts = ["<table>"]
    split = min(max(int(header_rows), 0), len(normalized))
    if split:
        parts.append("<thead>")
        for row in normalized[:split]:
            parts.append("<tr>" + "".join(f"<th>{_escape_cell(cell)}</th>" for cell in row) + "</tr>")
        parts.append("</thead>")
    parts.append("<tbody>")
    for row in normalized[split:]:
        parts.append("<tr>" + "".join(f"<td>{_escape_cell(cell)}</td>" for cell in row) + "</tr>")
    parts.extend(("</tbody>", "</table>"))
    return "".join(parts)


def rows_to_otsl(rows: Sequence[Sequence[str]]) -> str:
    """Emit a compact OTSL-like topology while retaining cell text.

    OTSL is used as a topology sidecar, not as a replacement for HTML.  The
    deterministic ``C`` token means a normal cell; model-produced spans can be
    supplied in ``TableInfo.metadata['otsl']`` and are preserved by
    :func:`table_artifacts_from_parsed`.
    """

    normalized = [[_clean_cell(cell) for cell in row] for row in rows if row]
    return "\n".join(" | ".join(f"C:{cell}" for cell in row) for row in normalized)


def _header_key(header: Sequence[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", " ".join(header).lower()).strip()


def table_artifacts_from_parsed(document: ParsedDocument) -> list[TableArtifact]:
    artifacts: list[TableArtifact] = []
    adapter = TableStructureAdapter()
    for table in document.tables:
        metadata = getattr(table, "metadata", {}) or {}
        raw_html = str(metadata.get("html") or "")
        raw_otsl = str(metadata.get("otsl") or "")
        structure_backend = str(metadata.get("structure_backend") or "deterministic-rows")
        markup, topology, has_spans = adapter.serialize(table.rows, raw_html, raw_otsl)
        artifacts.append(TableArtifact(
            table_id=table.table_id,
            page_start=table.page,
            page_end=table.page,
            caption=table.caption or "NR",
            header=list(table.header),
            rows=[list(row) for row in table.rows],
            html=markup,
            otsl=topology,
            parser_backend=table.parser_backend,
            has_spans=has_spans,
            structure_backend=structure_backend if structure_backend != "deterministic-rows" else adapter.backend,
            warnings=[] if raw_html else ["No model table structure available; regular-cell fallback used"],
        ))
    return artifacts


def stitch_cross_page_tables(tables: Sequence[TableArtifact]) -> list[TableArtifact]:
    """Join adjacent tables with the same column topology into a normalized view.

    Source tables are never deleted: the returned artifact gets a stable ID and
    ``stitched_from`` list, while rows retain their original values.  A table
    is joined only when its header matches and its caption indicates the same
    table or a continuation; this avoids merging unrelated tables that happen
    to share column names.
    """

    result: list[TableArtifact] = []
    for source in sorted(tables, key=lambda item: (item.page_start, item.table_id)):
        current = source.model_copy(deep=True)
        if result:
            previous = result[-1]
            same_header = _header_key(previous.header) and _header_key(previous.header) == _header_key(current.header)
            adjacent = current.page_start <= previous.page_end + 1
            same_caption = (
                previous.caption == current.caption
                or re.search(r"continued|cont\.?$", current.caption or "", re.I) is not None
                or previous.table_id.split("-part", 1)[0] == current.table_id.split("-part", 1)[0]
            )
            if same_header and adjacent and same_caption:
                merged_id = previous.table_id if previous.table_id.endswith("-stitched") else f"{previous.table_id}-stitched"
                repeated_header = current.rows and _header_key(current.rows[0]) == _header_key(previous.header)
                appended = current.rows[1:] if repeated_header else current.rows
                previous.rows.extend([list(row) for row in appended])
                previous.page_end = current.page_end
                previous.stitched_from = list(dict.fromkeys(previous.stitched_from + [current.table_id] + ([previous.table_id] if not previous.stitched_from else [])))
                previous.table_id = merged_id
                previous.html = rows_to_html(previous.rows)
                previous.otsl = rows_to_otsl(previous.rows)
                previous.has_spans = previous.has_spans or current.has_spans
                if previous.structure_backend == "deterministic-rows" and current.structure_backend != "deterministic-rows":
                    previous.structure_backend = current.structure_backend
                previous.warnings.append(f"stitched continuation {current.table_id} without changing source values")
                continue
        result.append(current)
    return result


def _formula_artifacts(chunks: Sequence[DocumentChunk]) -> list[FormulaArtifact]:
    artifacts: list[FormulaArtifact] = []
    parser = FormulaParser()
    counter = 0
    for chunk in chunks:
        for pattern in _FORMULA_PATTERNS:
            for match in pattern.finditer(chunk.text):
                raw = match.group(0).strip()
                if not raw:
                    continue
                counter += 1
                parsed = parser.parse(raw)
                artifacts.append(parsed.model_copy(update={
                    "formula_id": f"{chunk.study_id}-F{counter:04d}",
                    "page": chunk.page,
                    "evidence_chunk_id": chunk.chunk_id,
                }))
    return artifacts


def _is_repeated_artifact(text: str, counts: Counter[str], page_count: int) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if not normalized:
        return True
    if _PAGE_NUMBER_RE.match(normalized) or _WATERMARK_RE.match(normalized):
        return True
    return counts[normalized] >= max(3, math.ceil(page_count * 0.6)) and len(normalized) < 180


def _remove_repeated_headers_footers(blocks: Sequence[LayoutBlock], page_count: int) -> tuple[list[LayoutBlock], list[str]]:
    counts = Counter(re.sub(r"\s+", " ", block.text).strip().lower() for block in blocks if block.text.strip())
    removed: list[str] = []
    kept: list[LayoutBlock] = []
    for block in blocks:
        if _is_repeated_artifact(block.text, counts, page_count):
            removed.append(block.block_id)
            continue
        kept.append(block)
    warnings = [f"removed {len(removed)} repeated header/footer/page-number/watermark blocks"] if removed else []
    return kept, warnings


def _apply_optional_layout_detector(
    document: ParsedDocument,
    blocks: Sequence[LayoutBlock],
) -> tuple[list[LayoutBlock], list[str]]:
    """Run a configured RT-DETR/DocLayout-YOLO model on rendered pages.

    Rendering is performed in a temporary directory and only detector labels
    are copied into the normalized block sidecar.  If no model path is
    configured, the function is a no-op and the caller retains bbox ordering.
    """

    detector = LayoutDetector()
    if detector.model is None or fitz is None:
        return list(blocks), ([detector.error] if detector.error else [])
    output = list(blocks)
    warnings: list[str] = []
    try:  # pragma: no cover - optional model runtime
        with tempfile.TemporaryDirectory(prefix="article-agent-layout-") as temp_dir, fitz.open(str(document.source_pdf)) as pdf:
            for page_number, page in enumerate(pdf, start=1):
                image_path = Path(temp_dir) / f"page-{page_number:04d}.png"
                page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(str(image_path))
                regions = detector.detect(image_path)
                page_blocks = [item for item in output if item.page == page_number]
                for region in regions:
                    bbox = region.get("bbox") or []
                    if len(bbox) != 4 or not page_blocks:
                        continue
                    center_x = (float(bbox[0]) + float(bbox[2])) / 2
                    center_y = (float(bbox[1]) + float(bbox[3])) / 2
                    target = min(
                        page_blocks,
                        key=lambda item: (
                            abs(((item.bbox or (0, 0, 0, 0))[0] + (item.bbox or (0, 0, 0, 0))[2]) / 2 - center_x)
                            + abs(((item.bbox or (0, 0, 0, 0))[1] + (item.bbox or (0, 0, 0, 0))[3]) / 2 - center_y)
                        ),
                    )
                    label = str(region.get("label", "unknown")).lower()
                    kind = "formula" if any(token in label for token in ("equation", "formula", "math")) else "table" if "table" in label else "figure" if any(token in label for token in ("figure", "image", "chart")) else "heading" if any(token in label for token in ("title", "header")) else target.kind
                    target.kind = kind  # type: ignore[assignment]
                    target.detector_backend = detector.backend
                    target.confidence = max(target.confidence, float(region.get("confidence", 0.0)))
    except Exception as exc:  # pragma: no cover - optional model runtime
        warnings.append(f"{detector.backend} layout inference failed: {type(exc).__name__}: {exc}")
    return output, warnings


def normalize_parsed_document(document: ParsedDocument, route: ParserRoute | None = None) -> NormalizedDocument:
    """Convert a parsed document into layout/formula/table artifacts."""

    blocks: list[LayoutBlock] = []
    for order, chunk in enumerate(document.chunks, start=1):
        kind: Literal["text", "heading", "table", "figure", "formula", "unknown"] = "text"
        if chunk.source_type == "table":
            kind = "table"
        elif chunk.source_type in {"figure", "figure_caption", "vision"}:
            kind = "figure"
        elif _HEADING_RE.match(chunk.text[:160]):
            kind = "heading"
        if _formula_count(chunk.text):
            # Keep a text block as well; the formula sidecar is additive.
            kind = "formula" if kind == "text" else kind
        blocks.append(LayoutBlock(
            block_id=chunk.chunk_id,
            page=chunk.page,
            kind=kind,
            text=chunk.text,
            bbox=chunk.bbox,
            reading_order=order,
            section=chunk.section,
            parser_backend=chunk.parser_backend,
            detector_backend=detector_backend_name(),
            confidence=0.75 if chunk.bbox else 0.55,
            metadata={**chunk.metadata, "source_type": chunk.source_type, "table_id": chunk.table_id, "figure_id": chunk.figure_id},
        ))
    blocks, detector_warnings = _apply_optional_layout_detector(document, blocks)
    blocks, artifact_warnings = _remove_repeated_headers_footers(blocks, document.page_count)
    tables = stitch_cross_page_tables(table_artifacts_from_parsed(document))
    warnings = list(document.warnings) + detector_warnings + artifact_warnings
    if not tables and any(chunk.source_type == "table" for chunk in document.chunks):
        warnings.append("table chunks exist but no structured table rows were available")
    return NormalizedDocument(
        study_id=document.study_id,
        source_pdf=document.source_pdf,
        parser_backend=(route.effective_backend if route else (document.pages[0].parser_backend if document.pages else "unknown")),
        route=route,
        blocks=blocks,
        formulas=_formula_artifacts(document.chunks),
        tables=tables,
        warnings=warnings,
    )


def _html_table_rows(markup: str) -> tuple[list[str], list[list[str]]]:
    """Extract visible rows from MinerU/Docling HTML without losing markup."""

    header: list[str] = []
    rows: list[list[str]] = []
    for row_markup in re.findall(r"<tr\b[^>]*>.*?</tr>", markup, re.I | re.S):
        cells = re.findall(r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>", row_markup, re.I | re.S)
        values = [re.sub(r"<[^>]+>", " ", html.unescape(cell)) for cell in cells]
        values = [_clean_cell(value) for value in values]
        if values and any(values):
            if not header and re.search(r"<th\b", row_markup, re.I):
                header = values
            else:
                rows.append(values)
    return header, rows


def _pipe_row(line: str) -> list[str]:
    text = line.strip().strip("|")
    return [_clean_cell(cell.replace("\\|", "|")) for cell in text.split("|")]


def normalize_markdown_document(
    markdown: str,
    *,
    study_id: str,
    source_pdf: Path,
    parser_backend: str = "markdown",
) -> NormalizedDocument:
    """Normalize MinerU/Docling Markdown directly, retaining table markup."""

    blocks: list[LayoutBlock] = []
    tables: list[TableArtifact] = []
    current_section = "front_matter"
    page = 1
    block_number = 0
    table_number = 0
    consumed_ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"<table\b.*?</table>", markdown, re.I | re.S):
        table_number += 1
        markup = match.group(0).strip()
        before = markdown[:match.start()]
        page_match = re.findall(r"(?:<!--\s*page\s*:\s*|\bpage\s*[=:]\s*)(\d+)", before, re.I)
        table_page = int(page_match[-1]) if page_match else page
        caption_match = re.findall(r"(?:Table|Tab\.?)\s*\d+[A-Za-z]?[.:]?[^\n]{0,240}", before[-400:], re.I)
        caption = _clean_cell(caption_match[-1]) if caption_match else f"Table {table_number}"
        header, rows = _html_table_rows(markup)
        table_id = f"table-{table_number:03d}"
        tables.append(TableArtifact(
            table_id=table_id,
            page_start=table_page,
            page_end=table_page,
            caption=caption,
            header=header,
            rows=([header] if header else []) + rows,
            html=markup,
            otsl=rows_to_otsl(([header] if header else []) + rows),
            parser_backend=parser_backend,
            structure_backend="mineru-html" if parser_backend.startswith("mineru") else "docling-html",
            has_spans=bool(re.search(r"\b(?:rowspan|colspan)=", markup, re.I)),
            warnings=[] if header or rows else ["HTML table has no parsable cell rows; original markup retained"],
        ))
        consumed_ranges.append((match.start(), match.end()))

    lines = markdown.splitlines()
    pipe_rows: list[str] = []
    pipe_start = 0

    def flush_pipe() -> None:
        nonlocal pipe_rows, pipe_start, table_number
        if not pipe_rows:
            return
        rows = [_pipe_row(line) for line in pipe_rows]
        if len(rows) >= 2:
            table_number += 1
            table_id = f"table-{table_number:03d}"
            header = rows[0]
            data = rows[2:] if len(rows) > 1 and all(re.fullmatch(r"[-: ]+", cell or "") for cell in rows[1]) else rows[1:]
            tables.append(TableArtifact(
                table_id=table_id,
                page_start=page,
                page_end=page,
                caption=f"Table {table_number}",
                header=header,
                rows=[header] + data,
                html=rows_to_html([header] + data),
                otsl=rows_to_otsl([header] + data),
                parser_backend=parser_backend,
                structure_backend="markdown-pipe",
                warnings=["Pipe table has no explicit rowspan/colspan topology"],
            ))
        pipe_rows = []

    for line in lines:
        page_marker = re.search(r"(?:<!--\s*page\s*:\s*|\bpage\s*[=:]\s*)(\d+)", line, re.I)
        if page_marker:
            page = int(page_marker.group(1))
        if re.match(r"^\s*\|.*\|\s*$", line):
            if not pipe_rows:
                pipe_start = page
            pipe_rows.append(line)
            continue
        flush_pipe()
        stripped = line.strip()
        if not stripped or stripped.startswith("<table") or stripped.startswith("</table"):
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if heading:
            current_section = heading.group(2).strip().lower()
            kind: Literal["text", "heading", "table", "figure", "formula", "unknown"] = "heading"
        else:
            kind = "formula" if _formula_count(stripped) else "text"
        block_number += 1
        blocks.append(LayoutBlock(
            block_id=f"{study_id}_P{page:03d}_M{block_number:04d}",
            page=page,
            kind=kind,
            text=stripped,
            reading_order=block_number,
            section=current_section,
            parser_backend=parser_backend,
            detector_backend=detector_backend_name(),
            confidence=0.85,
        ))
    flush_pipe()
    tables = stitch_cross_page_tables(tables)
    formulas = _formula_artifacts([
        DocumentChunk(
            study_id=study_id,
            source_pdf=source_pdf,
            page=block.page,
            section=block.section,
            text=block.text,
            chunk_id=block.block_id,
            parser_backend=parser_backend,
        ) for block in blocks if block.kind == "formula"
    ])
    return NormalizedDocument(
        study_id=study_id,
        source_pdf=source_pdf,
        parser_backend=parser_backend,
        blocks=blocks,
        formulas=formulas,
        tables=tables,
        warnings=[],
    )


def chunks_from_normalized_document(normalized: NormalizedDocument) -> list[DocumentChunk]:
    """Project normalized blocks/tables into the common retrieval chunk type."""

    chunks: list[DocumentChunk] = []
    for block in normalized.blocks:
        chunks.append(DocumentChunk(
            study_id=normalized.study_id,
            source_pdf=normalized.source_pdf,
            page=block.page,
            section=block.section,
            source_type="figure_caption" if block.kind == "figure" else "table" if block.kind == "table" else "text",
            text=block.text,
            chunk_id=block.block_id,
            bbox=block.bbox,
            block_index=block.reading_order,
            context_prefix=f"study_id={normalized.study_id} | page={block.page} | section={block.section} | source_type={block.kind}",
            parser_backend=normalized.parser_backend,
            metadata={**block.metadata, "reading_order": block.reading_order, "normalized": True},
        ))
    for table in normalized.tables:
        if not table.rows:
            text = table.html
        else:
            text = f"{table.caption}\n" + "\n".join(" | ".join(row) for row in table.rows)
        chunks.append(DocumentChunk(
            study_id=normalized.study_id,
            source_pdf=normalized.source_pdf,
            page=table.page_start,
            section="results",
            source_type="table",
            text=text,
            chunk_id=f"{normalized.study_id}_{table.table_id}",
            table_id=table.table_id,
            caption=table.caption,
            context_prefix=f"study_id={normalized.study_id} | page={table.page_start} | section=results | source_type=table | table_id={table.table_id}",
            parser_backend=table.parser_backend,
            metadata={"html": table.html, "otsl": table.otsl, "has_spans": table.has_spans, "normalized": True},
        ))
    return chunks


def write_normalized_document(normalized: NormalizedDocument, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(normalized.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def parse_pdf_hybrid(
    pdf_path: Path,
    *,
    force_backend: str | None = None,
    use_vision: bool = False,
    output_dir: Path | None = None,
) -> tuple[ParsedDocument, ParserRoute, NormalizedDocument]:
    """Route a PDF and parse it with an optional backend plus safe fallback.

    The core graph can opt into this function without requiring Docling or
    MinerU at import time.  The MinerU experiment's CLI uses the same route
    object and invokes its existing command adapter for actual Markdown output.
    Here we retain the dependency-light structured parser as the safe core
    representation, which is useful for tests and for downstream code that
    needs ``ParsedDocument`` rather than Markdown.
    """

    from .pdf import parse_pdf

    route = route_pdf(pdf_path, force_backend=force_backend)
    parsed = parse_pdf(pdf_path, use_vision=use_vision)
    # The core graph deliberately keeps a structured ParsedDocument fallback;
    # the MinerU method CLI owns third-party Markdown conversion.  Do not label
    # PyMuPDF output as Docling/MinerU merely because those packages happen to
    # be installed.
    if route.preferred_backend != "pymupdf":
        route.effective_backend = f"pymupdf-structured-fallback:{route.preferred_backend}"
        route.fallback_used = True
        route.warnings = list(route.warnings) + [
            f"Core ParsedDocument adapter uses PyMuPDF structured fallback for {route.preferred_backend}; use MinerU method CLI for third-party Markdown conversion"
        ]
    parsed.parser_backend = route.effective_backend
    parsed.parser_route = route.model_dump(mode="json")
    # Add route/backend provenance without mutating the source chunks' values.
    parsed.warnings = list(parsed.warnings) + route.warnings
    for chunk in parsed.chunks:
        chunk.metadata = {**chunk.metadata, "route_preferred_backend": route.preferred_backend, "route_effective_backend": route.effective_backend}
    normalized = normalize_parsed_document(parsed, route)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "pdf_text_layer.json").write_text(route.text_layer.model_dump_json(indent=2), encoding="utf-8")
        (output_dir / "parser_route.json").write_text(route.model_dump_json(indent=2), encoding="utf-8")
        write_normalized_document(normalized, output_dir / "normalized_document.json")
    return parsed, route, normalized


def detector_backend_name() -> str:
    """Report the configured layout detector without claiming unavailable ML."""

    requested = os.getenv("ARTICLE_AGENT_LAYOUT_BACKEND", "auto").strip().lower()
    model_path = os.getenv("ARTICLE_AGENT_LAYOUT_MODEL", "").strip()
    if requested in {"rtdetr", "rt-detr"} and importlib.util.find_spec("ultralytics") and model_path and Path(model_path).exists():
        return "rt-detr"
    if requested in {"doclayout-yolo", "doclayout_yolo"} and importlib.util.find_spec("doclayout_yolo") and model_path and Path(model_path).exists():
        return "doclayout-yolo"
    if requested not in {"", "auto", "heuristic"}:
        return f"heuristic-fallback:{requested}-unavailable"
    return "heuristic-bbox"


class LayoutDetector:
    """Optional RT-DETR/DocLayout-YOLO adapter with a deterministic fallback."""

    def __init__(self, model_path: str | Path | None = None, backend: str | None = None):
        self.model_path = Path(model_path or os.getenv("ARTICLE_AGENT_LAYOUT_MODEL", "")) if (model_path or os.getenv("ARTICLE_AGENT_LAYOUT_MODEL")) else None
        self.backend = backend or detector_backend_name()
        self.model: Any | None = None
        self.error: str | None = None
        if self.model_path and self.model_path.exists() and self.backend == "rt-detr":
            try:  # ultralytics exposes RT-DETR through the same YOLO API.
                from ultralytics import RTDETR  # type: ignore
                self.model = RTDETR(str(self.model_path))
            except Exception as exc:  # pragma: no cover - optional model runtime
                self.error = f"RT-DETR unavailable: {type(exc).__name__}: {exc}"
        elif self.model_path and self.model_path.exists() and self.backend == "doclayout-yolo":
            try:  # package APIs differ; keep the adapter intentionally narrow.
                module = __import__("doclayout_yolo")
                loader = getattr(module, "DocLayoutYOLO", None)
                self.model = loader(str(self.model_path)) if callable(loader) else None
                if self.model is None:
                    self.error = "doclayout_yolo package has no DocLayoutYOLO loader"
            except Exception as exc:  # pragma: no cover - optional model runtime
                self.error = f"DocLayout-YOLO unavailable: {type(exc).__name__}: {exc}"
        elif self.backend.startswith("heuristic-fallback"):
            self.error = self.backend

    def detect(self, image_path: Path) -> list[dict[str, Any]]:
        """Return label/bbox/confidence records; empty means use bbox rules."""

        if self.model is None:
            return []
        try:  # pragma: no cover - optional model runtime
            prediction = self.model.predict(str(image_path), verbose=False)
            first = prediction[0] if isinstance(prediction, (list, tuple)) else prediction
            boxes = getattr(first, "boxes", None)
            names = getattr(first, "names", {}) or {}
            output: list[dict[str, Any]] = []
            if boxes is None:
                return output
            for index, box in enumerate(boxes):
                coords = getattr(box, "xyxy", None)
                cls = getattr(box, "cls", None)
                conf = getattr(box, "conf", None)
                values = coords[0].tolist() if coords is not None else []
                class_index = int(cls[0].item()) if cls is not None else -1
                confidence = float(conf[0].item()) if conf is not None else 0.0
                output.append({
                    "block_id": f"detected-{index:04d}",
                    "label": str(names.get(class_index, class_index)),
                    "bbox": values,
                    "confidence": confidence,
                    "detector_backend": self.backend,
                })
            return output
        except Exception as exc:  # pragma: no cover - optional model runtime
            self.error = f"{self.backend} inference failed: {type(exc).__name__}: {exc}"
            return []


class FormulaParser:
    """UniMERNet hook that never invents LaTeX when the model is absent."""

    def __init__(self, command: str | None = None):
        self.command = command or os.getenv("ARTICLE_AGENT_UNIMERNET_COMMAND", "").strip() or None
        self.backend = "unimernet" if self.command and shutil.which(self.command) else "unimernet-unavailable"

    def parse(self, raw: str) -> FormulaArtifact:
        raw = str(raw or "").strip()
        if raw.startswith("$") or "\\" in raw:
            return FormulaArtifact(
                formula_id="formula-inline",
                page=0,
                raw=raw,
                latex=raw,
                parser_backend="source-latex-preserved",
                status="parsed",
            )
        if self.command:
            try:  # pragma: no cover - optional external command
                completed = subprocess.run([self.command], input=raw, capture_output=True, text=True, timeout=60, check=False)
                latex = (completed.stdout or "").strip()
                if completed.returncode == 0 and latex:
                    return FormulaArtifact(
                        formula_id="formula-unimernet",
                        page=0,
                        raw=raw,
                        latex=latex,
                        parser_backend="unimernet",
                        status="parsed",
                    )
            except Exception:
                pass
        return FormulaArtifact(
            formula_id="formula-unavailable",
            page=0,
            raw=raw,
            latex=None,
            parser_backend="unimernet-unavailable",
            status="unavailable",
        )


class TableStructureAdapter:
    """TableFormer/StructTable hook with HTML/OTSL-preserving fallback."""

    def __init__(self, backend: str | None = None):
        requested = (backend or os.getenv("ARTICLE_AGENT_TABLE_BACKEND", "auto")).strip().lower()
        installed = _optional_backends()
        model_path = os.getenv("ARTICLE_AGENT_TABLE_MODEL", "").strip()
        model_ready = bool(model_path and Path(model_path).exists())
        if requested in {"tableformer", "auto"} and installed["tableformer"] and model_ready:
            self.backend = "tableformer"
        elif requested in {"structtable", "auto"} and installed["structtable"] and model_ready:
            self.backend = "structtable"
        elif requested in {"tableformer", "structtable"} and installed.get(requested, False) and not model_ready:
            self.backend = f"deterministic-fallback:{requested}-model-not-configured"
        elif requested not in {"", "auto", "deterministic", "deterministic-rows"}:
            self.backend = f"deterministic-fallback:{requested}-unavailable"
        else:
            self.backend = "deterministic-rows"

    def serialize(self, rows: Sequence[Sequence[str]], html_markup: str | None = None, otsl: str | None = None) -> tuple[str, str, bool]:
        markup = html_markup if html_markup and html_markup.lstrip().lower().startswith("<table") else rows_to_html(rows)
        topology = otsl or rows_to_otsl(rows)
        has_spans = bool(re.search(r"\b(?:rowspan|colspan)=", markup, re.I))
        return markup, topology, has_spans


def optional_engine_status() -> dict[str, Any]:
    """Machine-readable installation status for reports and diagnostics."""

    status = _optional_backends()
    status["layout_selected"] = detector_backend_name()
    status["formula_selected"] = "unimernet" if status["unimernet"] else "source-latex-preservation"
    status["table_selected"] = "tableformer-or-structtable" if (status["tableformer"] or status["structtable"]) else "deterministic-rows"
    return status
