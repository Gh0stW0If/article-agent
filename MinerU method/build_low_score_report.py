from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from evaluate_2015_01 import sheet1_gold, sheet3_gold


ARTICLE_IDS = ("2015-04", "2015-05")
FIELD_MODULES = {
    "metadata": (
        "title", "publication_year", "journal", "first_author", "country", "intervention", "control",
    ),
    "acupuncture": (
        "control_type_transformed", "treatment_frequency_raw", "treatment_frequency_value",
        "treatment_frequency_unit", "treatment_duration_raw", "treatment_duration_value",
        "treatment_duration_unit", "total_sessions", "deqi",
    ),
    "risk_of_bias": (
        "random_sequence_method", "random_sequence_class", "allocation_concealment",
        "allocation_concealment_class", "participant_blinding", "outcome_assessor_blinding",
        "primary_analysis", "missing_data_method",
    ),
    "consort_flow": (
        "randomized_sample_intervention_raw", "randomized_sample_control_raw", "total_randomized",
    ),
}
FIELD_LABELS = {
    "title": "标题", "publication_year": "发表年份", "journal": "期刊", "first_author": "第一作者",
    "country": "国家", "intervention": "干预", "control": "对照", "control_type_transformed": "对照类型编码",
    "treatment_frequency_raw": "治疗频率原文", "treatment_frequency_value": "治疗频率数值",
    "treatment_frequency_unit": "治疗频率单位", "treatment_duration_raw": "治疗疗程原文",
    "treatment_duration_value": "治疗疗程数值", "treatment_duration_unit": "治疗疗程单位",
    "total_sessions": "总治疗次数", "deqi": "得气（Deqi）", "random_sequence_method": "随机序列方法",
    "random_sequence_class": "随机序列分类", "allocation_concealment": "分配隐藏原文",
    "allocation_concealment_class": "分配隐藏分类", "participant_blinding": "参与者盲法",
    "outcome_assessor_blinding": "结局评估者盲法", "primary_analysis": "主要分析集",
    "missing_data_method": "缺失数据处理", "randomized_sample_intervention_raw": "干预组随机例数",
    "randomized_sample_control_raw": "对照组随机例数", "total_randomized": "总随机例数",
}
MODULE_LABELS = {
    "metadata": "基础信息", "acupuncture": "STRICTA 针灸", "risk_of_bias": "偏倚风险",
    "outcomes": "统计结局", "consort_flow": "CONSORT 流程图",
}
STATUS_LABELS = {
    "correct": "正确", "acceptable": "可接受", "incorrect": "错误", "missing": "缺失",
    "ambiguous": "金标准歧义", "gold_ambiguous": "金标准歧义",
}
OUTCOME_COLUMNS = (
    ("STUDYID", "研究ID"), ("OUTCOM", "结局"), ("INSTRU", "测量工具"), ("FOLTIM", "随访时间"),
    ("FOLTIMN", "时间数值"), ("BIESTI", "干预基线"), ("BNINTE", "干预基线n"),
    ("BCESTI", "对照基线"), ("BNCONT", "对照基线n"), ("EIESTI", "干预末次"),
    ("ENINTE", "干预末次n"), ("ECESTI", "对照末次"), ("ENCONT", "对照末次n"),
    ("EDEST", "组间效应"), ("EDLVAR", "效应下限"), ("EDUVAR", "效应上限"), ("PVALNUM", "P值"),
)


def display(value) -> str:
    if value is None:
        return "NR / 空值"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return str(value)


def esc(value) -> str:
    return html.escape(display(value), quote=True)


def norm(value):
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip()).lower()
    if isinstance(value, list):
        return sorted(norm(item) for item in value)
    if isinstance(value, dict):
        return {key: norm(child) for key, child in sorted(value.items())}
    return value


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module_audits(article_dir: Path) -> dict[str, dict]:
    audits = {}
    for module in (*FIELD_MODULES, "outcomes"):
        path = article_dir / f"llm_evaluation.{module}.json"
        if path.exists():
            audits[module] = load_json(path)
    return audits


