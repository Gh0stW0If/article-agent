from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


LABELS = {
    "correct": "正确",
    "acceptable": "可接受",
    "ambiguous": "金标准歧义",
    "incorrect": "错误",
    "missing": "缺失",
}


def flatten(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key == "evidence" and isinstance(child, list):
                yield child_path, f"{len(child)} 条证据"
            else:
                yield from flatten(child, child_path)
    elif isinstance(value, list):
        if not value or all(not isinstance(item, (dict, list)) for item in value):
            yield path, value
        else:
            for index, child in enumerate(value):
                yield from flatten(child, f"{path}[{index}]")
    else:
        yield path, value


def module_for(path: str) -> str:
    if path.startswith("metadata"):
        return "基础信息"
    if path.startswith("acupuncture"):
        return "STRICTA针灸"
    if path.startswith("risk_of_bias"):
        return "偏倚风险"
    if path.startswith("outcomes"):
        return "统计结局"
    if path.startswith("consort_flow"):
        return "CONSORT流程"
    return "整体"


def finding_index(audit: dict) -> list[dict]:
    findings = []
    for module_name, module_audit in audit.get("module_audits", {}).items():
        if not isinstance(module_audit, dict):
            continue
        findings.extend(item for item in module_audit.get("field_findings", []) if isinstance(item, dict))
        # Lossless outcome evaluation stores field findings at row level so a
        # table/row error is not hidden by a document-wide summary.  Promote
        # those findings into the same lookup index while retaining their
        # source coordinates for the HTML audit payload.
        if module_name == "outcomes":
            for row_audit in module_audit.get("row_audits", []) or []:
                if not isinstance(row_audit, dict):
                    continue
                for finding in row_audit.get("field_findings", []) or []:
                    if not isinstance(finding, dict):
                        continue
                    enriched = dict(finding)
                    for key in ("source_index", "table_id", "row_id"):
                        if key in row_audit:
                            enriched.setdefault(key, row_audit[key])
                    findings.append(enriched)
    # Ordinary evaluator output stores per-module audits separately, so the caller
    # can optionally inject them under module_audits before building the page.
    return findings


def match_finding(path: str, findings: list[dict]) -> dict | None:
    leaf = path.rsplit(".", 1)[-1]
    leaf = leaf.split("[", 1)[0]
    for finding in findings:
        field = str(finding.get("field", "")).strip()
        if field and (field == path or field == leaf or path.endswith(f".{field}")):
            return finding
    return None


def judge(path: str, value, findings: list[dict]) -> tuple[str, str]:
    finding = match_finding(path, findings)
    if finding:
        status = str(finding.get("status", "acceptable"))
        status = "ambiguous" if status == "gold_ambiguous" else status
        if status not in LABELS:
            status = "acceptable"
        return status, str(finding.get("reason") or "见LLM字段审计。")
    if value is None or value == "NR" or value == []:
        return "missing", "候选未报告；可能是论文未明确说明，也可能是抽取漏失，需结合证据复核。"
    return "acceptable", "LLM关键错误清单未标记此字段；值已保留来源或结构化上下文，仍可人工复核。"


def reference(path: str) -> str:
    if path.endswith("evidence"):
        return "原文/图像/Crossref证据条数"
    return "见原文证据、人工金标准与LLM代码本审计"


def build(extraction: Path, evaluation: Path, output: Path) -> None:
    data = json.loads(extraction.read_text(encoding="utf-8"))
    audit = json.loads(evaluation.read_text(encoding="utf-8"))
    article_id = str(data.get("article_id") or extraction.parent.name)
    module_audits = {}
    suffix = evaluation.name.removeprefix("llm_evaluation").removesuffix(".json")
    for module in ("metadata", "acupuncture", "risk_of_bias", "outcomes", "consort_flow"):
        candidate = evaluation.parent / f"llm_evaluation{suffix}.{module}.json"
        if candidate.exists():
            module_audits[module] = json.loads(candidate.read_text(encoding="utf-8"))
    audit["module_audits"] = module_audits
    findings = finding_index(audit)
    rows = []
    for path, value in flatten(data):
        status, reason = judge(path, value, findings)
        rows.append({
            "module": module_for(path), "field": path, "value": value,
            "status": status, "reason": reason, "reference": reference(path),
        })
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    scores = audit.get("module_scores", {})
    score_cards = "".join(
        f'<div class="card"><b>{html.escape(str(score))}</b><span>{html.escape(name)}</span></div>'
        for name, score in (("综合", audit.get("overall_score")), *scores.items())
    )
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(article_id)} 全字段审计</title><style>
:root{{--bg:#f3f6fb;--panel:#fff;--ink:#172235;--line:#dce4ef;--blue:#245bd7;--green:#10794e;--orange:#aa6500;--purple:#7150aa}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}}
header{{padding:30px max(20px,calc((100vw - 1500px)/2));background:linear-gradient(120deg,#183678,#2d68db);color:white}}h1{{margin:0 0 8px}}header p{{margin:4px 0;color:#dce8ff}}
main{{max-width:1500px;margin:auto;padding:20px}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}.card{{background:white;border:1px solid var(--line);border-radius:11px;padding:13px}}.card b{{display:block;font-size:24px}}.card span{{color:#65748a}}
.note{{margin:16px 0;padding:12px 14px;background:#fff9e8;border:1px solid #ead58b;border-radius:9px}}.tools{{position:sticky;top:0;z-index:3;padding:10px 0;background:#f3f6fbf2;display:flex;gap:8px;flex-wrap:wrap}}
button,input,select{{border:1px solid var(--line);border-radius:8px;background:white;padding:8px 10px;font:inherit}}button.active{{background:var(--blue);color:white}}input{{flex:1;min-width:250px}}
section{{background:white;border:1px solid var(--line);border-radius:11px;margin:14px 0;overflow:hidden}}h2{{font-size:18px;margin:0;padding:13px;background:#f9fbfe;border-bottom:1px solid var(--line)}}.wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:1050px}}th,td{{padding:10px 11px;text-align:left;vertical-align:top;border-bottom:1px solid #edf1f6}}th{{font-size:12px;color:#536176;background:#f8fafc}}code{{color:#183c7b;background:#edf3fb;padding:2px 5px;border-radius:4px}}.badge{{font-weight:700;border-radius:999px;padding:3px 8px;white-space:nowrap}}.correct{{color:var(--green);background:#e7f7ef}}.acceptable{{color:var(--orange);background:#fff2dd}}.ambiguous{{color:var(--purple);background:#f1ebfb}}.incorrect,.missing{{color:#b73939;background:#fdecec}}td{{max-width:360px;overflow-wrap:anywhere}}@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><header><h1>{html.escape(article_id)} · 全字段正误审计</h1><p>允许可复算推导，禁止猜测 · DOI/Crossref书目检索 · 模块化证据路由 · CONSORT图文核对</p><p>LLM代码本审计：{audit.get('overall_score')}/100</p></header><main><div class="cards">{score_cards}</div>
<div class="note"><b>口径：</b>论文/Crossref证据优先于旧Excel金标准。LLM明确指出的字段显示为正确、错误或金标准歧义；未进入关键发现且非空的字段显示“可接受”，并不等同于已逐项人工确认。</div>
<div class="tools"><button class="active" data-s="all">全部</button><button data-s="correct">正确</button><button data-s="acceptable">可接受</button><button data-s="incorrect">错误</button><button data-s="ambiguous">金标准歧义</button><button data-s="missing">缺失</button><select id="module"><option value="all">全部模块</option></select><input id="q" placeholder="搜索字段、值、原因…"></div><div id="report"></div></main>
<script>const rows={payload};const labels={json.dumps(LABELS,ensure_ascii=False)};let status='all';const modules=[...new Set(rows.map(x=>x.module))];const moduleSel=document.querySelector('#module');modules.forEach(x=>moduleSel.insertAdjacentHTML('beforeend',`<option>${{x}}</option>`));const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));function render(){{const q=document.querySelector('#q').value.toLowerCase(),m=moduleSel.value;const f=rows.filter(x=>(status==='all'||x.status===status)&&(m==='all'||x.module===m)&&(!q||JSON.stringify(x).toLowerCase().includes(q)));document.querySelector('#report').innerHTML=modules.map(mod=>{{const list=f.filter(x=>x.module===mod);if(!list.length)return'';return`<section><h2>${{mod}} · ${{list.length}}字段</h2><div class="wrap"><table><thead><tr><th>字段路径</th><th>判定</th><th>候选值</th><th>参考</th><th>原因</th></tr></thead><tbody>${{list.map(x=>`<tr><td><code>${{esc(x.field)}}</code></td><td><span class="badge ${{x.status}}">${{labels[x.status]}}</span></td><td>${{esc(typeof x.value==='object'?JSON.stringify(x.value):x.value)}}</td><td>${{esc(x.reference)}}</td><td>${{esc(x.reason)}}</td></tr>`).join('')}}</tbody></table></div></section>`}}).join('')||'<section><h2>无匹配字段</h2></section>'}}document.querySelectorAll('button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');status=b.dataset.s;render()}});moduleSel.onchange=render;document.querySelector('#q').oninput=render;render();</script></body></html>"""
    output.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("extraction", type=Path)
    parser.add_argument("evaluation", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.extraction, args.evaluation, args.output)
