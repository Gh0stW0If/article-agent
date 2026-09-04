from __future__ import annotations

import html
import json
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "mineru_method_2015_docling_baml_v1"
REPAIRED_TAG = "docling_baml_repaired"


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def unresolved_table_errors(raw_dir: Path) -> list[str]:
    """Return only errors for target parts still failed in the latest manifest.

    Older runs intentionally leave ``.error.txt`` files as transport
    provenance.  A stale error from a table that is now classified as
    baseline/safety (or has a replacement JSON cache) must not be counted as
    an unresolved outcome shard in the final report.
    """

    manifests = [
        raw_dir / "outcomes.tablewise.manifest.json",
        raw_dir / "outcomes.tablewise.retry-serial-10ms.manifest.json",
    ]
    latest = None
    for path in manifests:
        payload = load(path, {}) or {}
        if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
            if latest is None or path.stat().st_mtime >= latest[0]:
                latest = (path.stat().st_mtime, payload)
    if latest is not None:
        unresolved = []
        for table in latest[1].get("tables", []):
            if not isinstance(table, dict) or table.get("status") == "skipped":
                continue
            for part in table.get("parts", []) or []:
                if not isinstance(part, dict) or part.get("status") in {"success", "skipped"}:
                    continue
                cache_name = part.get("cache")
                if not cache_name:
                    continue
                cache_path = raw_dir / str(cache_name)
                if cache_path.exists():
                    continue
                error_path = cache_path.with_suffix(".error.txt")
                if error_path.exists():
                    unresolved.append(error_path.name)
        return sorted(set(unresolved))

    # Legacy output with no structured manifest: retain the old conservative
    # behavior, but still ignore errors paired with a valid cache.
    return sorted({
        path.name
        for path in raw_dir.glob("outcomes.table-*.error.txt")
        if not Path(str(path).replace(".error.txt", ".json")).exists()
    })


