from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from build_field_audit import build as build_field_audit
from evaluate_2015_01 import evaluate
from mineru_method import run_experiment


def article_id(path: Path) -> str:
    return path.stem.lstrip("-")


def find_markdown(source_roots: list[Path], target_id: str) -> Path | None:
    candidates: list[Path] = []
    for root in source_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            if target_id in path.name or target_id in str(path.parent):
                candidates.append(path)
    return max(candidates, key=lambda path: path.stat().st_size) if candidates else None


def extraction_is_complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        outcome_rows = data.get("outcomes", {}).get("outcomes")
        if not outcome_rows:
            return False
        # Rerun artifacts produced before the explicit source-layer fields
        # were added; otherwise a resume would preserve a structurally valid
        # but lossy OutcomeStatistic projection.
        if any(
            not isinstance(item, dict)
            or any(field not in item for field in ("source_values", "source_evidence", "derived", "derivation"))
            for item in outcome_rows
        ):
            return False
        # A non-empty extraction is not sufficient: a table can have valid
        # rows plus one failed shard.  Resume must replay any article whose
        # latest lossless manifest still reports missing/partial coverage.
        tablewise_path = path.parent / "raw_module_responses" / "outcomes.tablewise.manifest.json"
        if tablewise_path.exists():
            tablewise = json.loads(tablewise_path.read_text(encoding="utf-8"))
            for table in tablewise.get("tables", []) if isinstance(tablewise, dict) else []:
                if not isinstance(table, dict) or table.get("status") == "skipped":
                    continue
                if table.get("missing_row_ids"):
                    return False
                if any(
                    isinstance(part, dict) and part.get("status") not in {"success", "skipped"}
                    for part in (table.get("parts") or [])
                ):
                    return False
            # Results prose is a separate evidence source.  Before the
            # narrative-cache isolation fix, an old empty ``outcomes.table``
            # cache could report complete row coverage with zero outcomes.
            # Force one fresh narrative pass on resume; after that pass an
            # honest zero remains reviewable in LOSSLESS_QA rather than being
            # silently replaced by an older response.
            narrative_path = path.parent / "raw_module_responses" / "narrative" / "outcomes.narrative.manifest.json"
            if narrative_path.exists():
                narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
                if isinstance(narrative, dict):
                    candidate_count = int(narrative.get("candidate_paragraph_count") or 0)
                    narrative_count = int(tablewise.get("narrative_outcome_count") or 0)
                    cache_policy = str(narrative.get("cache_policy") or "")
                    if candidate_count > 0 and narrative_count == 0 and cache_policy != "forced_fresh":
                        return False
        return True
    except (OSError, ValueError, TypeError):
        return False


