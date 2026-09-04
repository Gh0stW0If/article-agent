from __future__ import annotations

import argparse
import json

from .graph import run_pipeline
from .paths import TEMPLATE_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="article-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run MVP extraction")
    run.add_argument("--year")
    run.add_argument("--article-id")
    run.add_argument("--use-api", action="store_true", help="Call configured OpenAI-compatible API for extraction review.")
    run.add_argument(
        "--document-backend",
        choices=("pymupdf", "auto", "docling", "mineru"),
        default="pymupdf",
        help="Document parser route: auto audits the PDF and selects Docling or MinerU with a recorded fallback.",
    )
    ask = sub.add_parser("ask", help="Run evidence-linked RCS retrieval over one PDF")
    ask.add_argument("--pdf", required=True, help="Source PDF path")
    ask.add_argument("query", nargs="+", help="Question to answer")
    ask.add_argument("--top-k", type=int, default=5)
    ask.add_argument("--candidate-pool", type=int, default=1000)
    ask.add_argument("--use-api", action="store_true", help="Use configured API for reranking and answer generation")
    ask.add_argument("--external-metadata", action="store_true", help="Query Crossref/Semantic Scholar/Unpaywall")
    sub.add_parser("inspect-template", help="Print optimized template path")
    args = parser.parse_args(argv)

    if args.command == "inspect-template":
        print(TEMPLATE_PATH)
        return 0
    if args.command == "run":
        state = run_pipeline(
            year=args.year,
            article_id=args.article_id,
            use_api=args.use_api,
            document_backend=args.document_backend,
        )
        print(json.dumps({
            "articles": len(state.studies),
            "output_dir": str(state.output_dir),
            "studies": [s.study_id for s in state.studies],
            "review_items": len(state.review),
            "api_status": state.api_status,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "ask":
        from pathlib import Path

        from .document_pipeline import parse_pdf_hybrid
        from .evidence_engine import BibliographicMetadata, MetadataResolver
        from .models import OpenAICompatibleClient
        from .pdf_tools import answer_pdf_question

        pdf_path = Path(args.pdf)
        parsed, route, _normalized = parse_pdf_hybrid(pdf_path, output_dir=pdf_path.parent / ".article_agent_hybrid")
        client = OpenAICompatibleClient() if args.use_api else None
        metadata = BibliographicMetadata()
        if args.external_metadata:
            metadata = MetadataResolver().resolve(title="NR", doi="NR", allow_network=True)
        answer = answer_pdf_question(
            parsed,
            " ".join(args.query),
            client=client,
            metadata=metadata,
            top_k=max(1, args.top_k),
            candidate_pool=min(1000, max(1, args.candidate_pool)),
        )
        print(json.dumps({
            "route": route.model_dump(mode="json"),
            "answer": answer.model_dump(mode="json"),
        }, ensure_ascii=True, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
