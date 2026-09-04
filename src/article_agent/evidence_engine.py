"""Evidence-linked retrieval, metadata headers and answer generation.

This is a dependency-light implementation of the PaperQA-style flow described
for the project:

1. retrieve a bounded candidate pool with lexical + deterministic sparse-vector
   similarity;
2. optionally ask the configured LLM to rerank every candidate and write a
   query-specific contextual summary;
3. traverse DOI references when a caller supplies a loader;
4. surface contradictions explicitly; and
5. generate an answer that is required to carry ``[cite: DOI/Chunk_ID]``
   markers.

No step edits source extraction values.  Metadata and summaries are sidecars,
and failures remain visible in the result models.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from pydantic import BaseModel, Field

from .retrieval import HybridRetriever, tokenize
from .schemas import DocumentChunk


class JsonChatClient(Protocol):
    def chat_json(self, messages: list[dict[str, str]], temperature: float = 0.0) -> dict[str, Any]: ...


class BibliographicMetadata(BaseModel):
    """Metadata injected into every chunk header.

    ``impact_factor`` is intentionally optional: Crossref and Semantic Scholar
    do not provide a stable journal impact-factor field, so the system records
    ``NR`` unless a trusted caller supplies one.
    """

    doi: str = "NR"
    title: str = "NR"
    journal: str = "NR"
    publication_year: int | None = None
    impact_factor: str = "NR"
    citation_count: int | None = None
    retracted: bool | None = None
    is_open_access: bool | None = None
    sources: list[str] = Field(default_factory=list)
    source_records: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    fetched_at: str | None = None


class RCSHit(BaseModel):
    """One evidence candidate after retrieval and optional LLM reranking."""

    chunk_id: str
    citation_id: str
    study_id: str
    page: int
    section: str
    source_type: str
    text: str
    lexical_score: float = 0.0
    vector_score: float = 0.0
    initial_score: float = 0.0
    rerank_score: float = 0.0
    contextual_summary: str = ""
    relevant: bool = True
    rerank_backend: str = "none"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContradictionRecord(BaseModel):
    contradiction_id: str
    claim_key: str
    chunk_ids: list[str] = Field(default_factory=list)
    status: str = "unresolved"
    fields: list[str] = Field(default_factory=list)
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)


class CitationTraversalResult(BaseModel):
    seed_chunk_ids: list[str] = Field(default_factory=list)
    visited_chunk_ids: list[str] = Field(default_factory=list)
    visited_dois: list[str] = Field(default_factory=list)
    unresolved_references: list[str] = Field(default_factory=list)
    depth_reached: int = 0


class EvidenceAnswer(BaseModel):
    query: str
    answer: str
    citation_ids: list[str] = Field(default_factory=list)
    unsupported_citations: list[str] = Field(default_factory=list)
    contradiction_ids: list[str] = Field(default_factory=list)
    generation_backend: str = "fallback"


class MetadataResolver:
    """Fetch Crossref/Semantic Scholar/Unpaywall metadata with injection-safe I/O."""

    def __init__(self, *, timeout: int = 20, fetch_json: Callable[[str], dict[str, Any]] | None = None):
        self.timeout = max(1, int(timeout))
        self.fetch_json = fetch_json or self._fetch_json

    def _fetch_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Article-Agent/0.2 (evidence-metadata)",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
        return value if isinstance(value, dict) else {}

    def resolve(self, *, title: str = "NR", doi: str = "NR", allow_network: bool = True) -> BibliographicMetadata:
        normalized_doi = str(doi or "NR").strip().lower() or "NR"
        if normalized_doi.startswith("https://doi.org/"):
            normalized_doi = normalized_doi.split("https://doi.org/", 1)[1]
        result = BibliographicMetadata(doi=normalized_doi, title=str(title or "NR"))
        if not allow_network:
            return result

        crossref: dict[str, Any] | None = None
        try:
            if normalized_doi != "NR":
                url = "https://api.crossref.org/works/" + urllib.parse.quote(normalized_doi, safe="")
                crossref = self.fetch_json(url).get("message", {})
            elif title and title != "NR":
                query = urllib.parse.urlencode({"query.title": title, "rows": 1})
                items = self.fetch_json(f"https://api.crossref.org/works?{query}").get("message", {}).get("items", [])
                crossref = items[0] if items else None
        except Exception as exc:
            result.errors.append(f"crossref: {type(exc).__name__}: {exc}")
        if crossref:
            result.sources.append("crossref")
            result.source_records["crossref"] = crossref
            result.doi = str(crossref.get("DOI") or result.doi or "NR").lower()
            result.title = str((crossref.get("title") or [result.title])[0] or result.title)
            result.journal = str((crossref.get("container-title") or ["NR"])[0] or "NR")
            for key in ("published-print", "published-online", "published", "issued"):
                parts = crossref.get(key, {}).get("date-parts", [])
                if parts and parts[0]:
                    result.publication_year = int(parts[0][0])
                    break
            updates = crossref.get("update-to") or crossref.get("relation", {}).get("is-updated-by") or []
            if isinstance(updates, list) and any("retract" in json.dumps(item).lower() for item in updates):
                result.retracted = True

        if result.doi != "NR":
            encoded = urllib.parse.quote(result.doi, safe="")
            try:
                semantic = self.fetch_json(
                    f"https://api.semanticscholar.org/graph/v1/paper/DOI:{encoded}?fields=title,year,citationCount,isOpenAccess,isRetracted,journal,externalIds,references"
                )
                if semantic:
                    result.sources.append("semantic_scholar")
                    result.source_records["semantic_scholar"] = semantic
                    result.citation_count = _int_or_none(semantic.get("citationCount"))
                    result.is_open_access = _bool_or_none(semantic.get("isOpenAccess"))
                    if semantic.get("isRetracted") is not None:
                        result.retracted = bool(semantic.get("isRetracted"))
                    journal = semantic.get("journal") or {}
                    if result.journal == "NR" and isinstance(journal, dict):
                        result.journal = str(journal.get("name") or "NR")
                    if result.publication_year is None and semantic.get("year") is not None:
                        result.publication_year = _int_or_none(semantic.get("year"))
            except Exception as exc:
                result.errors.append(f"semantic_scholar: {type(exc).__name__}: {exc}")
            try:
                email = "article-agent@example.com"
                unpaywall = self.fetch_json(
                    "https://api.unpaywall.org/v2/" + encoded + "?" + urllib.parse.urlencode({"email": email})
                )
                if unpaywall:
                    result.sources.append("unpaywall")
                    result.source_records["unpaywall"] = unpaywall
                    result.is_open_access = _bool_or_none(unpaywall.get("is_oa"))
            except Exception as exc:
                result.errors.append(f"unpaywall: {type(exc).__name__}: {exc}")
        result.sources = list(dict.fromkeys(result.sources))
        result.fetched_at = datetime.now(timezone.utc).isoformat()
        return result


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if str(value).lower() in {"true", "1", "yes"}:
        return True
    if str(value).lower() in {"false", "0", "no"}:
        return False
    return None


def bibliography_header(metadata: BibliographicMetadata) -> str:
    """Stable header text prepended to every retrievable chunk."""

    doi = metadata.doi or "NR"
    year = str(metadata.publication_year) if metadata.publication_year is not None else "NR"
    citations = str(metadata.citation_count) if metadata.citation_count is not None else "NR"
    retracted = "yes" if metadata.retracted is True else "no" if metadata.retracted is False else "NR"
    return (
        f"DOI={doi} | YEAR={year} | JOURNAL={metadata.journal or 'NR'} | "
        f"IMPACT_FACTOR={metadata.impact_factor or 'NR'} | CITATION_COUNT={citations} | RETRACTED={retracted}"
    )


def inject_bibliographic_metadata(
    chunks: Sequence[DocumentChunk],
    metadata: BibliographicMetadata,
) -> list[DocumentChunk]:
    """Return chunks with a metadata header and stable citation identity."""

    header = bibliography_header(metadata)
    output: list[DocumentChunk] = []
    for chunk in chunks:
        citation_id = f"{metadata.doi}/{chunk.chunk_id}" if metadata.doi != "NR" else f"{chunk.study_id}/{chunk.chunk_id}"
        enriched = {
            **chunk.metadata,
            "bibliography": metadata.model_dump(mode="json"),
            "citation_id": citation_id,
        }
        prefix = chunk.context_prefix.strip()
        context_prefix = f"{header} | {prefix}" if prefix else header
        output.append(chunk.model_copy(update={"context_prefix": context_prefix, "metadata": enriched}))
    return output


def inject_metadata_into_contexts(
    contexts: Mapping[str, str],
    metadata: BibliographicMetadata,
) -> dict[str, str]:
    """Inject the same bibliographic header into routed Markdown contexts."""

    header = bibliography_header(metadata)
    return {
        name: f"{header}\n\n{text}" if str(text or "").strip() else header
        for name, text in contexts.items()
    }


def _hashed_vector(text: str, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % dimensions
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


class RCSRetriever:
    """Reranking and Contextual Summarization retriever."""

    def __init__(self, chunks: Sequence[DocumentChunk], client: JsonChatClient | None = None, candidate_cap: int = 1000):
        self.chunks = list(chunks)
        self.client = client
        self.candidate_cap = min(max(int(candidate_cap), 1), 1000)
        self.lexical = HybridRetriever(self.chunks)
        self.vectors = [_hashed_vector(f"{chunk.context_prefix} {chunk.text}") for chunk in self.chunks]

    def _candidate_scores(self, query: str, sections: set[str] | None, pool_size: int) -> list[RCSHit]:
        lexical_hits = self.lexical.search(query, sections=sections, limit=min(pool_size, len(self.chunks)))
        lexical_map = {chunk.chunk_id: float(score) for chunk, score in lexical_hits}
        max_lexical = max(lexical_map.values(), default=1.0)
        q_vector = _hashed_vector(query)
        scored: list[tuple[float, RCSHit]] = []
        for index, chunk in enumerate(self.chunks):
            if sections and chunk.section not in sections:
                continue
            lexical = lexical_map.get(chunk.chunk_id, 0.0)
            vector = _cosine(q_vector, self.vectors[index])
            if lexical <= 0 and vector <= 0:
                continue
            initial = 0.65 * (lexical / max_lexical if max_lexical else 0.0) + 0.35 * vector
            citation_id = str(chunk.metadata.get("citation_id") or f"{chunk.study_id}/{chunk.chunk_id}")
            hit = RCSHit(
                chunk_id=chunk.chunk_id,
                citation_id=citation_id,
                study_id=chunk.study_id,
                page=chunk.page,
                section=chunk.section,
                source_type=chunk.source_type,
                text=chunk.text,
                lexical_score=round(lexical, 6),
                vector_score=round(vector, 6),
                initial_score=round(initial, 6),
                rerank_score=round(initial, 6),
                contextual_summary=chunk.text[:500],
                metadata=chunk.metadata,
            )
            scored.append((initial, hit))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in scored[:pool_size]]

    def _rerank_one(self, query: str, hit: RCSHit) -> RCSHit:
        if self.client is None:
            return hit
        payload = {
            "task": "Score the evidence chunk for the supplied query and summarize only supported facts.",
            "query": query,
            "candidate": {
                "chunk_id": hit.chunk_id,
                "citation_id": hit.citation_id,
                "section": hit.section,
                "text": hit.text,
            },
            "output": {"score": "0..1", "relevant": True, "contextual_summary": "query-specific evidence summary"},
            "rules": ["Do not infer missing values", "Do not change the source text", "Return JSON only"],
        }
        try:
            raw = self.client.chat_json([
                {"role": "system", "content": "You are an evidence reranking and contextual summarization auditor."},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ])
            score = float(raw.get("score", raw.get("rerank_score", hit.initial_score)))
            summary = str(raw.get("contextual_summary", raw.get("summary", "")) or "").strip()
            relevant = bool(raw.get("relevant", score > 0))
            return hit.model_copy(update={
                "rerank_score": max(0.0, min(1.0, score)),
                "contextual_summary": summary[:1500] or hit.contextual_summary,
                "relevant": relevant,
                "rerank_backend": "llm",
            })
        except Exception as exc:
            return hit.model_copy(update={
                "metadata": {**hit.metadata, "rerank_error": f"{type(exc).__name__}: {exc}"},
                "rerank_backend": "llm-fallback",
            })

    def gather(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_pool: int = 1000,
        sections: set[str] | None = None,
        rerank: bool = True,
    ) -> list[RCSHit]:
        top_k = max(1, int(top_k))
        pool_size = min(max(int(candidate_pool), top_k), self.candidate_cap, 1000)
        candidates = self._candidate_scores(query, sections, pool_size)
        if rerank and self.client is not None:
            candidates = [self._rerank_one(query, hit) for hit in candidates]
        candidates = [hit for hit in candidates if hit.relevant]
        candidates.sort(key=lambda hit: (hit.rerank_score, hit.initial_score), reverse=True)
        return candidates[:top_k]


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def extract_reference_dois(text: str) -> list[str]:
    return list(dict.fromkeys(match.rstrip(".,;)]}").lower() for match in DOI_RE.findall(text or "")))


class CitationTraverser:
    """Traverse DOI references with a caller-provided local/external loader."""

    def __init__(self, loader: Callable[[str], Iterable[DocumentChunk]] | None = None):
        self.loader = loader

    def traverse(self, seeds: Sequence[DocumentChunk | RCSHit], *, max_depth: int = 1, max_nodes: int = 20) -> CitationTraversalResult:
        seed_chunks: list[DocumentChunk] = []
        for item in seeds:
            if isinstance(item, DocumentChunk):
                seed_chunks.append(item)
            else:
                seed_chunks.append(DocumentChunk(
                    study_id=item.study_id,
                    source_pdf=Path("NR"),
                    page=item.page,
                    section=item.section,
                    source_type="text",
                    text=item.text,
                    chunk_id=item.chunk_id,
                    context_prefix=item.citation_id,
                    metadata=item.metadata,
                ))
        seed_ids = [item.chunk_id for item in seeds]
        visited_chunks: list[str] = []
        visited_dois: list[str] = []
        unresolved: list[str] = []
        queue: list[tuple[DocumentChunk, int]] = [(item, 0) for item in seed_chunks]
        seen_chunk_ids: set[str] = set()
        seen_dois: set[str] = set()
        depth_reached = 0
        while queue and len(visited_chunks) < max(1, int(max_nodes)):
            chunk, depth = queue.pop(0)
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            visited_chunks.append(chunk.chunk_id)
            depth_reached = max(depth_reached, depth)
            if depth >= max_depth:
                continue
            references = list(chunk.metadata.get("reference_dois", [])) if isinstance(chunk.metadata, dict) else []
            references.extend(extract_reference_dois(chunk.text))
            for doi in dict.fromkeys(str(value).lower() for value in references if value):
                if doi in seen_dois:
                    continue
                seen_dois.add(doi)
                visited_dois.append(doi)
                if self.loader is None:
                    unresolved.append(doi)
                    continue
                try:
                    loaded = list(self.loader(doi))
                except Exception:
                    loaded = []
                if not loaded:
                    unresolved.append(doi)
                queue.extend((item, depth + 1) for item in loaded)
        return CitationTraversalResult(
            seed_chunk_ids=seed_ids,
            visited_chunk_ids=visited_chunks,
            visited_dois=visited_dois,
            unresolved_references=list(dict.fromkeys(unresolved)),
            depth_reached=depth_reached,
        )


def detect_contradictions(hits: Sequence[RCSHit], client: JsonChatClient | None = None) -> list[ContradictionRecord]:
    """Find same-claim disagreements without selecting a winning value."""

    groups: dict[str, list[RCSHit]] = defaultdict(list)
    for hit in hits:
        metadata = hit.metadata or {}
        claim_key = str(metadata.get("claim_key") or "").strip()
        if claim_key:
            groups[claim_key].append(hit)
    records: list[ContradictionRecord] = []
    for claim_key, items in groups.items():
        if len(items) < 2:
            continue
        values = [str(item.metadata.get("claim_value")) for item in items if item.metadata.get("claim_value") is not None]
        differing_values = len(set(values)) > 1
        status = "conflict" if differing_values else "unresolved"
        reason = "Same claim_key has different source values" if differing_values else "Multiple sources require semantic review"
        fields = ["claim_value"] if differing_values else []
        if client is not None:
            payload = {
                "task": "Compare evidence for contradiction; preserve all source claims.",
                "claim_key": claim_key,
                "evidence": [{"chunk_id": item.chunk_id, "text": item.text, "metadata": item.metadata} for item in items],
                "output": {"status": "none|conflict|unresolved", "fields": [], "reason": ""},
            }
            try:
                raw = client.chat_json([
                    {"role": "system", "content": "You are a clinical evidence contradiction auditor."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ])
                status = str(raw.get("status", status))
                fields = [str(value) for value in (raw.get("fields") or [])]
                reason = str(raw.get("reason", reason))
            except Exception as exc:
                reason += f"; LLM audit unavailable: {type(exc).__name__}: {exc}"
        records.append(ContradictionRecord(
            contradiction_id="contradiction-" + hashlib.sha1(claim_key.encode("utf-8")).hexdigest()[:12],
            claim_key=claim_key,
            chunk_ids=[item.chunk_id for item in items],
            status=status,
            fields=fields,
            reason=reason,
            evidence=[item.citation_id for item in items],
        ))
    return records


def generate_evidence_answer(
    query: str,
    hits: Sequence[RCSHit],
    *,
    client: JsonChatClient | None = None,
    contradictions: Sequence[ContradictionRecord] = (),
) -> EvidenceAnswer:
    """Generate a citation-anchored answer from the selected evidence set."""

    known_citations = {hit.citation_id for hit in hits}
    contradiction_ids = [item.contradiction_id for item in contradictions if item.status == "conflict"]
    if client is None:
        pieces = [f"{hit.contextual_summary or hit.text[:500]} [cite: {hit.citation_id}]" for hit in hits]
        return EvidenceAnswer(query=query, answer="\n".join(pieces), citation_ids=list(known_citations), contradiction_ids=contradiction_ids)
    payload = {
        "query": query,
        "evidence": [{"citation_id": hit.citation_id, "summary": hit.contextual_summary, "source_text": hit.text} for hit in hits],
        "contradictions": [item.model_dump(mode="json") for item in contradictions],
        "rules": [
            "Use only supplied evidence",
            "Every factual sentence must carry [cite: DOI/Chunk_ID]",
            "Mention conflicts explicitly instead of choosing a value",
            "Return JSON with answer and citations",
        ],
    }
    try:
        raw = client.chat_json([
            {"role": "system", "content": "You are an evidence-first clinical answer generator."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ])
        answer = str(raw.get("answer", raw.get("text", "")) or "").strip()
        citations = list(dict.fromkeys(re.findall(r"\[cite:\s*([^\]]+)\]", answer)))
        declared = raw.get("citation_ids") or citations
        citations = list(dict.fromkeys(str(value) for value in declared if value))
        unsupported = [citation for citation in citations if citation not in known_citations]
        return EvidenceAnswer(
            query=query,
            answer=answer or "NR",
            citation_ids=citations,
            unsupported_citations=unsupported,
            contradiction_ids=contradiction_ids,
            generation_backend="llm",
        )
    except Exception as exc:
        fallback = "\n".join(f"{hit.contextual_summary or hit.text[:500]} [cite: {hit.citation_id}]" for hit in hits)
        return EvidenceAnswer(
            query=query,
            answer=fallback or "NR",
            citation_ids=list(known_citations),
            contradiction_ids=contradiction_ids,
            generation_backend=f"fallback:{type(exc).__name__}",
        )