def write_summary(records: list[dict], output_root: Path) -> None:
    summary = {
        "run_id": os.getenv("ARTICLE_AGENT_RUN_ID", output_root.name),
        "year": 2015,
        "article_count": len(records),
        "extraction_success": sum(item.get("extraction_status") == "success" for item in records),
        "evaluation_success": sum(item.get("evaluation_status") == "success" for item in records),
        "records": records,
    }
    (output_root / "BATCH_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 2015 年文章批量运行汇总",
        "",
        f"- 文章数：{summary['article_count']}",
        f"- 抽取成功：{summary['extraction_success']}",
        f"- LLM 评价成功：{summary['evaluation_success']}",
        "",
        "| 文章 | MinerU Markdown | 抽取 | LLM评价 | 综合分 | 用时(s) | 错误 |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for item in records:
        lines.append(
            "| {article_id} | {markdown_status} | {extraction_status} | {evaluation_status} | "
            "{overall_score} | {elapsed_seconds} | {error} |".format(
                **{**item, "error": str(item.get("error") or "").replace("|", "\\|").replace("\n", " ")}
            )
        )
    (output_root / "BATCH_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cards = "".join(
        f"<article><h2>{html.escape(item['article_id'])}</h2>"
        f"<p>抽取：<b>{html.escape(item['extraction_status'])}</b> · "
        f"LLM评价：<b>{html.escape(item['evaluation_status'])}</b> · "
        f"综合分：<b>{html.escape(str(item.get('overall_score') or '—'))}</b></p>"
        + (
            f"<a href=\"{html.escape(item['article_id'])}/FIELD_AUDIT.html\">查看全部字段正误</a>"
            if item.get("evaluation_status") == "success" else ""
        )
        + (f"<pre>{html.escape(str(item.get('error')))}</pre>" if item.get("error") else "")
        + "</article>"
        for item in records
    )
    index = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>2015批量抽取审计</title>
<style>body{{max-width:1100px;margin:40px auto;padding:0 20px;background:#f4f7fb;color:#172235;font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}}h1{{margin-bottom:4px}}.summary{{color:#56657a}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:22px}}article{{background:#fff;border:1px solid #dce4ef;border-radius:12px;padding:18px}}h2{{margin:0}}a{{display:inline-block;background:#245bd7;color:white;text-decoration:none;border-radius:8px;padding:8px 12px}}pre{{white-space:pre-wrap;color:#a12929}}</style></head><body>
<h1>2015 年 6 篇 RCT 批量抽取审计</h1><div class="summary">抽取成功 {summary['extraction_success']}/{summary['article_count']} · LLM评价成功 {summary['evaluation_success']}/{summary['article_count']}</div><main>{cards}</main></body></html>"""
    (output_root / "BATCH_INDEX.html").write_text(index, encoding="utf-8")


def main() -> int:
    # Windows terminals may default to GBK while transport diagnostics contain
    # UTF-8 replacement characters.  Logging must never terminate the batch.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Run modular extraction and LLM audit for all 2015 PDFs")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/mineru_method_2015_batch")
    parser.add_argument("--sources", type=Path, action="append")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--no-vlm", action="store_true")
    parser.add_argument("--parser", choices=("auto", "mineru", "docling", "pymupdf"), default="auto")
    parser.add_argument("--force-backend", choices=("docling", "mineru", "pymupdf"))
    parser.add_argument(
        "--articles",
        nargs="*",
        default=None,
        help="Optional article IDs to process; default runs all PDFs in the 2015 source directory",
    )
    parser.add_argument("--resume", action="store_true", help="Reuse completed extraction/evaluation files")
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    # One batch-wide identifier is propagated into every article manifest and
    # later evaluation/report files.  A resume keeps the existing ID so a
    # resumed run cannot silently mix artifacts from separate batches.
    run_id_path = output_root / "RUN_ID.txt"
    if args.resume and run_id_path.exists():
        run_id = run_id_path.read_text(encoding="utf-8", errors="replace").strip()
    else:
        run_id = "lossless-2015-" + uuid.uuid4().hex[:12]
        run_id_path.write_text(run_id + "\n", encoding="utf-8")
    os.environ["ARTICLE_AGENT_RUN_ID"] = run_id
    source_roots = args.sources or [
        ROOT / "outputs/mineru_method_2015_sources",
        ROOT / "outputs/mineru_method_retest",
    ]
    pdfs = sorted((ROOT / "Datas/articles/2015").glob("*.pdf"))
    if args.articles:
        requested = {str(value).lstrip("-") for value in args.articles}
        pdfs = [pdf for pdf in pdfs if article_id(pdf) in requested]
    records: list[dict] = []

    for pdf in pdfs:
        target_id = article_id(pdf)
        started = time.monotonic()
        # Existing MinerU Markdown remains available as an explicit fast path.
        # Auto/Docling runs parse the PDF afresh unless a prior Docling
        # Markdown artifact is explicitly reused below; the latter is labelled
        # as cached so provenance is never misrepresented.
        markdown = find_markdown(source_roots, target_id) if args.parser == "mineru" else None
        cached_docling_markdown = None
        if args.resume and args.parser == "docling":
            # A previous Docling conversion is already a lossless local
            # artifact.  Reusing it on resume avoids re-downloading Docling's
            # HuggingFace layout model (which can fail independently of the
            # extraction API) and keeps the table context stable.  The
            # resulting manifest is labelled ``provided-markdown`` so the
            # provenance is explicit rather than pretending a fresh parse.
            candidate = output_root / target_id / "hybrid" / "docling" / "docling.md"
            if candidate.exists() and candidate.stat().st_size:
                cached_docling_markdown = candidate
                markdown = candidate
        record = {
            "article_id": target_id,
            "pdf": str(pdf.resolve()),
            "markdown": str(markdown.resolve()) if markdown else None,
            "markdown_status": "cached" if cached_docling_markdown else ("provided" if markdown else "generated"),
            "extraction_status": "not_run",
            "evaluation_status": "not_run",
            "overall_score": None,
            "elapsed_seconds": 0,
            "error": None,
        }
        try:
            extraction_file = output_root / target_id / "extraction.json"
            if not (args.resume and extraction_is_complete(extraction_file)):
                result = run_experiment(
                    pdf=pdf,
                    project_root=ROOT,
                    output_root=output_root,
                    parser=args.parser,
                    markdown_path=cached_docling_markdown or markdown,
                    use_api=True,
                    use_vlm=not args.no_vlm,
                    force_backend=args.force_backend,
                )
                if result is None:
                    raise RuntimeError("Extraction unexpectedly returned no bundle")
            record["extraction_status"] = "success"
            if not args.skip_evaluation:
                evaluation_file = output_root / target_id / "llm_evaluation.json"
                evaluation = (
                    json.loads(evaluation_file.read_text(encoding="utf-8"))
                    if args.resume and evaluation_file.exists()
                    else evaluate(output_root / target_id, use_postprocessed=True)
                )
                record["evaluation_status"] = "success"
                record["overall_score"] = evaluation.get("overall_score")
                build_field_audit(
                    output_root / target_id / "extraction.json",
                    output_root / target_id / "llm_evaluation.json",
                    output_root / target_id / "FIELD_AUDIT.html",
                )
            else:
                record["evaluation_status"] = "skipped"
        except Exception as exc:  # keep the remaining articles running
            record["error"] = f"{type(exc).__name__}: {exc}"
            if record["extraction_status"] == "success":
                record["evaluation_status"] = "failed"
            else:
                record["extraction_status"] = "failed"
            article_dir = output_root / target_id
            article_dir.mkdir(parents=True, exist_ok=True)
            (article_dir / "batch_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 1)
            records.append(record)
            write_summary(records, output_root)
            print(json.dumps(record, ensure_ascii=False), flush=True)

    return 0 if all(item["extraction_status"] == "success" for item in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