def finding_index(audits: dict[str, dict]) -> dict[str, dict]:
    index = {}
    for audit in audits.values():
        for finding in audit.get("field_findings", []):
            raw_field = str(finding.get("field") or "").strip()
            # Most Sheet1 findings use slash-separated canonical fields.
            names = [part.strip() for part in raw_field.split("/") if re.fullmatch(r"[A-Za-z0-9_]+", part.strip())]
            for name in names or [raw_field]:
                index.setdefault(name, finding)
    return index


def candidate_field(data: dict, field: str):
    for module in (*FIELD_MODULES, "outcomes"):
        value = data.get(module)
        if isinstance(value, dict) and field in value:
            return value[field], module
    return None, None


def field_evidence(data: dict, field: str) -> list[str]:
    evidence = []
    for module in (*FIELD_MODULES, "outcomes"):
        value = data.get(module)
        if not isinstance(value, dict):
            continue
        for item in value.get("evidence", []) if isinstance(value.get("evidence"), list) else []:
            field_id = str(item.get("field_id") or "")
            if field_id == field or field in field_id.split("/"):
                quote = str(item.get("quote") or "").strip()
                if quote and quote not in evidence:
                    evidence.append(quote)
    return evidence


def status_for(field: str, candidate, gold, findings: dict[str, dict]) -> tuple[str, str]:
    finding = findings.get(field)
    if finding:
        raw_status = str(finding.get("status") or "acceptable")
        status = "ambiguous" if raw_status == "gold_ambiguous" else raw_status
        return status if status in STATUS_LABELS else "acceptable", str(finding.get("reason") or "见 LLM 字段审计。")
    if candidate is None or candidate == "NR" or candidate == []:
        if gold not in (None, "NR", []):
            return "missing", "候选为空而金标准有值；需回到原文确认是否为抽取漏失或金标准误填。"
        return "acceptable", "候选与金标准均未提供可用值。"
    if norm(candidate) == norm(gold):
        return "acceptable", "候选与金标准规范化后相同；未被 LLM 列为关键错误。"
    return "acceptable", "候选与金标准原始值不同；该差异需结合原文证据，不能仅凭 Excel 值判错。"


def render_score_cards(evaluation: dict) -> str:
    scores = [("综合", evaluation.get("overall_score"))]
    scores.extend((MODULE_LABELS.get(key, key), value) for key, value in evaluation.get("module_scores", {}).items())
    return "".join(
        f'<div class="score-card"><strong>{esc(value)}</strong><span>{html.escape(label)}</span></div>'
        for label, value in scores
    )


