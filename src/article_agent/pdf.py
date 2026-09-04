from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    try:
        import pymupdf as fitz  # type: ignore
    except ModuleNotFoundError:
        fitz = None  # type: ignore
import pdfplumber

from .models import OpenAICompatibleClient
from .schemas import DocumentChunk, FigureInfo, PageInfo, ParsedDocument, SectionInfo, TableInfo

SECTION_PATTERNS = {
    "title": re.compile(r"\b(original paper|article|research)\b", re.I),
    "abstract": re.compile(r"\babstract\b", re.I),
    "methods": re.compile(r"\b(methods?|participants|interventions?|randomi[sz]ation|statistical analysis)\b", re.I),
    "results": re.compile(r"\b(results?|findings)\b", re.I),
    "discussion": re.compile(r"\bdiscussion\b", re.I),
    "references": re.compile(r"\breferences\b", re.I),
}

HEADING_RE = re.compile(
    r"^(abstract|introduction|methods?|participants|interventions?|outcomes?|results?|discussion|conclusions?|references|funding|competing interests|contributors|trial registration)\b",
    re.I,
)
CAPTION_RE = re.compile(r"\b(?:Figure|Fig\.?|Table)\s+\d+[A-Za-z]?[.:]?\s+[^\n]{10,350}", re.I)


def infer_study_id(pdf_path: Path) -> str:
    match = re.search(r"(20\d{2})-?0*(\d{1,2})", pdf_path.name)
    if not match:
        return pdf_path.stem.lstrip("-")
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def guess_section(text: str) -> str:
    head = text[:500]
    for name, pattern in SECTION_PATTERNS.items():
        if pattern.search(head):
            return name
    return "unknown"


def _normalize_section(title: str) -> str:
    low = title.lower().strip(" .:")
    if "abstract" in low:
        return "abstract"
    if any(k in low for k in ["method", "participant", "intervention", "random", "statistical"]):
        return "methods"
    if any(k in low for k in ["result", "finding"]):
        return "results"
    if "discussion" in low:
        return "discussion"
    if "reference" in low:
        return "references"
    if "funding" in low or "competing" in low or "contributor" in low:
        return "metadata"
    return "unknown"


def _block_text(block: dict[str, Any]) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = [span.get("text", "") for span in line.get("spans", [])]
        line_text = "".join(spans).strip()
        if line_text:
            lines.append(line_text)
    return _clean("\n".join(lines))


def _ordered_text_blocks(page_dict: dict[str, Any], width: float) -> list[dict[str, Any]]:
    blocks = [b for b in page_dict.get("blocks", []) if b.get("type") == 0 and _block_text(b)]
    if len(blocks) < 4:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), round(b["bbox"][0], 1)))
    centers = [((b["bbox"][0] + b["bbox"][2]) / 2) for b in blocks]
    left = [b for b, c in zip(blocks, centers) if c < width * 0.52]
    right = [b for b, c in zip(blocks, centers) if c >= width * 0.48]
    two_col = len(left) >= 3 and len(right) >= 3
    if not two_col:
        return sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), round(b["bbox"][0], 1)))

    full_width = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) > width * 0.72]
    full_ids = {id(b) for b in full_width}
    column_blocks = [b for b in blocks if id(b) not in full_ids]
    top_full = sorted([b for b in full_width if b["bbox"][1] < 170], key=lambda b: (b["bbox"][1], b["bbox"][0]))
    bottom_full = sorted([b for b in full_width if b["bbox"][1] >= 170], key=lambda b: (b["bbox"][1], b["bbox"][0]))
    left_col = sorted([b for b in column_blocks if ((b["bbox"][0] + b["bbox"][2]) / 2) < width / 2], key=lambda b: (b["bbox"][1], b["bbox"][0]))
    right_col = sorted([b for b in column_blocks if ((b["bbox"][0] + b["bbox"][2]) / 2) >= width / 2], key=lambda b: (b["bbox"][1], b["bbox"][0]))
    return top_full + left_col + right_col + bottom_full


def _context(study_id: str, page: int, section: str, source_type: str, table_id: str | None = None, figure_id: str | None = None) -> str:
    parts = [f"study_id={study_id}", f"page={page}", f"section={section}", f"source_type={source_type}"]
    if table_id:
        parts.append(f"table_id={table_id}")
    if figure_id:
        parts.append(f"figure_id={figure_id}")
    return " | ".join(parts)