def main(output: Path | None = None, evaluation_tag: str | None = None) -> None:
    global OUTPUT
    if output is not None:
        OUTPUT = output.resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    module_names = ("metadata", "acupuncture", "risk_of_bias", "outcomes", "consort_flow")
    for index in range(1, 7):
        article_id = f"2015-{index:02d}"
        article_dir = OUTPUT / article_id
        # ``--evaluation-tag ""`` is an explicit request to use the fresh
        # untagged files produced by the current batch.  It must not silently
        # fall back to the historical repaired tag or an older cache.
        explicit_untagged = evaluation_tag == ""
        preferred_tag = REPAIRED_TAG if evaluation_tag is None else evaluation_tag
        repaired = article_dir / f"llm_evaluation.{preferred_tag}.json" if preferred_tag else article_dir / "__no_tag__.json"
        evaluation_path = (
            article_dir / "llm_evaluation.json"
            if explicit_untagged
            else (repaired if repaired.exists() else article_dir / "llm_evaluation.json")
        )
        repaired_exists = bool(not explicit_untagged and repaired.exists())
        evaluation = load(evaluation_path, {}) or {}
        extraction = load(article_dir / "extraction.json", {}) or {}
        postprocessed = load(article_dir / "outcomes.postprocessed.json", {}) or {}
        manifest = load(article_dir / "manifest.json", {}) or {}
        raw_dir = article_dir / "raw_module_responses"
        unresolved = unresolved_table_errors(raw_dir)
        audit_name = f"FIELD_AUDIT.{preferred_tag}.html" if repaired.exists() else "FIELD_AUDIT.html"
        retry_table = load(raw_dir / "outcomes.tablewise.retry-serial-10ms.manifest.json", {}) or {}
        retry_post = load(raw_dir / "outcomes.postprocess.retry-serial-10ms.manifest.json", {}) or {}
        outcomes = (extraction.get("outcomes") or {}).get("outcomes") or []
        # A tagged evaluation is only current when its outcome audit covered
        # the same raw source-record cardinality.  Resumed extraction runs can
        # append narrative/table rows while leaving an older score file in
        # place; expose that mismatch instead of presenting the cached score
        # as a fresh evaluation.
        outcome_audit = load(article_dir / f"llm_evaluation.{preferred_tag}.outcomes.json", {}) if preferred_tag else {}
        outcome_aggregation = outcome_audit.get("score_aggregation") if isinstance(outcome_audit, dict) else {}
        evaluated_outcome_count = outcome_aggregation.get("expected_source_index_count") if isinstance(outcome_aggregation, dict) else None
        evaluation_stale = (
            isinstance(evaluated_outcome_count, int)
            and evaluated_outcome_count != len(outcomes)
        )
        if evaluation_stale:
            evaluation_source = "stale_evaluation_record_count_mismatch"
        elif explicit_untagged and evaluation_path.exists():
            evaluation_source = "fresh_untagged_evaluation"
        elif repaired_exists:
            evaluation_source = "new_tagged_evaluation"
        else:
            evaluation_source = "cached_previous_evaluation"
        records.append({
            "article_id": article_id,
            "overall_score": evaluation.get("overall_score"),
            "module_scores": evaluation.get("module_scores") or {},
            "outcome_records": len(outcomes),
            "conflicts": postprocessed.get("conflict_count", 0),
            "unresolved_table_shards": unresolved,
            "parser_backend": manifest.get("parser_backend"),
            "evaluation_file": str(evaluation_path.relative_to(OUTPUT)),
            "field_audit": f"{article_id}/{audit_name}",
            "run_id": manifest.get("run_id"),
            "critical_errors": evaluation.get("critical_errors") or [],
            "evaluation_source": evaluation_source,
            "evaluated_outcome_count": evaluated_outcome_count,
            "evaluation_stale": evaluation_stale,
            "table_retry_status": retry_table.get("status", "not_run"),
            "postprocess_retry_status": retry_post.get("status", "not_run"),
            "postprocess_processed_count": retry_post.get("processed_outcome_count"),
        })

    scores = [row["overall_score"] for row in records if isinstance(row["overall_score"], (int, float))]
    module_averages = {
        name: round(sum(row["module_scores"].get(name, 0) for row in records) / len(records), 2)
        for name in module_names
    }
    docling_backends = {"docling", "provided-markdown"}
    outcome_mean = module_averages.get("outcomes", 0)
    outcome_threshold = 75
    overall_threshold = 85
    overall_mean = sum(scores) / len(scores) if scores else None
    summary = {
        "run_id": next((row.get("run_id") for row in records if row.get("run_id")), OUTPUT.name),
        "pipeline": "MinerU/Docling Markdown + luna semantic routing + deterministic structure + serial row extraction + conflict-preserving postprocess",
        "evaluation_tag": REPAIRED_TAG if evaluation_tag is None else evaluation_tag,
        "evaluation_note": (
            "本报告显式使用当前批次的未加标签评分文件。"
            if evaluation_tag == ""
            else "若新标签评价文件不存在，保留上一次独立LLM评分；当评分覆盖的原始结局记录数与当前 extraction.json 不一致时标记为 stale_evaluation_record_count_mismatch，不视为新评分。"
        ),
        "article_count": len(records),
        "scored_articles": len(scores),
        "mean_overall_score": round(sum(scores) / len(scores), 2) if scores else None,
        "min_overall_score": min(scores) if scores else None,
        "max_overall_score": max(scores) if scores else None,
        "module_average_scores": module_averages,
        "acceptance_thresholds": {
            "outcome_module_mean_gt": outcome_threshold,
            "overall_mean_gt": overall_threshold,
        },
        "acceptance": {
            "outcome_module_mean_pass": bool(outcome_mean > outcome_threshold),
            "overall_mean_pass": bool(overall_mean is not None and overall_mean > overall_threshold),
        },
        # ``provided-markdown`` is the explicit resume label for a cached
        # Docling conversion; it is still Docling-derived and must not make
        # the provenance summary falsely report a non-Docling run.
        "all_parser_backends_docling": all(row["parser_backend"] in docling_backends for row in records),
        "unresolved_table_shards": sum(len(row["unresolved_table_shards"]) for row in records),
        "records": records,
    }
    (OUTPUT / "FINAL_SCORE_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 2015 Docling + BAML 新流程最终评分",
        "",
        f"- 六篇平均综合分：**{summary['mean_overall_score']} / 100**",
        f"- run_id：`{summary['run_id']}`",
        f"- 分数范围：{summary['min_overall_score']}–{summary['max_overall_score']}",
        f"- Docling/缓存 Docling Markdown：{summary['all_parser_backends_docling']}",
        f"- 未解决表格分片：{summary['unresolved_table_shards']}",
        f"- 新评分标签：`{summary['evaluation_tag']}`（fresh_untagged 表示当前批次文件）",
        f"- 验收：结局均值 {outcome_mean} > {outcome_threshold}：**{'通过' if outcome_mean > outcome_threshold else '未通过'}**；"
        f"整体均值 {summary['mean_overall_score']} > {overall_threshold}：**{'通过' if scores and summary['mean_overall_score'] > overall_threshold else '未通过'}**",
        "",
        "| 文章 | 综合 | 元数据 | 针灸 | 偏倚 | 结局 | 流程图 | 结局记录 | 冲突 | 评分来源 | 表格恢复 | 后处理恢复 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in records:
        modules = row["module_scores"]
        lines.append(
            f"| {row['article_id']} | {row['overall_score']} | {modules.get('metadata')} | "
            f"{modules.get('acupuncture')} | {modules.get('risk_of_bias')} | "
            f"{modules.get('outcomes')} | {modules.get('consort_flow')} | "
            f"{row['outcome_records']} | {row['conflicts']} | {row['evaluation_source']} | "
            f"{row['table_retry_status']} | {row['postprocess_retry_status']} |"
        )
    lines += [
        "",
        "## 模块平均分",
        "",
        *[f"- {name}: {score}" for name, score in module_averages.items()],
    ]
    (OUTPUT / "FINAL_SCORE_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows_html = "".join(
        "<tr>"
        f"<td><a href='{html.escape(row['field_audit'])}'>{row['article_id']}</a></td>"
        f"<td class='score'>{row['overall_score']}</td>"
        + "".join(f"<td>{row['module_scores'].get(name, '—')}</td>" for name in module_names)
        + f"<td>{row['outcome_records']}</td><td>{row['conflicts']}</td>"
        + f"<td>{html.escape(row['evaluation_source'])}"
        + (f" ({row['evaluated_outcome_count']}/{row['outcome_records']})" if row.get('evaluation_stale') else "")
        + "</td>"
        + f"<td>{html.escape(row['table_retry_status'])}</td>"
        + f"<td>{html.escape(row['postprocess_retry_status'])}</td>"
        + "</tr>"
        for row in records
    )
    report = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>2015新流程最终评分</title>
<style>body{{max-width:1100px;margin:36px auto;padding:0 20px;background:#f5f7fb;color:#182235;font:15px/1.6 system-ui,'Microsoft YaHei',sans-serif}}.hero,table{{background:white;border:1px solid #dce3ed;border-radius:12px}}.hero{{padding:22px;margin-bottom:18px}}.big{{font-size:38px;font-weight:750;color:#245bd7}}table{{width:100%;border-collapse:collapse;overflow:hidden}}th,td{{padding:10px;border-bottom:1px solid #e7ebf1;text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{background:#eef3fb}}.score{{font-weight:700}}a{{color:#245bd7}}</style></head><body>
<div class='hero'><h1>2015 Docling + BAML 新流程最终评分</h1><div class='big'>{summary['mean_overall_score']} / 100</div><p>run_id：{html.escape(str(summary['run_id']))}</p><p>{summary['scored_articles']}/{summary['article_count']} 完成 · Docling/缓存 Markdown · 未解决表格分片 {summary['unresolved_table_shards']}</p><p>结局均值 {outcome_mean} &gt; {outcome_threshold}：<b>{'通过' if outcome_mean > outcome_threshold else '未通过'}</b>；整体均值 {summary['mean_overall_score']} &gt; {overall_threshold}：<b>{'通过' if scores and summary['mean_overall_score'] > overall_threshold else '未通过'}</b></p></div>
<table><thead><tr><th>文章</th><th>综合</th><th>元数据</th><th>针灸</th><th>偏倚</th><th>结局</th><th>流程图</th><th>结局记录</th><th>冲突</th><th>评分来源</th><th>表格恢复</th><th>后处理恢复</th></tr></thead><tbody>{rows_html}</tbody></table>
</body></html>"""
    (OUTPUT / "FINAL_SCORE_REPORT.html").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the 2015 final score report")
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    parser.add_argument("--evaluation-tag", default=None, help="Prefer this tagged evaluation; pass an empty string to use the current untagged batch only")
    args = parser.parse_args()
    main(args.output_root, args.evaluation_tag)