def render_field_table(data: dict, gold: dict, audits: dict[str, dict]) -> str:
    findings = finding_index(audits)
    rows = []
    for module, fields in FIELD_MODULES.items():
        for field in fields:
            candidate, candidate_module = candidate_field(data, field)
            gold_value = gold.get(field, {}).get("value") if field in gold else None
            status, reason = status_for(field, candidate, gold_value, findings)
            evidence = "；".join(field_evidence(data, field)) or "—"
            codebook = gold.get(field, {}).get("codebook") if field in gold else None
            codebook_text = str(codebook or "—")
            rows.append(
                "<tr>"
                f"<td>{html.escape(MODULE_LABELS.get(module, module))}</td>"
                f"<td><code>{html.escape(field)}</code><br><small>{html.escape(FIELD_LABELS.get(field, field))}</small></td>"
                f"<td>{esc(candidate)}</td><td>{esc(gold_value)}</td>"
                f"<td><span class=\"badge {html.escape(status)}\">{html.escape(STATUS_LABELS.get(status, status))}</span></td>"
                f"<td>{html.escape(reason)}</td><td>{html.escape(evidence)}</td>"
                f"<td>{html.escape(codebook_text)}</td></tr>"
            )
    return (
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>模块</th><th>字段</th><th>候选抽取</th><th>Excel 金标准</th><th>LLM判定</th>"
        "<th>判定原因</th><th>候选证据</th><th>代码本/备注</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def outcome_groups(outcomes: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for outcome in outcomes:
        key = (
            str(outcome.get("outcome_name") or "NR"),
            str(outcome.get("measurement_instrument") or "NR"),
            str(outcome.get("outcome_observation_timepoint_raw") or "NR"),
        )
        grouped[key].append(outcome)
    result = []
    for (name, instrument, timepoint), items in grouped.items():
        flags = []
        if len(items) > 1:
            flags.append(f"重复×{len(items)}")
        if instrument == "NR":
            flags.append("工具缺失")
        if timepoint == "NR":
            flags.append("时间点缺失")
        if any(item.get("intervention_estimate") is None or item.get("control_estimate") is None for item in items):
            flags.append("组别值不完整")
        if any(item.get("outcome_p_value") is None for item in items):
            flags.append("P值缺失")

        def arm_text(prefix: str) -> str:
            values = []
            for item in items:
                estimate = item.get(f"{prefix}_estimate")
                n = item.get(f"{prefix}_n")
                if estimate is not None or n is not None:
                    values.append(f"值={display(estimate)}, n={display(n)}")
            return "；".join(values) or "NR"

        p_values = [item.get("outcome_p_value") for item in items if item.get("outcome_p_value") is not None]
        quotes = []
        for item in items:
            for evidence in item.get("evidence", []):
                quote = str(evidence.get("quote") or "").strip()
                if quote and quote not in quotes:
                    quotes.append(quote)
        result.append({
            "name": name, "instrument": instrument, "timepoint": timepoint, "count": len(items),
            "flags": flags, "intervention": arm_text("intervention"), "control": arm_text("control"),
            "between": "; ".join(display(item.get("outcome_between_group_estimate")) for item in items),
            "p": "; ".join(display(value) for value in p_values) or "NR",
            "quote": "；".join(quotes) or "—",
        })
    return result


def render_outcome_group_table(outcomes: list[dict]) -> str:
    groups = outcome_groups(outcomes)
    rows = []
    for group in groups:
        flags = "；".join(group["flags"]) or "—"
        rows.append(
            "<tr>"
            f"<td>{esc(group['name'])}</td><td>{esc(group['instrument'])}</td><td>{esc(group['timepoint'])}</td>"
            f"<td>{group['count']}</td><td>{html.escape(flags)}</td><td>{esc(group['intervention'])}</td>"
            f"<td>{esc(group['control'])}</td><td>{esc(group['between'])}</td><td>{esc(group['p'])}</td>"
            f"<td>{esc(group['quote'])}</td></tr>"
        )
    return (
        f"<p>候选共有 <b>{len(outcomes)}</b> 条记录，归并为 <b>{len(groups)}</b> 个（结局名、工具、时间点）组合；"
        f"其中 <b>{sum(1 for item in groups if item['count'] > 1)}</b> 个组合存在重复记录。</p>"
        "<div class=\"table-wrap\"><table><thead><tr><th>结局名</th><th>工具</th><th>时间点</th>"
        "<th>记录数</th><th>诊断标记</th><th>干预侧值/n</th><th>对照侧值/n</th><th>组间效应</th><th>P值</th><th>证据摘录</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_gold_outcomes(rows: list[dict]) -> str:
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{esc(row.get(key))}</td>" for key, _ in OUTCOME_COLUMNS) + "</tr>")
    headers = "".join(f"<th>{html.escape(label)}<br><code>{html.escape(key)}</code></th>" for key, label in OUTCOME_COLUMNS)
    return (
        f"<p>Excel Sheet3 金标准记录数：<b>{len(rows)}</b>。注意：金标准行本身可能存在时间点、组别或样本量错配，报告中的金标准歧义需回查原文。</p>"
        f"<div class=\"table-wrap\"><table><thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def render_candidate_outcomes(outcomes: list[dict]) -> str:
    rows = []
    for index, item in enumerate(outcomes, 1):
        def arm(prefix: str) -> str:
            return f"值={display(item.get(prefix + '_estimate'))}; n={display(item.get(prefix + '_n'))}"
        between = f"{display(item.get('outcome_between_group_estimate'))} ({display(item.get('outcome_between_group_lower'))}, {display(item.get('outcome_between_group_upper'))})"
        p = f"{display(item.get('outcome_p_value_comparator'))}{display(item.get('outcome_p_value'))}"
        rows.append(
            "<tr>"
            f"<td>{index}</td><td>{esc(item.get('outcome_name'))}</td><td>{esc(item.get('measurement_instrument'))}</td>"
            f"<td>{esc(item.get('outcome_observation_timepoint_raw'))}</td><td>{esc(arm('intervention'))}</td>"
            f"<td>{esc(arm('control'))}</td><td>{esc(between)}</td><td>{esc(p)}</td>"
            f"<td>{esc((item.get('evidence') or [{}])[0].get('quote'))}</td></tr>"
        )
    return (
        f"<details><summary>展开查看候选全部结局记录（{len(outcomes)} 条）</summary>"
        "<div class=\"table-wrap\"><table><thead><tr><th>#</th><th>结局名</th><th>工具</th><th>时间点</th>"
        "<th>干预值/n</th><th>对照值/n</th><th>组间效应/CI</th><th>P值</th><th>证据</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>"
    )


def render_canonical_outcomes(dataset: dict | None) -> str:
    """Render the evidence-only canonical projection beside raw candidates."""

    if not isinstance(dataset, dict):
        return "<p>尚未生成独立 canonical outcome dataset；原始结局记录仍可审计。</p>"
    records = dataset.get("records", []) if isinstance(dataset.get("records", []), list) else []
    groups = dataset.get("conflict_groups", []) if isinstance(dataset.get("conflict_groups", []), list) else []
    rows = []
    for record in records:
        outcome = record.get("outcome", {}) if isinstance(record.get("outcome"), dict) else {}
        status = str(record.get("selection_status") or "unresolved")
        badge = "ambiguous" if status == "unresolved" else "incorrect" if status == "conflict" else "acceptable"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(record.get('canonical_id') or ''))}</code></td>"
            f"<td><span class=\"badge {badge}\">{html.escape(status)}</span></td>"
            f"<td>{esc(outcome.get('outcome_name'))}</td><td>{esc(outcome.get('measurement_instrument'))}</td>"
            f"<td>{esc(outcome.get('outcome_observation_timepoint_raw'))}</td>"
            f"<td>{esc(outcome.get('analysis_set'))}</td><td>{esc(outcome.get('record_role'))}</td>"
            f"<td>{esc(record.get('source_indices'))}</td><td>{esc(record.get('conflict_group_id'))}</td>"
            f"<td>{esc(record.get('selection_reason'))}</td></tr>"
        )
    return (
        f"<p>canonical 记录 <b>{len(records)}</b> 条；conflict group <b>{len(groups)}</b> 个。"
        "代表行仅用于导出和复核，不表示冲突已解决；所有 source_indices 均可回指原始记录。</p>"
        "<div class=\"table-wrap\"><table><thead><tr>"
        "<th>canonical_id</th><th>状态</th><th>结局</th><th>工具</th><th>时间点</th>"
        "<th>analysis_set</th><th>record_role</th><th>来源索引</th><th>conflict group</th><th>选择依据</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_findings(audits: dict[str, dict], module: str) -> str:
    audit = audits.get(module, {})
    findings = audit.get("field_findings", [])
    rows = []
    for item in findings:
        status = str(item.get("status") or "acceptable")
        status = "ambiguous" if status == "gold_ambiguous" else status
        rows.append(
            "<tr>"
            f"<td><span class=\"badge {html.escape(status)}\">{html.escape(STATUS_LABELS.get(status, status))}</span></td>"
            f"<td>{html.escape(str(item.get('severity') or ''))}</td><td><code>{html.escape(str(item.get('field') or ''))}</code></td>"
            f"<td>{html.escape(str(item.get('reason') or ''))}</td></tr>"
        )
    if not rows:
        return "<p>该模块没有单独字段发现。</p>"
    return (
        "<div class=\"table-wrap\"><table><thead><tr><th>状态</th><th>严重性</th><th>字段/结局</th><th>LLM 解释</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_article(article_id: str, article_dir: Path) -> str:
    data = load_json(article_dir / "extraction.json")
    evaluation = load_json(article_dir / "llm_evaluation.json")
    gold = sheet1_gold(article_id)
    gold_outcomes = sheet3_gold(article_id)
    audits = load_module_audits(article_dir)
    outcomes = data.get("outcomes", {}).get("outcomes", [])
    canonical_path = article_dir / "outcomes.canonical.json"
    canonical = load_json(canonical_path) if canonical_path.exists() else None
    manifest_path = article_dir / "raw_module_responses" / "outcomes.tablewise.manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    partial_tables = [item.get("table_id") for item in manifest.get("tables", []) if item.get("status") in {"partial", "failed"}]
    critical = evaluation.get("critical_errors", [])
    notes = evaluation.get("gold_quality_notes", [])
    next_actions = evaluation.get("next_actions", [])
    score = evaluation.get("overall_score")
    module_scores = evaluation.get("module_scores", {})
    table_status = f"{manifest.get('table_count', '—')} 张表 / {manifest.get('total_outcomes', len(outcomes))} 条候选结局"
    if partial_tables:
        table_status += f"；部分失败：{', '.join(map(str, partial_tables))}"

    return f"""
<article class="article" id="article-{html.escape(article_id)}">
  <div class="article-head"><div><h2>{html.escape(article_id)} · 低分原因</h2><p>{html.escape(table_status)}；金标准 Sheet3：{len(gold_outcomes)} 行</p></div>
    <div class="score-strip">{render_score_cards(evaluation)}</div></div>
  <section><h3>一眼结论</h3>
    <p class="verdict">{html.escape(str(evaluation.get('verdict') or ''))}</p>
    <div class="callout"><b>主要扣分模块：</b>统计结局 {esc(module_scores.get('outcomes'))} 分；CONSORT 流程 {esc(module_scores.get('consort_flow'))} 分。以下内容将候选抽取与 Excel 金标准并列，且保留 LLM 对金标准错误/歧义的提示。</div>
    <h4>LLM 关键错误清单</h4><ol class="issues">{''.join(f'<li>{html.escape(str(item))}</li>' for item in critical)}</ol>
  </section>
  <section><h3>Sheet1 字段对比：候选 vs Excel 金标准</h3>
    <p class="legend">“LLM 判定”优先采用逐模块审计；没有明确字段发现时，仅显示可接受/待复核，不把 Excel 不一致自动当作论文事实错误。</p>
    {render_field_table(data, gold, audits)}
  </section>
  <section><h3>统计结局（Sheet3）</h3>
    <h4>Excel 金标准行</h4>{render_gold_outcomes(gold_outcomes)}
    <h4>独立 canonical outcome dataset（不使用金标准回写）</h4>{render_canonical_outcomes(canonical)}
    <h4>候选按结局名 × 工具 × 时间点聚合</h4>{render_outcome_group_table(outcomes)}
    {render_candidate_outcomes(outcomes)}
    <h4>LLM 结局模块逐项诊断（{esc(module_scores.get('outcomes'))}/100）</h4>{render_findings(audits, 'outcomes')}
  </section>
  <section><h3>CONSORT 流程图对比（Sheet1）</h3>
    <div class="flow-compare"><div><b>候选 consort_flow</b><pre>{html.escape(json.dumps(data.get('consort_flow'), ensure_ascii=False, indent=2))}</pre></div><div><b>Excel 金标准相关字段</b><pre>{html.escape(json.dumps({field: gold.get(field, {}).get('value') for field in FIELD_MODULES['consort_flow']}, ensure_ascii=False, indent=2))}</pre></div></div>
    {render_findings(audits, 'consort_flow')}
  </section>
  <section><h3>金标准质量提示与建议</h3><h4>金标准可能的错误/歧义</h4><ul class="notes">{''.join(f'<li>{html.escape(str(item))}</li>' for item in notes)}</ul><h4>下一步修复</h4><ul class="actions">{''.join(f'<li>{html.escape(str(item))}</li>' for item in next_actions)}</ul></section>
</article>
"""


def build(output: Path, root: Path) -> None:
    articles = []
    for article_id in ARTICLE_IDS:
        article_dir = root / article_id
        if not (article_dir / "extraction.json").exists():
            continue
        articles.append(render_article(article_id, article_dir))
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>2015-04/05 低分原因与金标准对比</title><style>
:root{{--bg:#f3f6fb;--panel:#fff;--ink:#182437;--muted:#607089;--line:#dce4ef;--blue:#235bd6;--red:#b73939;--green:#10794e;--orange:#9b5d00;--purple:#7150aa}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}}header{{background:linear-gradient(120deg,#183678,#2d68db);color:#fff;padding:30px max(20px,calc((100vw - 1700px)/2))}}header h1{{margin:0 0 8px}}header p{{margin:4px 0;color:#dce8ff}}main{{max-width:1700px;margin:auto;padding:20px}}.topnav{{position:sticky;top:0;z-index:5;background:#f3f6fbed;padding:10px 0;display:flex;gap:9px;flex-wrap:wrap}}.topnav a{{background:var(--blue);color:#fff;border-radius:8px;text-decoration:none;padding:8px 13px}}.article{{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin:18px 0 35px;overflow:hidden;box-shadow:0 4px 18px #193b7410}}.article-head{{padding:18px 20px;background:#f9fbfe;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}}h2{{margin:0 0 4px}}h3{{margin:0;padding:14px 18px;background:#f9fbfe;border-bottom:1px solid var(--line);font-size:19px}}h4{{margin:18px 18px 8px}}section>p,section>ol,section>ul,section>.callout,section>.legend,section>.verdict,section>.table-wrap,section>details,section>.flow-compare{{margin-left:18px;margin-right:18px}}.score-strip{{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start}}.score-card{{min-width:90px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 12px;text-align:center}}.score-card strong{{display:block;font-size:22px;color:#173c88}}.score-card span{{font-size:12px;color:var(--muted)}}.verdict{{padding:12px 14px;background:#f7f9fc;border-left:4px solid var(--blue)}}.callout{{padding:12px 14px;background:#fff9e8;border:1px solid #ead58b;border-radius:9px}}.legend{{color:var(--muted)}}.issues,.notes,.actions{{padding-left:38px}}li{{margin:5px 0}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:9px;margin-bottom:16px}}table{{width:100%;border-collapse:collapse;min-width:1150px}}th,td{{padding:8px 9px;text-align:left;vertical-align:top;border-bottom:1px solid #edf1f6;overflow-wrap:anywhere;max-width:360px}}th{{font-size:12px;color:#536176;background:#f8fafc;white-space:nowrap}}tr:nth-child(even){{background:#fcfdff}}code{{color:#183c7b;background:#edf3fb;padding:2px 4px;border-radius:4px;font-size:12px}}small{{color:var(--muted)}}.badge{{font-weight:700;border-radius:999px;padding:3px 8px;white-space:nowrap;display:inline-block}}.correct{{color:var(--green);background:#e7f7ef}}.acceptable{{color:var(--orange);background:#fff2dd}}.ambiguous{{color:var(--purple);background:#f1ebfb}}.incorrect,.missing{{color:var(--red);background:#fdecec}}.flow-compare{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}pre{{white-space:pre-wrap;overflow:auto;background:#f7f9fc;border:1px solid var(--line);padding:10px;border-radius:8px;max-height:340px}}details{{margin-bottom:18px}}summary{{cursor:pointer;color:var(--blue);font-weight:700;padding:10px 0}}@media(max-width:900px){{.article-head{{display:block}}.score-strip{{margin-top:12px}}}}
</style></head><body><header><h1>2015-04 / 2015-05 低分原因与金标准对比</h1><p>逐表逐行结局抽取 · LLM 分模块审计 · Excel Sheet1/Sheet3 并列 · 允许推导但禁止猜测</p><p>阅读提示：金标准可能有错配或编码歧义，报告同时展示 LLM 的 gold_quality_notes。</p></header><main><nav class="topnav"><a href="#article-2015-04">2015-04（58分）</a><a href="#article-2015-05">2015-05（48分）</a><a href="BATCH_INDEX.html">返回批量索引</a></nav>{''.join(articles)}</main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a low-score comparison report for 2015-04 and 2015-05")
    parser.add_argument("--root", type=Path, default=ROOT / "outputs/mineru_method_2015_tablewise_v2")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/mineru_method_2015_tablewise_v2/LOW_SCORE_2015_04_05.html")
    args = parser.parse_args()
    build(args.output.resolve(), args.root.resolve())
    print(args.output.resolve())