def _make_chunk(
    study_id: str,
    pdf_path: Path,
    page: int,
    section: str,
    source_type: str,
    text: str,
    chunk_index: int,
    section_path: list[str],
    bbox: tuple[float, float, float, float] | None = None,
    block_index: int | None = None,
    table_id: str | None = None,
    figure_id: str | None = None,
    caption: str | None = None,
    backend: str = "pymupdf",
    metadata: dict[str, Any] | None = None,
) -> DocumentChunk:
    context_prefix = _context(study_id, page, section, source_type, table_id, figure_id)
    return DocumentChunk(
        study_id=study_id,
        source_pdf=pdf_path,
        page=page,
        section=section,
        source_type=source_type,
        text=_clean(text),
        chunk_id=f"{study_id}_P{page:03d}_C{chunk_index:04d}",
        section_path=section_path,
        heading_level=1 if section_path else None,
        bbox=bbox,
        block_index=block_index,
        table_id=table_id,
        figure_id=figure_id,
        caption=caption,
        context_prefix=context_prefix,
        parser_backend=backend,
        metadata=metadata or {},
    )


def _tables_for_page(pdf_path: Path) -> dict[int, list[list[list[str]]]]:
    tables_by_page: dict[int, list[list[list[str]]]] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            clean_tables: list[list[list[str]]] = []
            for table in tables:
                rows = [[_clean(cell or "") for cell in row] for row in table if row]
                rows = [row for row in rows if any(cell for cell in row)]
                if rows:
                    clean_tables.append(rows)
            tables_by_page[page_index] = clean_tables
    return tables_by_page


def _caption_candidates(text: str) -> list[str]:
    return [_clean(m.group(0)) for m in CAPTION_RE.finditer(text)]


def _vision_page_summary(doc: Any, page_index_zero: int, prompt: str, client: OpenAICompatibleClient) -> dict[str, Any]:
    page = doc.load_page(page_index_zero)
    pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
    image_bytes = pix.tobytes("png")
    return client.chat_vision_json(prompt, image_bytes, "image/png")



