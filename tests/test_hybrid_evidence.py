from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "MinerU method"))

from article_agent.document_pipeline import (
    NormalizedDocument,
    inspect_pdf_text_layer,
    normalize_parsed_document,
    optional_engine_status,
    route_pdf,
    stitch_cross_page_tables,
    TableArtifact,
    normalize_markdown_document,
)
from article_agent.evidence_engine import (
    BibliographicMetadata,
    RCSRetriever,
    detect_contradictions,
    generate_evidence_answer,
    inject_bibliographic_metadata,
    MetadataResolver,
)
from article_agent.baml_adapter import BamlExtractor
from mineru_method.prompts import PROMPT_SPECS
from mineru_method.schemas import MetadataExtraction
from article_agent.pdf import parse_pdf
from article_agent.schemas import DocumentChunk


def test_pdf_router_records_text_layer_and_optional_backends() -> None:
    pdf = Path("Datas/articles/2015/-2015-01.pdf")
    report = inspect_pdf_text_layer(pdf)
    route = route_pdf(pdf, report=report)
    assert report.page_count >= 1
    assert report.native_text_pages == report.page_count
    assert route.preferred_backend in {"docling", "mineru"}
    assert isinstance(optional_engine_status(), dict)
    assert "docling" in route.optional_backends


def test_normalized_document_keeps_provenance_and_table_sidecars() -> None:
    doc = parse_pdf(Path("Datas/articles/2015/-2015-01.pdf"))
    normalized = normalize_parsed_document(doc)
    assert isinstance(normalized, NormalizedDocument)
    assert normalized.blocks
    assert all(block.block_id for block in normalized.blocks)
    if doc.tables:
        assert normalized.tables
        assert normalized.tables[0].html.startswith("<table")
        if normalized.tables[0].rows:
            assert normalized.tables[0].otsl


def test_cross_page_stitch_requires_same_header_and_preserves_source_ids() -> None:
    first = TableArtifact(
        table_id="table-1-part-1", page_start=2, page_end=2,
        caption="Table 1", header=["Outcome", "Mean"], rows=[["Outcome", "Mean"], ["Pain", "1.0"]],
    )
    second = TableArtifact(
        table_id="table-1-part-2", page_start=3, page_end=3,
        caption="Table 1 continued", header=["Outcome", "Mean"], rows=[["Outcome", "Mean"], ["Anxiety", "2.0"]],
    )
    merged = stitch_cross_page_tables([first, second])
    assert len(merged) == 1
    assert merged[0].rows[-1] == ["Anxiety", "2.0"]
    assert "table-1-part-2" in merged[0].stitched_from
    assert any("without changing source values" in warning for warning in merged[0].warnings)


def test_normalize_mineru_markdown_keeps_html_spans_and_pipe_rows() -> None:
    markdown = """# Trial title
<!-- page: 2 -->
## Results
Table 1. Outcomes
<table><tr><th>Outcome</th><th>Group</th></tr><tr><td rowspan=2>Pain</td><td>A</td></tr><tr><td>B</td></tr></table>
| Outcome | Effect |
| --- | --- |
| Anxiety | -0.4 |
"""
    normalized = normalize_markdown_document(markdown, study_id="s", source_pdf=Path("p.pdf"), parser_backend="mineru:pipeline")
    assert len(normalized.tables) == 2
    assert normalized.tables[0].has_spans is True
    assert "rowspan" in normalized.tables[0].html
    assert normalized.tables[1].rows[-1] == ["Anxiety", "-0.4"]


def test_metadata_injection_is_copy_only_and_citation_anchored() -> None:
    chunk = DocumentChunk(
        study_id="2015-01", source_pdf=Path("paper.pdf"), page=1,
        text="Randomized trial", chunk_id="2015-01_P001_C0001", context_prefix="page=1",
    )
    metadata = BibliographicMetadata(doi="10.1234/example", title="Trial", journal="Journal", publication_year=2015)
    enriched = inject_bibliographic_metadata([chunk], metadata)[0]
    assert "DOI=10.1234/example" in enriched.context_prefix
    assert enriched.metadata["citation_id"] == "10.1234/example/2015-01_P001_C0001"
    assert chunk.context_prefix == "page=1"


