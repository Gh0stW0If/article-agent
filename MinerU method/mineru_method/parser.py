from __future__ import annotations

import os
import json
import shutil
import subprocess
from pathlib import Path

from article_agent.document_pipeline import ParserRoute, route_pdf


def _find_markdown(output_dir: Path) -> Path:
    candidates = sorted(output_dir.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
    if not candidates:
        raise RuntimeError(f"MinerU completed but no Markdown was found under {output_dir}")
    return candidates[0]


def mineru_to_markdown(pdf: Path, output_dir: Path) -> tuple[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mineru = shutil.which("mineru")
    magic_pdf = shutil.which("magic-pdf")
    if mineru:
        mineru_backend = os.getenv("ARTICLE_AGENT_MINERU_BACKEND", "pipeline")
        command = [mineru, "-p", str(pdf), "-o", str(output_dir), "-b", mineru_backend]
        backend = f"mineru:{mineru_backend}"
    elif magic_pdf:
        command = [magic_pdf, "-p", str(pdf), "-o", str(output_dir), "-m", "auto"]
        backend = "magic-pdf"
    else:
        raise RuntimeError("MinerU is not installed in the Agent environment; install requirements-mineru.txt or pass --markdown")
    completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"{backend} failed with exit code {completed.returncode}: {detail}")
    path = _find_markdown(output_dir)
    return path.read_text(encoding="utf-8"), backend


def docling_to_markdown(pdf: Path, output_dir: Path) -> tuple[str, str]:
    """Convert a clean native-text PDF with Docling when it is installed.

    Docling has changed the name of its Markdown exporter across minor
    versions.  Support the known variants and fail loudly so the hybrid
    router can record a deterministic fallback rather than mislabeling the
    output as Docling.
    """

    try:
        from docling.datamodel.base_models import InputFormat  # type: ignore
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # type: ignore
        from docling.document_converter import PdfFormatOption  # type: ignore
        from docling.document_converter import DocumentConverter  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Docling is not installed in the Agent environment") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = os.getenv("ARTICLE_AGENT_DOCLING_ARTIFACTS", "").strip()
    if artifacts:
        # The 2015 corpus has a complete native text layer.  OCR is disabled
        # here to avoid replacing reliable embedded text and to keep the local
        # model bundle limited to layout + table structure.
        pipeline_options = PdfPipelineOptions(
            artifacts_path=Path(artifacts),
            do_ocr=False,
            do_table_structure=True,
        )
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    else:
        converter = DocumentConverter()
    result = converter.convert(str(pdf))
    document = getattr(result, "document", result)
    markdown = None
    for method_name in ("export_to_markdown", "export_markdown", "to_markdown"):
        method = getattr(document, method_name, None)
        if callable(method):
            markdown = method()
            break
    if not isinstance(markdown, str) or not markdown.strip():
        raise RuntimeError("Docling conversion completed but no Markdown exporter returned text")
    path = output_dir / "docling.md"
    path.write_text(markdown, encoding="utf-8")
    # Keep DoclingDocument's structured form when the installed version
    # exposes an exporter; Markdown remains the common downstream contract.
    for method_name in ("export_to_dict", "model_dump", "to_dict"):
        method = getattr(document, method_name, None)
        if callable(method):
            try:
                value = method()
                (output_dir / "docling_document.json").write_text(
                    json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )
            except Exception:
                pass
            break
    return markdown, "docling"


def hybrid_to_markdown(
    pdf: Path,
    output_dir: Path,
    *,
    force_backend: str | None = None,
) -> tuple[str, str, ParserRoute]:
    """Use the PyMuPDF audit to select Docling or MinerU with safe fallback."""

    route = route_pdf(pdf, force_backend=force_backend)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        if route.preferred_backend == "docling":
            markdown, backend = docling_to_markdown(pdf, output_dir / "docling")
        elif route.preferred_backend == "mineru":
            markdown, backend = mineru_to_markdown(pdf, output_dir / "mineru")
        else:
            markdown, backend = pymupdf_to_markdown(pdf), "pymupdf-explicit"
        route.effective_backend = backend
        route.fallback_used = backend != route.preferred_backend
        route.warnings = list(route.warnings)
    except Exception as exc:
        # A partial third-party conversion is not promoted to a successful
        # result.  Keep the source PDF usable with the deterministic parser and
        # persist the exact error in parser_route.json for later remediation.
        markdown, backend = pymupdf_to_markdown(pdf), f"pymupdf-fallback:{route.preferred_backend}"
        route.effective_backend = backend
        route.fallback_used = True
        route.warnings = list(route.warnings) + [f"{route.preferred_backend} conversion failed: {type(exc).__name__}: {exc}"]
    (output_dir / "parser_route.json").write_text(route.model_dump_json(indent=2), encoding="utf-8")
    return markdown, backend, route


def pymupdf_to_markdown(pdf: Path) -> str:
    """Explicit experiment fallback. This output must never be labelled MinerU."""
    from article_agent.pdf import parse_pdf

    document = parse_pdf(pdf)
    pieces: list[str] = []
    current_section: str | None = None
    current_page: int | None = None
    routed_sections = {"abstract", "introduction", "methods", "results", "discussion", "references"}
    structured_table_ids = {table.table_id for table in document.tables if table.rows}
    fallback_table_chunks: list = []
    for chunk in document.chunks:
        if chunk.source_type == "table":
            if chunk.table_id not in structured_table_ids:
                fallback_table_chunks.append(chunk)
            continue
        if chunk.page != current_page:
            current_page = chunk.page
            pieces.append(f"<!-- page: {current_page} -->")
        section = chunk.section if chunk.section in routed_sections else "front_matter"
        if section != current_section and section != "front_matter":
            pieces.append(f"# {section.upper()}")
        current_section = section
        pieces.append(chunk.text)

    for table in document.tables:
        if not table.rows:
            continue
        pieces.append(f"\nTable {table.table_id}; page {table.page}; caption: {table.caption or 'NR'}")
        width = max(len(row) for row in table.rows)
        rows = [row + [""] * (width - len(row)) for row in table.rows]
        pieces.append("| " + " | ".join(rows[0]) + " |")
        pieces.append("| " + " | ".join(["---"] * width) + " |")
        pieces.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    for chunk in fallback_table_chunks:
        cell = chunk.text.replace("|", "\\|").replace("\n", "<br>")
        pieces.append(f"\nTable candidate {chunk.table_id}; page {chunk.page}")
        pieces.append("| recovered table text |")
        pieces.append("| --- |")
        pieces.append(f"| {cell} |")
    return "\n\n".join(pieces)
