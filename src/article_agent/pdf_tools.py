from __future__ import annotations

from typing import Any

from .retrieval import HybridRetriever
from .schemas import DocumentChunk, ParsedDocument
from .evidence_engine import (
    BibliographicMetadata,
    EvidenceAnswer,
    RCSHit,
    RCSRetriever,
    ContradictionRecord,
    detect_contradictions,
    generate_evidence_answer,
    inject_bibliographic_metadata,
)


def search_pdf(doc: ParsedDocument, query: str, sections: set[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
    retriever = HybridRetriever(doc.chunks)
    hits = retriever.search(query, sections=sections, limit=limit)
    return [quote_source(chunk, score) for chunk, score in hits]


def read_page(doc: ParsedDocument, page: int, source_types: set[str] | None = None) -> list[DocumentChunk]:
    chunks = [chunk for chunk in doc.chunks if chunk.page == page]
    if source_types:
        chunks = [chunk for chunk in chunks if chunk.source_type in source_types]
    return chunks


def extract_table(doc: ParsedDocument, table_id: str) -> dict[str, Any] | None:
    table = next((t for t in doc.tables if t.table_id == table_id), None)
    return table.model_dump(mode="json") if table else None


def analyze_figure(doc: ParsedDocument, figure_id: str) -> dict[str, Any] | None:
    figure = next((f for f in doc.figures if f.figure_id == figure_id), None)
    if figure:
        return figure.model_dump(mode="json")
    chunk = next((c for c in doc.chunks if c.figure_id == figure_id or c.source_type == "vision"), None)
    return chunk.model_dump(mode="json") if chunk else None


def quote_source(chunk: DocumentChunk, score: float | None = None) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "study_id": chunk.study_id,
        "page": chunk.page,
        "section": chunk.section,
        "section_path": chunk.section_path,
        "source_type": chunk.source_type,
        "table_id": chunk.table_id,
        "figure_id": chunk.figure_id,
        "bbox": chunk.bbox,
        "score": score,
        "context_prefix": chunk.context_prefix,
        "text": chunk.text,
    }


def search_pdf_rcs(
    doc: ParsedDocument,
    query: str,
    *,
    client: Any | None = None,
    metadata: BibliographicMetadata | None = None,
    sections: set[str] | None = None,
    top_k: int = 5,
    candidate_pool: int = 1000,
    rerank: bool = True,
) -> list[RCSHit]:
    """Run the bounded RCS retrieval flow over a parsed PDF.

    Metadata injection is opt-in so existing callers keep their exact source
    chunks.  When supplied, the injected chunks are copies and the original
    ``ParsedDocument`` is not mutated.
    """

    chunks = inject_bibliographic_metadata(doc.chunks, metadata) if metadata else list(doc.chunks)
    return RCSRetriever(chunks, client=client, candidate_cap=min(candidate_pool, 1000)).gather(
        query,
        top_k=top_k,
        candidate_pool=candidate_pool,
        sections=sections,
        rerank=rerank,
    )


def answer_pdf_question(
    doc: ParsedDocument,
    query: str,
    *,
    client: Any | None = None,
    metadata: BibliographicMetadata | None = None,
    top_k: int = 5,
    candidate_pool: int = 1000,
) -> EvidenceAnswer:
    """Retrieve, audit contradictions, and generate an inline-cited answer."""

    hits = search_pdf_rcs(
        doc,
        query,
        client=client,
        metadata=metadata,
        top_k=top_k,
        candidate_pool=candidate_pool,
        rerank=client is not None,
    )
    contradictions: list[ContradictionRecord] = detect_contradictions(hits, client=client)
    return generate_evidence_answer(query, hits, client=client, contradictions=contradictions)
