"""Build a provenance/coverage audit for a lossless 2015 batch.

The report is intentionally independent of the Gold workbook.  It checks the
request manifests and source datasets for coverage, duplicate source indices,
missing row acknowledgements, and accidental legacy cache mixing.  It never
changes an extracted value or score.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _source_outcomes(article_dir: Path) -> list[dict]:
    extraction = _read_json(article_dir / "extraction.json")
    outcomes = extraction.get("outcomes", {}).get("outcomes", [])
    return [item for item in outcomes if isinstance(item, dict)]


def audit_article(article_dir: Path) -> dict:
    extraction_path = article_dir / "extraction.json"
    outcomes = _source_outcomes(article_dir)
    tablewise = _read_json(article_dir / "raw_module_responses" / "outcomes.tablewise.manifest.json")
    requests = _jsonl(article_dir / "raw_module_responses" / "request_manifest.jsonl")
    statuses = {"success": 0, "partial": 0, "failed": 0, "timeout": 0, "invalid": 0}
    missing: list[str] = []
    covered: set[str] = set()
    requested: set[str] = set()
    request_ids: list[str] = []
    request_run_ids: set[str] = set()
    for item in requests:
        request_id = str(item.get("request_id") or "")
        if request_id:
            request_ids.append(request_id)
        request_run_id = str(item.get("run_id") or "")
        if request_run_id:
            request_run_ids.add(request_run_id)
        for row_id in item.get("row_ids", []) if isinstance(item.get("row_ids"), list) else []:
            requested.add(str(row_id))
        for row_id in item.get("covered_row_ids", []) if isinstance(item.get("covered_row_ids"), list) else []:
            covered.add(str(row_id))
        status = str(item.get("response_status") or item.get("status") or "unknown").lower()
        if status in statuses:
            statuses[status] += 1
        elif status in {"success", "partial", "failed"}:
            statuses[status] += 1
    # The tablewise manifest is the source inventory.  Include every part's
    # declared row IDs so a legacy retry that rewrote request_manifest.jsonl
    # cannot make the QA report appear complete by simply omitting rows.
    for table in tablewise.get("tables", []) if isinstance(tablewise.get("tables"), list) else []:
        if not isinstance(table, dict) or str(table.get("status") or "").lower() == "skipped":
            continue
        for part in table.get("parts", []) if isinstance(table.get("parts"), list) else []:
            if not isinstance(part, dict):
                continue
            requested.update(
                str(value) for value in (part.get("row_ids") or [])
                if value not in (None, "", "NR")
            )
            covered.update(
                str(value) for value in (part.get("covered_row_ids") or [])
                if value not in (None, "", "NR")
            )
        covered.update(
            str(value) for value in (table.get("covered_row_ids") or [])
            if value not in (None, "", "NR")
        )
    # Results-narrative retries are stored separately from the table list;
    # fold their stable row acknowledgements into the same coverage set.
    for path in (
        article_dir / "raw_module_responses" / "narrative" / "outcomes.narrative.manifest.json",
        article_dir / "raw_module_responses" / "outcomes.narrative.retry-serial-10ms.manifest.json",
    ):
        payload = _read_json(path)
        parts = payload.get("manifest") if isinstance(payload, dict) else None
        for item in parts if isinstance(parts, list) else []:
            if not isinstance(item, dict):
                continue
            for key in ("row_ids", "covered_row_ids", "missing_row_ids"):
                values = item.get(key)
                if not isinstance(values, list):
                    continue
                requested.update(
                    str(value) for value in values
                    if value not in (None, "", "NR")
                )
                if key == "covered_row_ids":
                    covered.update(str(value) for value in values if value not in (None, "", "NR"))
            for part in item.get("parts", []) if isinstance(item.get("parts"), list) else []:
                if not isinstance(part, dict):
                    continue
                requested.update(str(value) for value in (part.get("row_ids") or []) if value not in (None, "", "NR"))
                covered.update(str(value) for value in (part.get("covered_row_ids") or []) if value not in (None, "", "NR"))
    for table in tablewise.get("tables", []) if isinstance(tablewise.get("tables"), list) else []:
        if not isinstance(table, dict):
            continue
        # A deterministic classifier may explicitly mark a baseline,
        # administrative, or empty table as skipped.  Its empty target set is
        # a covered routing decision, not an uncovered outcome row.
        if str(table.get("status") or "").lower() == "skipped":
            continue
        for row_id in table.get("missing_row_ids", []) if isinstance(table.get("missing_row_ids"), list) else []:
            # The tablewise summary may be from an earlier attempt.  A later
            # append-only retry is authoritative for the row when its stable
            # row_id is acknowledged in the request manifest; do not report
            # a stale summary as an uncovered row.
            value = str(row_id)
            if value not in covered:
                missing.append(value)
    # The request manifest is append-only and therefore remains authoritative
    # when a later retry updates the tablewise summary.  Reconcile every
    # requested row against every successful acknowledgement so stale failed
    # attempts cannot hide an uncovered row behind a nominal table status.
    missing.extend(sorted(requested - covered))
    outcome_row_ids = [str(item.get("row_id") or "NR") for item in outcomes]
    duplicate_source_rows = len(outcome_row_ids) - len(set(outcome_row_ids))
    raw_count = len(outcomes)
    postprocessed = _read_json(article_dir / "outcomes.postprocessed.json")
    post_records = [item for item in (postprocessed.get("records") or []) if isinstance(item, dict)]
    post_record_count = len(post_records)
    processed_count = int(postprocessed.get("processed_outcome_count") or 0)
    unresolved_count = sum(
        1 for item in post_records
        if str(item.get("annotation_status") or item.get("conflict_status") or "").lower()
        in {"unresolved", "not_checked"}
    )
    article_manifest = _read_json(article_dir / "manifest.json")
    article_run_id = str(article_manifest.get("run_id") or "")
    required_source_fields = (
        "table_id", "row_id", "arm", "comparison", "analysis_set", "record_role",
        "source_values", "source_evidence", "derived", "derivation",
    )
    source_field_errors = [
        f"source outcome {index} missing: {', '.join(field for field in required_source_fields if field not in item)}"
        for index, item in enumerate(outcomes)
        if any(field not in item for field in required_source_fields)
    ]
    narrative_path = article_dir / "raw_module_responses" / "narrative" / "outcomes.narrative.manifest.json"
    narrative_manifest = _read_json(narrative_path)
    errors = []
    if not extraction_path.exists():
        errors.append("extraction.json missing")
    if not requests:
        errors.append("request_manifest.jsonl missing or empty")
    if missing:
        errors.append(f"uncovered source rows: {len(sorted(set(missing)))}")
    if any(not item.get("lossless", False) for item in requests):
        errors.append("request without lossless=true")
    if len(request_ids) != len(set(request_ids)):
        errors.append("duplicate request_id in request_manifest.jsonl")
    if article_run_id and any(run_id not in {article_run_id, "NR"} for run_id in request_run_ids):
        errors.append("request manifest mixes run_id values")
    if any(not item.get("input_sha256") for item in requests):
        errors.append("request without input_sha256")
    if source_field_errors:
        errors.append(f"source provenance fields missing: {len(source_field_errors)} records")
    if post_record_count > raw_count:
        errors.append("postprocessed record count exceeds source count")
    if raw_count and post_record_count != raw_count:
        errors.append(f"postprocessed record count does not cover source count: {post_record_count}/{raw_count}")
    if tablewise and int(tablewise.get("total_outcomes") or 0) != raw_count:
        errors.append("tablewise total_outcomes differs from extraction source count")
    if isinstance(narrative_manifest, dict):
        candidate_count = int(narrative_manifest.get("candidate_paragraph_count") or 0)
        narrative_count = int(tablewise.get("narrative_outcome_count") or 0)
        if candidate_count > 0 and narrative_count == 0 and narrative_manifest.get("cache_policy") != "forced_fresh":
            errors.append("narrative outcome count is zero under a reusable cache policy")
    postprocess_manifest = _read_json(article_dir / "raw_module_responses" / "outcomes.postprocess.manifest.json")
    postprocess_parts = postprocess_manifest.get("parts", []) if isinstance(postprocess_manifest, dict) else []
    postprocess_failed = sum(
        1 for part in postprocess_parts if isinstance(part, dict) and str(part.get("status")) not in {"success", "skipped", "failed_cached"}
    )
    if postprocess_failed:
        errors.append(f"postprocess parts not successful: {postprocess_failed}")
    return {
        "article_id": article_dir.name,
        "run_id": _read_json(article_dir / "manifest.json").get("run_id"),
        "extraction_present": extraction_path.exists(),
        "source_outcome_count": raw_count,
        "postprocessed_outcome_count": post_record_count,
        "postprocessed_processed_count": processed_count,
        "postprocessed_unresolved_count": unresolved_count,
        "request_count": len(requests),
        "requested_row_count": len(requested),
        "covered_row_count": len(covered),
        "missing_row_ids": sorted(set(missing)),
        "duplicate_source_row_count": duplicate_source_rows,
        "source_field_errors": source_field_errors,
        "narrative_candidate_paragraph_count": int(narrative_manifest.get("candidate_paragraph_count") or 0) if isinstance(narrative_manifest, dict) else 0,
        "narrative_outcome_count": int(tablewise.get("narrative_outcome_count") or 0),
        "postprocess_failed_part_count": postprocess_failed,
        "request_status_counts": statuses,
        "table_manifest_status": tablewise.get("tables", []),
        "errors": errors,
        "status": "PASS" if not errors else "REVIEW",
    }


def build(output_root: Path) -> dict:
    articles = [audit_article(output_root / f"2015-{index:02d}") for index in range(1, 7)]
    run_ids = sorted({str(item.get("run_id")) for item in articles if item.get("run_id")})
    summary = {
        "run_id": run_ids[0] if len(run_ids) == 1 else None,
        "run_ids": run_ids,
        "article_count": len(articles),
        "pass_count": sum(item["status"] == "PASS" for item in articles),
        "review_count": sum(item["status"] != "PASS" for item in articles),
        "all_request_inputs_lossless": all(
            not any("request without lossless=true" in error for error in item["errors"])
            for item in articles
        ),
        "articles": articles,
    }
    (output_root / "LOSSLESS_QA.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cards = []
    for item in articles:
        errors = "<br>".join(html.escape(str(error)) for error in item["errors"]) or "无未覆盖行或截断证据"
        missing = ", ".join(html.escape(str(value)) for value in item["missing_row_ids"]) or "—"
        cards.append(
            f"<article><h2>{html.escape(item['article_id'])} "
            f"<span class='{item['status'].lower()}'>{item['status']}</span></h2>"
            f"<p>原始结局 {item['source_outcome_count']} · 后处理记录 {item['postprocessed_outcome_count']} "
            f"（已处理 {item.get('postprocessed_processed_count', 0)} / unresolved {item.get('postprocessed_unresolved_count', 0)}）· "
            f"Results 正文候选 {item['narrative_candidate_paragraph_count']} / 结局 {item['narrative_outcome_count']} · "
            f"请求 {item['request_count']} · 请求行 {item['requested_row_count']} · 覆盖行 {item['covered_row_count']}</p>"
            f"<p>重复 source row：{item['duplicate_source_row_count']} · 来源字段缺失：{len(item['source_field_errors'])} · "
            f"后处理失败分片：{item['postprocess_failed_part_count']}<br>未覆盖：{missing}</p>"
            f"<p class='errors'>{errors}</p></article>"
        )
    document = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<title>Lossless QA</title><style>body{{font:15px/1.6 system-ui,'Microsoft YaHei',sans-serif;max-width:1100px;margin:30px auto;padding:0 18px;background:#f4f7fb;color:#172235}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}}article{{background:white;border:1px solid #d8e0eb;border-radius:10px;padding:15px}}h2{{margin:0 0 6px}}.pass{{color:#087443}}.review{{color:#a52b2b}}.errors{{color:#a52b2b}}</style></head>
<body><h1>无截断与来源覆盖审计</h1><p>run_id：{html.escape(str(summary.get('run_id') or '不一致/未写入'))} · 通过 {summary['pass_count']}/{summary['article_count']}</p><main>{''.join(cards)}</main></body></html>"""
    (output_root / "LOSSLESS_QA.html").write_text(document, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    summary = build(args.output_root.resolve())
    print(json.dumps({key: summary[key] for key in ("run_id", "article_count", "pass_count", "review_count")}, ensure_ascii=False))
    return 0 if summary["review_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
