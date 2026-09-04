from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


MODULES = ("metadata", "acupuncture", "risk_of_bias", "outcomes", "consort_flow")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def outcome_score(postprocessed: dict) -> tuple[int, dict[str, int], float]:
    records = postprocessed.get("records", [])
    counts = Counter(str(record.get("conflict_status", "unresolved")) for record in records)
    total = len(records)
    weighted_correct = counts.get("none", 0) + 0.5 * counts.get("unresolved", 0)
    score = round(100 * weighted_correct / total) if total else 0
    return score, dict(counts), weighted_correct / total if total else 0.0


def score_article(article_dir: Path) -> dict:
    postprocessed = load(article_dir / "outcomes.postprocessed.json")
    prior = load(article_dir / "llm_evaluation.json")
    outcomes, status_counts, agreement = outcome_score(postprocessed)
    module_scores = {
        module: int(prior.get("module_scores", {}).get(module, 0))
        for module in MODULES
    }
    previous_outcomes = module_scores["outcomes"]
    module_scores["outcomes"] = outcomes
    overall = round(sum(module_scores.values()) / len(MODULES))
    return {
        "article_id": article_dir.name,
        "score_type": "offline_postprocessed_hybrid",
        "overall_score": overall,
        "module_scores": module_scores,
        "previous_llm_overall_score": prior.get("overall_score"),
        "previous_llm_outcomes_score": previous_outcomes,
        "outcome_score": outcomes,
        "outcome_status_counts": status_counts,
        "outcome_weighted_agreement": round(agreement, 6),
        "outcome_source_count": postprocessed.get("source_outcome_count", len(postprocessed.get("records", []))),
        "outcome_processed_count": postprocessed.get("processed_outcome_count", 0),
        "gold_conflict_count": len(postprocessed.get("gold_conflicts", [])),
        "scoring_notes": [
            "统计结局分由已完成的 LLM 后处理冲突标注离线计算：none=1、unresolved=0.5、conflict=0。",
            "metadata/acupuncture/risk_of_bias/consort_flow 未被本次后处理改变，沿用既有 LLM 模块分。",
            "完整的 postprocessed LLM 复评分请求因 API 网关 SSL 传输错误未完成；本分数不等同于新的独立 LLM 综合复审。",
            "原始 extraction.json 和 source_outcome 未参与改写。",
        ],
    }


def write_reports(results: list[dict], output_root: Path) -> None:
    payload = {
        "score_type": "offline_postprocessed_hybrid",
        "articles": results,
        "formula": {
            "outcome_score": "round(100 * (none + 0.5 * unresolved) / total_records)",
            "overall_score": "round(mean(metadata, acupuncture, risk_of_bias, outcomes, consort_flow))",
        },
    }
    (output_root / "OFFLINE_POSTPROCESSED_SCORE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 新后处理结果离线提取评分",
        "",
        "> 这是端点 SSL 传输失败时的可复核替代分：统计结局使用已完成的 LLM 后处理标注（none=1、unresolved=0.5、conflict=0），其余模块沿用既有 LLM 审计分；不等同于新的完整 LLM 复审分。",
        "",
        "| 文章 | 综合分 | 基础信息 | 针灸/干预 | 偏倚风险 | 统计结局（新） | CONSORT | 旧综合分 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        scores = item["module_scores"]
        lines.append(
            f"| {item['article_id']} | {item['overall_score']} | {scores['metadata']} | "
            f"{scores['acupuncture']} | {scores['risk_of_bias']} | {scores['outcomes']} | "
            f"{scores['consort_flow']} | {item['previous_llm_overall_score']} |"
        )
    lines.extend(["", "## 统计结局明细", ""])
    for item in results:
        lines.extend(
            [
                f"### {item['article_id']}",
                "",
                f"- 记录：{item['outcome_source_count']}；已处理：{item['outcome_processed_count']}；金标准缺失冲突：{item['gold_conflict_count']}",
                f"- 状态计数：`{json.dumps(item['outcome_status_counts'], ensure_ascii=False)}`",
                f"- 加权一致率：{item['outcome_weighted_agreement']:.3f}；统计结局分：{item['outcome_score']}",
                f"- 旧统计结局分：{item['previous_llm_outcomes_score']}；旧综合分：{item['previous_llm_overall_score']}",
                "",
            ]
        )
    (output_root / "OFFLINE_POSTPROCESSED_SCORE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "outputs" / "mineru_method_2015_tablewise_v2",
    )
    parser.add_argument("article", nargs="*", default=["2015-04", "2015-05"])
    args = parser.parse_args()
    results = [score_article(args.output_root / article) for article in args.article]
    write_reports(results, args.output_root)
    print(json.dumps({"articles": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