def _parse_pdf_pdfplumber_fallback(pdf_path: Path, study_id: str, warning: str) -> ParsedDocument:
    chunks: list[DocumentChunk] = []
    pages: list[PageInfo] = []
    tables: list[TableInfo] = []
    figures: list[FigureInfo] = []
    sections: list[SectionInfo] = []
    warnings = [warning]
    chunk_counter = 0
    current_section = "unknown"
    section_path: list[str] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                clean_text = _clean(text)
                try:
                    raw_tables = page.extract_tables() or []
                except Exception as exc:
                    warnings.append(f"page {page_no}: table extraction failed: {exc}")
                    raw_tables = []
                page_type = "scanned" if not clean_text else "table_dense" if len(raw_tables) >= 2 else "native_text"
                pages.append(PageInfo(
                    study_id=study_id,
                    source_pdf=pdf_path,
                    page=page_no,
                    width=float(page.width or 0),
                    height=float(page.height or 0),
                    page_type=page_type,
                    text_density=len(clean_text) / max(float((page.width or 1) * (page.height or 1)) / 1000, 1),
                    is_scanned=not bool(clean_text),
                    is_table_dense=len(raw_tables) >= 2,
                    is_figure_dense=bool(_caption_candidates(text)),
                    text_block_count=1 if clean_text else 0,
                    table_count=len(raw_tables),
                    parser_backend="pdfplumber",
                ))
                if clean_text:
                    guessed = guess_section(clean_text)
                    if guessed != "unknown":
                        current_section = guessed
                        section_path = [guessed.title()]
                        if not any(s.normalized == guessed for s in sections):
                            sections.append(SectionInfo(section_id=f"{study_id}_SEC{len(sections)+1:02d}", title=guessed.title(), normalized=guessed, start_page=page_no))
                    chunk_counter += 1
                    chunks.append(_make_chunk(
                        study_id,
                        pdf_path,
                        page_no,
                        current_section,
                        "text",
                        clean_text,
                        chunk_counter,
                        section_path,
                        backend="pdfplumber",
                        metadata={"page_type": page_type, "fallback": True},
                    ))
                for table_index, table in enumerate(raw_tables, start=1):
                    rows = [[_clean(cell or "") for cell in row] for row in table if row]
                    rows = [row for row in rows if any(row)]
                    if not rows:
                        continue
                    table_id = f"{study_id}_P{page_no:03d}_T{table_index:02d}"
                    header = rows[0]
                    tables.append(TableInfo(table_id=table_id, study_id=study_id, source_pdf=pdf_path, page=page_no, rows=rows, header=header, parser_backend="pdfplumber"))
                    row_text = [" | ".join(row) for row in rows]
                    chunk_counter += 1
                    chunks.append(_make_chunk(
                        study_id,
                        pdf_path,
                        page_no,
                        "tables",
                        "table",
                        f"Table {table_id}. Rows: " + "\n".join(row_text),
                        chunk_counter,
                        ["Tables"],
                        table_id=table_id,
                        backend="pdfplumber",
                        metadata={"rows": rows, "header": header, "fallback": True},
                    ))
                fallback_markers = []
                low_text = clean_text.lower()
                if "table" in low_text:
                    fallback_markers.append(("tables", "table", "table"))
                if "figure" in low_text or "fig" in low_text:
                    fallback_markers.append(("figures", "figure_caption", "figure"))
                for marker_index, (section_name, source_type, marker) in enumerate(fallback_markers, start=1):
                    pos = low_text.find(marker)
                    window = clean_text[max(0, pos - 220): pos + 520] if pos >= 0 else clean_text[:520]
                    if not window.strip():
                        continue
                    if source_type == "table":
                        table_id = f"{study_id}_P{page_no:03d}_TC{marker_index:02d}"
                        tables.append(TableInfo(table_id=table_id, study_id=study_id, source_pdf=pdf_path, page=page_no, caption="table text candidate", parser_backend="pdfplumber_text_window"))
                        chunk_counter += 1
                        chunks.append(_make_chunk(
                            study_id,
                            pdf_path,
                            page_no,
                            section_name,
                            source_type,
                            f"Table text candidate {table_id}: {window}",
                            chunk_counter,
                            ["Tables"],
                            table_id=table_id,
                            caption="table text candidate",
                            backend="pdfplumber_text_window",
                            metadata={"fallback": True, "marker": marker},
                        ))
                    else:
                        figure_id = f"{study_id}_P{page_no:03d}_FC{marker_index:02d}"
                        figures.append(FigureInfo(figure_id=figure_id, study_id=study_id, source_pdf=pdf_path, page=page_no, caption=window, parser_backend="pdfplumber_text_window"))
                        chunk_counter += 1
                        chunks.append(_make_chunk(
                            study_id,
                            pdf_path,
                            page_no,
                            section_name,
                            source_type,
                            f"Figure text candidate {figure_id}: {window}",
                            chunk_counter,
                            ["Figures"],
                            figure_id=figure_id,
                            caption=window,
                            backend="pdfplumber_text_window",
                            metadata={"fallback": True, "marker": marker},
                        ))
            for section in sections:
                following = [s.start_page for s in sections if s.start_page > section.start_page]
                section.end_page = min(following) - 1 if following else len(pdf.pages)
            return ParsedDocument(study_id=study_id, source_pdf=pdf_path, page_count=len(pdf.pages), chunks=chunks, pages=pages, sections=sections, tables=tables, figures=figures, warnings=warnings)
    except Exception as exc:
        return ParsedDocument(study_id=study_id, source_pdf=pdf_path, page_count=0, warnings=warnings + [f"pdfplumber fallback failed: {exc}"])