def test_rcs_caps_candidates_and_llm_reranks_every_candidate() -> None:
    class FakeClient:
        def __init__(self):
            self.calls = []

        def chat_json(self, messages):
            self.calls.append(json.loads(messages[1]["content"]))
            return {"score": 0.8, "relevant": True, "contextual_summary": "supported result"}

    chunks = [
        DocumentChunk(
            study_id="s", source_pdf=Path("p.pdf"), page=index + 1,
            text=f"Pain outcome week {index}", chunk_id=f"s-{index}", context_prefix="results",
        ) for index in range(4)
    ]
    client = FakeClient()
    hits = RCSRetriever(chunks, client=client).gather("Pain outcome", top_k=2, candidate_pool=1000)
    assert len(hits) == 2
    assert len(client.calls) == 4
    assert all("candidate" in payload for payload in client.calls)


def test_contradiction_detection_preserves_both_source_values() -> None:
    class FakeClient:
        def chat_json(self, messages):
            return {"status": "conflict", "fields": ["claim_value"], "reason": "different reported rates"}

    chunks = [
        DocumentChunk(study_id="s", source_pdf=Path("p.pdf"), page=1, text="rate 10%", chunk_id="a", metadata={"claim_key": "response_rate", "claim_value": "10%"}),
        DocumentChunk(study_id="s", source_pdf=Path("p.pdf"), page=2, text="rate 20%", chunk_id="b", metadata={"claim_key": "response_rate", "claim_value": "20%"}),
    ]
    hits = RCSRetriever(chunks).gather("rate", top_k=2, rerank=False)
    records = detect_contradictions(hits, client=FakeClient())
    assert records and records[0].status == "conflict"
    assert records[0].chunk_ids == ["a", "b"]


def test_answer_generator_fallback_always_has_inline_citations() -> None:
    class FakeClient:
        def chat_json(self, messages):
            return {"answer": "Pain improved [cite: 10.1234/example/s-1]", "citation_ids": ["10.1234/example/s-1"]}

    chunk = DocumentChunk(study_id="s", source_pdf=Path("p.pdf"), page=1, text="Pain improved", chunk_id="s-1", metadata={"citation_id": "10.1234/example/s-1"})
    hits = RCSRetriever([chunk]).gather("Pain", top_k=1, rerank=False)
    answer = generate_evidence_answer("Pain", hits, client=FakeClient())
    assert "[cite:" in answer.answer
    assert answer.unsupported_citations == []


def test_metadata_resolver_is_injectable_and_does_not_require_network() -> None:
    calls = []

    def fetch(url: str):
        calls.append(url)
        if "crossref" in url:
            return {"message": {"DOI": "10.1234/example", "title": ["Trial"], "container-title": ["Journal"], "published": {"date-parts": [[2015]]}}}
        if "semanticscholar" in url:
            return {"title": "Trial", "year": 2015, "citationCount": 12, "isRetracted": False}
        return {"is_oa": True}

    metadata = MetadataResolver(fetch_json=fetch).resolve(title="Trial", doi="10.1234/example")
    assert metadata.doi == "10.1234/example"
    assert metadata.citation_count == 12
    assert metadata.retracted is False
    assert metadata.is_open_access is True
    assert len(calls) == 3


def test_baml_adapter_fallback_keeps_pydantic_wire_contract(tmp_path: Path) -> None:
    class FakeClient:
        def chat_json(self, messages):
            payload = json.loads(messages[1]["content"])
            assert payload["field_definitions"]["pydantic_json_schema"]
            return MetadataExtraction().model_dump()

    extractor = BamlExtractor(client=FakeClient(), raw_dir=tmp_path, generated_client=None)
    result = extractor.extract("metadata", MetadataExtraction, "# Title", PROMPT_SPECS["metadata"])
    assert result.title == "NR"
    assert extractor.backend_name == "openai-compatible-pydantic-fallback"


def test_baml_outcome_cache_is_scoped_to_each_table_shard(tmp_path: Path) -> None:
    class TinyOutcomes(BaseModel):
        outcomes: list[str]

    class GeneratedClient:
        def ExtractClinicalOutcomes(self, source_context: str):
            return {"outcomes": [source_context]}

    extractor = BamlExtractor(raw_dir=tmp_path, generated_client=GeneratedClient())
    first = extractor.extract("outcomes", TinyOutcomes, "table-1#part-01", {})
    second = extractor.extract("outcomes", TinyOutcomes, "table-1#part-02", {})
    assert first.outcomes != second.outcomes
    assert len(list(tmp_path.glob("outcomes.*.baml.json"))) == 2