def parse_pdf(pdf_path: Path, use_vision: bool = False, max_vision_pages: int = 2) -> ParsedDocument:
    study_id = infer_study_id(pdf_path)
    chunks: list[DocumentChunk] = []
    pages: list[PageInfo] = []
    sections: list[SectionInfo] = []
    tables: list[TableInfo] = []
    figures: list[FigureInfo] = []
    warnings: list[str] = []
    if fitz is None:
        return _parse_pdf_pdfplumber_fallback(pdf_path, study_id, "PyMuPDF unavailable; used pdfplumber structured fallback")
    chunk_counter = 0
    current_section = "unknown"
    section_path: list[str] = []
    section_starts: dict[str, SectionInfo] = {}
    vision_calls = 0
    vision_client: OpenAICompatibleClient | None = None

    try:
        tables_by_page = _tables_for_page(pdf_path)
    except Exception as exc:
        warnings.append(f"pdfplumber table pass failed: {exc}")
        tables_by_page = {}

    try:
        doc = fitz.open(str(pdf_path))
        for page_index_zero in range(doc.page_count):
            page = doc.load_page(page_index_zero)
            page_no = page_index_zero + 1
            page_dict = page.get_text("dict")
            width = float(page.rect.width)
            height = float(page.rect.height)
            raw_text = page.get_text("text") or ""
            ordered_blocks = _ordered_text_blocks(page_dict, width)
            image_blocks = [b for b in page_dict.get("blocks", []) if b.get("type") == 1]
            page_tables = tables_by_page.get(page_no, [])
            text_chars = len(_clean(raw_text))
            text_density = text_chars / max(width * height / 1000, 1)
            is_scanned = text_chars < 80 and bool(image_blocks)
            is_table_dense = len(page_tables) >= 2 or any(len(t) >= 8 for t in page_tables)
            captions = _caption_candidates(raw_text)
            is_figure_dense = bool(image_blocks) or any(c.lower().startswith(("figure", "fig")) for c in captions)
            page_type = "scanned" if is_scanned else "table_dense" if is_table_dense else "figure_dense" if is_figure_dense else "native_text"

            page_warnings: list[str] = []
            if is_scanned:
                page_warnings.append("low extractable text with image blocks; OCR/vision recommended")
            pages.append(PageInfo(
                study_id=study_id,
                source_pdf=pdf_path,
                page=page_no,
                width=width,
                height=height,
                page_type=page_type,
                text_density=round(text_density, 4),
                is_scanned=is_scanned,
                is_table_dense=is_table_dense,
                is_figure_dense=is_figure_dense,
                text_block_count=len(ordered_blocks),
                image_count=len(image_blocks),
                table_count=len(page_tables),
                warnings=page_warnings,
            ))

            for block_index, block in enumerate(ordered_blocks, start=1):
                text = _block_text(block)
                if not text:
                    continue
                heading = HEADING_RE.match(text)
                if heading:
                    normalized = _normalize_section(heading.group(1))
                    current_section = normalized if normalized != "unknown" else guess_section(text)
                    section_title = heading.group(1).strip().title()
                    section_path = [section_title]
                    if current_section not in section_starts:
                        section = SectionInfo(
                            section_id=f"{study_id}_SEC{len(section_starts)+1:02d}",
                            title=section_title,
                            normalized=current_section,
                            level=1,
                            start_page=page_no,
                        )
                        section_starts[current_section] = section
                        sections.append(section)
                elif current_section == "unknown":
                    guessed = guess_section(text)
                    if guessed != "unknown":
                        current_section = guessed
                        section_path = [guessed.title()]

                chunk_counter += 1
                chunks.append(_make_chunk(
                    study_id,
                    pdf_path,
                    page_no,
                    current_section,
                    "text",
                    text,
                    chunk_counter,
                    section_path,
                    bbox=tuple(float(v) for v in block.get("bbox", (0, 0, 0, 0))),
                    block_index=block_index,
                    backend="pymupdf",
                    metadata={"page_type": page_type},
                ))

            for table_index, table_rows in enumerate(page_tables, start=1):
                table_id = f"{study_id}_P{page_no:03d}_T{table_index:02d}"
                header = table_rows[0] if table_rows else []
                caption = next((c for c in captions if c.lower().startswith("table")), "NR")
                tables.append(TableInfo(
                    table_id=table_id,
                    study_id=study_id,
                    source_pdf=pdf_path,
                    page=page_no,
                    rows=table_rows,
                    header=header,
                    caption=caption,
                ))
                row_text = []
                for row_no, row in enumerate(table_rows[1:] if len(table_rows) > 1 else table_rows, start=1):
                    if header and len(header) == len(row):
                        row_text.append("; ".join(f"{h}: {v}" for h, v in zip(header, row) if h or v))
                    else:
                        row_text.append(" | ".join(row))
                chunk_counter += 1
                chunks.append(_make_chunk(
                    study_id,
                    pdf_path,
                    page_no,
                    "tables",
                    "table",
                    f"Table {table_id}. Caption: {caption}. Rows: " + "\n".join(row_text),
                    chunk_counter,
                    ["Tables"],
                    table_id=table_id,
                    caption=caption,
                    backend="pdfplumber",
                    metadata={"rows": table_rows, "header": header},
                ))

            for fig_index, caption in enumerate([c for c in captions if c.lower().startswith(("figure", "fig"))], start=1):
                figure_id = f"{study_id}_P{page_no:03d}_F{fig_index:02d}"
                figures.append(FigureInfo(
                    figure_id=figure_id,
                    study_id=study_id,
                    source_pdf=pdf_path,
                    page=page_no,
                    caption=caption,
                    parser_backend="caption_regex",
                ))
                chunk_counter += 1
                chunks.append(_make_chunk(
                    study_id,
                    pdf_path,
                    page_no,
                    "figures",
                    "figure_caption",
                    caption,
                    chunk_counter,
                    ["Figures"],
                    figure_id=figure_id,
                    caption=caption,
                    backend="caption_regex",
                ))


            fallback_markers = []
            low_text = _clean(raw_text).lower()
            if "table" in low_text and not page_tables:
                fallback_markers.append(("tables", "table", "table"))
            if ("figure" in low_text or "fig" in low_text) and not any(c.lower().startswith(("figure", "fig")) for c in captions):
                fallback_markers.append(("figures", "figure_caption", "figure"))
            for marker_index, (section_name, source_type, marker) in enumerate(fallback_markers, start=1):
                page_text = _clean(raw_text)
                marker_pos = page_text.lower().find(marker)
                window = page_text[max(0, marker_pos - 220): marker_pos + 520] if marker_pos >= 0 else page_text[:520]
                if not window.strip():
                    continue
                if source_type == "table":
                    table_id = f"{study_id}_P{page_no:03d}_TC{marker_index:02d}"
                    tables.append(TableInfo(table_id=table_id, study_id=study_id, source_pdf=pdf_path, page=page_no, caption="table text candidate", parser_backend="pymupdf_text_window"))
                    chunk_counter += 1
                    chunks.append(_make_chunk(
                        study_id,
                        pdf_path,
                        page_no,
                        section_name,
                        source_type,
                        f"Table text candidate {table_id}: {window}",
                        chunk_counter,
                        ["Tables"],
                        table_id=table_id,
                        caption="table text candidate",
                        backend="pymupdf_text_window",
                        metadata={"fallback": True, "marker": marker},
                    ))
                else:
                    figure_id = f"{study_id}_P{page_no:03d}_FC{marker_index:02d}"
                    figures.append(FigureInfo(figure_id=figure_id, study_id=study_id, source_pdf=pdf_path, page=page_no, caption=window, parser_backend="pymupdf_text_window"))
                    chunk_counter += 1
                    chunks.append(_make_chunk(
                        study_id,
                        pdf_path,
                        page_no,
                        section_name,
                        source_type,
                        f"Figure text candidate {figure_id}: {window}",
                        chunk_counter,
                        ["Figures"],
                        figure_id=figure_id,
                        caption=window,
                        backend="pymupdf_text_window",
                        metadata={"fallback": True, "marker": marker},
                    ))
            if use_vision and vision_calls < max_vision_pages and (is_scanned or is_figure_dense):
                try:
                    vision_client = vision_client or OpenAICompatibleClient()
                    prompt = json.dumps({
                        "task": "Summarize this PDF page for evidence retrieval. Return JSON with summary, visible_tables, visible_figures, key_numbers, uncertainty. Do not infer beyond the image.",
                        "study_id": study_id,
                        "page": page_no,
                        "page_type": page_type,
                    }, ensure_ascii=False)
                    result = _vision_page_summary(doc, page_index_zero, prompt, vision_client)
                    summary = _clean(result.get("summary", "NR") if isinstance(result, dict) else "NR")
                    key_numbers = result.get("key_numbers", []) if isinstance(result, dict) else []
                    vision_text = f"Vision page summary: {summary}. Key numbers: {key_numbers}"
                    chunk_counter += 1
                    chunks.append(_make_chunk(
                        study_id,
                        pdf_path,
                        page_no,
                        current_section,
                        "vision",
                        vision_text,
                        chunk_counter,
                        section_path,
                        backend=f"vision:{vision_client.backend_name}",
                        metadata={"vision_result": result, "page_type": page_type},
                    ))
                    vision_calls += 1
                except Exception as exc:
                    warnings.append(f"page {page_no}: vision analysis failed: {exc}")

        for section in sections:
            following = [s.start_page for s in sections if s.start_page > section.start_page]
            section.end_page = min(following) - 1 if following else doc.page_count
        page_count = doc.page_count
        doc.close()
    except Exception as exc:
        warnings.append(f"pdf parse failed: {exc}")
        page_count = 0

    return ParsedDocument(
        study_id=study_id,
        source_pdf=pdf_path,
        page_count=page_count,
        chunks=chunks,
        pages=pages,
        sections=sections,
        tables=tables,
        figures=figures,
        warnings=warnings,
    )








