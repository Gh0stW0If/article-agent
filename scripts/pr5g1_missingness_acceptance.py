"""Offline missingness-only projection, frozen-identity evaluation and PR5G2 handoff."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path

from article_agent.domain.models import ArticleExtraction, CanonicalField
from article_agent.evaluation.entity_matcher import GROUPS, entities
from article_agent.evaluation.hybrid import CachedSemanticJudge, HybridEvaluationReportV1
from article_agent.evaluation.hybrid.engine import evaluate_article_hybrid
from article_agent.evaluation.hybrid.semantic_judge import digest, write_json
from article_agent.missingness import resolve_missingness
from article_agent.missingness.resolver import FIELD_FAMILIES

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/2015-06/result_surface_v1"
SNAPSHOT = ROOT / "benchmarks/2015-06/missingness_v1"
FILES = ("REPORT.md", "SUMMARY.json", "CANONICAL_PREDICTION.json", "HYBRID_REPORT.json",
         "MISSINGNESS_DECISIONS.json", "MISSINGNESS_UNRESOLVED.json", "COVERAGE_PROOFS.json",
         "RUN_MANIFEST.json", "PR5G2_EXTRACTION_INPUT.json")
ATTRIBUTION = (
    "本 PR 的性能变化来自 missingness-state reasoning 的改善，即正确区分 "
    "NOT_REPORTED、NOT_APPLICABLE 和 UNRESOLVED；不代表提取到了新的 PDF 内容，"
    "也不代表 numerical extraction 能力提高。")


def predecessor():
    spec = importlib.util.spec_from_file_location("pr5g1_previous",
        ROOT / "scripts/pr5f2_result_surface_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def protected_hashes():
    prior = predecessor()
    hashes = prior.protected_hashes()
    paths = [*BASE.iterdir(), *(ROOT / "src/article_agent/result_surface").glob("*")]
    hashes.update({p.relative_to(ROOT).as_posix(): prior.sha(p) for p in paths if p.is_file()})
    return dict(sorted(hashes.items()))


def unresolved_missingness(report):
    return [f for f in report.field_results if f.in_hard_denominator
        and f.prediction_entity_id is not None and f.prediction_status == "UNRESOLVED"
        and f.gold_status in {"NOT_REPORTED", "NOT_APPLICABLE"}]


def verify_baseline(output):
    prior = predecessor()
    prior.verify_baseline(output / "previous")
    summary = prior.run(output, read(BASE / "SOURCE_SURFACE_CONTEXT.json"))
    for name in prior.FILES:
        if (output / name).read_bytes() != (BASE / name).read_bytes():
            raise RuntimeError("STOP: baseline byte drift: " + name)
    for key, pair in {
        "hybrid_hard_acceptable": (73, 271), "hybrid_production_coverage": (74, 165),
        "hybrid_supported_value_accuracy": (73, 74), "hybrid_status_accuracy": (99, 595),
    }.items():
        m = summary["after"][key]
        if (m["numerator"], m["denominator"]) != pair:
            raise RuntimeError("STOP: baseline metric drift: " + key)
    for kind, pair in {"ArmResult": (12, 21), "ComparisonResult": (10, 18), "Outcome": (3, 4)}.items():
        m = summary["after"]["hybrid_entity_metrics"][kind]
        if (m["matched"], m["gold"]) != pair:
            raise RuntimeError("STOP: baseline identity drift: " + kind)
    if (summary["hard_failures_after"]["identity_unresolved"] != 105
        or summary["missingness_hard_counts"] != {"NOT_REPORTED": 34, "NOT_APPLICABLE": 24}):
        raise RuntimeError("STOP: baseline backlog drift")


def scope_check(raw, projected, decisions):
    changed = {(d["entity_type"], d["entity_id"], d["field"]): d
               for d in decisions if d["changed"]}
    assert raw.evidence == projected.evidence[:len(raw.evidence)]
    assert raw.adapter_warnings == projected.adapter_warnings
    for kind in GROUPS:
        a, b = entities(raw, kind), entities(projected, kind)
        assert a.keys() == b.keys(), "STOP: identity change"
        for entity_id, old in a.items():
            new = b[entity_id]
            for name in type(old).model_fields:
                before, after = getattr(old, name), getattr(new, name)
                if name == "legacy_fields":
                    saved = dict(after)
                    saved.pop("missingness", None)
                    assert saved == before, "STOP: original source representation changed"
                elif (kind, entity_id, name) in changed:
                    assert name in FIELD_FAMILIES[kind][2]
                    assert before.status == "UNRESOLVED"
                    assert after.status in {"NOT_REPORTED", "NOT_APPLICABLE"} and after.value is None
                    assert before.raw_value == after.raw_value
                    assert new.legacy_fields["missingness"]["raw_fields"][name] == before.model_dump(mode="json")
                else:
                    assert before == after, "STOP: non-missingness field changed"
                if isinstance(before, CanonicalField) and before.status == "PRESENT":
                    assert before == after, "STOP: PRESENT changed"
    for name in ("schema_version", "source_format", "source_record_id", "parser_backend"):
        assert getattr(raw, name) == getattr(projected, name)
    ArticleExtraction.model_validate_json(projected.model_dump_json())


def extraction_handoff(report):
    """Evaluation-side diagnostics only; never input to the production resolver."""
    return [f.model_dump(mode="json") for f in report.field_results
        if f.in_hard_denominator and f.gold_status == "PRESENT"
        and f.prediction_entity_id is not None
        and f.prediction_status in {"UNRESOLVED", "INSUFFICIENT_CONTEXT"}
        and f.prediction_value is None and f.hybrid_classification == "NOT_EXTRACTED"]


def run(output):
    initial = protected_hashes()
    prior = predecessor()
    raw = ArticleExtraction.model_validate(read(BASE / "CANONICAL_PREDICTION.json"))
    original = raw.model_dump_json()
    # No Gold, evaluation outcomes, matched IDs or expected statuses are passed.
    # These production inputs have no eligible field-scope coverage receipts.
    result = resolve_missingness(raw)
    scope_check(raw, result.prediction, result.decisions)
    # Gold is loaded only after the source-side projection.
    _, gold, registry, overlay, _, _, _ = prior.predecessor().load_inputs()
    before = HybridEvaluationReportV1.model_validate(read(BASE / "HYBRID_REPORT.json"))
    cache = read(prior.BEFORE / "semantic_judgments.json")
    judge = CachedSemanticJudge(artifacts=cache, model=before.semantic_judge["model"])
    after = evaluate_article_hybrid(result.prediction, gold, registry, overlay, judge,
        precomputed_matches=before.entity_matches, gold_sha256=before.gold_sha256)
    assert before.entity_matches == after.entity_matches, "STOP: frozen matches changed"
    for metric in ("hybrid_production_coverage", "hybrid_supported_value_accuracy",
                   "hybrid_entity_metrics", "conflicts"):
        assert before.metrics[metric] == after.metrics[metric], "STOP: scope leak: " + metric
    for metric in ("hybrid_hard_acceptable", "hybrid_status_accuracy"):
        assert before.metrics[metric]["denominator"] == after.metrics[metric]["denominator"]
    assert before.metrics["hard_failure_decomposition"]["IDENTITY_UNRESOLVED"] == after.metrics["hard_failure_decomposition"]["IDENTITY_UNRESOLVED"]
    assert after.metrics["judge_unavailable_field_count"] == 0, "STOP: new semantic judgment needed"
    assert before.semantic_judgments == after.semantic_judgments, "STOP: cache/judge routing changed"
    new_by_id = {f.target_id: f for f in after.field_results}
    changed_keys = {(d["entity_type"], d["entity_id"], d["field"])
                    for d in result.decisions if d["changed"]}
    for old in before.field_results:
        key = (old.entity_type, old.prediction_entity_id, old.field_id.split(".", 1)[1])
        new = new_by_id[old.target_id]
        if key not in changed_keys:
            assert old == new, "STOP: evaluation outside missingness changed"
        else:
            assert old.in_hard_denominator and old.gold_status in {"NOT_REPORTED", "NOT_APPLICABLE"}
            assert new.hybrid_classification == "EXACT", "STOP: missingness regression"
    handoff = extraction_handoff(after)
    assert handoff == extraction_handoff(before) and len(handoff) == 34
    before_missing, after_missing = unresolved_missingness(before), unresolved_missingness(after)
    still = [f.model_dump(mode="json") for f in after_missing]
    decision_map = {(d["entity_type"], d["entity_id"], d["field"]): d for d in result.decisions}
    for item in still:
        item["decision"] = decision_map[(item["entity_type"], item["prediction_entity_id"],
                                        item["field_id"].split(".", 1)[1])]
    changed = [d for d in result.decisions if d["changed"]]
    counts = Counter(d["after_status"] for d in changed)
    metrics = ("hybrid_hard_acceptable", "hybrid_production_coverage",
               "hybrid_supported_value_accuracy", "hybrid_status_accuracy", "hybrid_entity_metrics", "conflicts")
    summary = {
        "baseline_reproduced": True,
        "before": {k: before.metrics[k] for k in metrics},
        "after": {k: after.metrics[k] for k in metrics},
        "missingness_before": dict(Counter(f.gold_status for f in before_missing)),
        "missingness_after": {k: sum(f.gold_status == k for f in after_missing)
                             for k in ("NOT_REPORTED", "NOT_APPLICABLE")},
        "total_missingness_unresolved_before": len(before_missing),
        "total_missingness_unresolved_after": len(after_missing),
        "nr_decisions": counts["NOT_REPORTED"], "na_decisions": counts["NOT_APPLICABLE"],
        "all_source_field_decisions": len(result.decisions),
        "all_source_unresolved_decisions": sum(d["resolution_status"] == "UNRESOLVED" for d in result.decisions),
        "hard_failures_before": prior.failures(before), "hard_failures_after": prior.failures(after),
        "coverage_certificates_supplied": 0, "pr5g2_hard_extraction_items": len(handoff),
        "api_calls": 0, "identity_mappings_unchanged": True, "canonical_revalidation": True,
        "remaining_blockers": ["34 HARD NR candidates lack bound complete field-scope coverage/review receipts.",
                              "105 identity-unresolved HARD, 34 PRESENT-field misses and one timepoint PARTIAL remain out of scope."],
        "attribution": ATTRIBUTION,
    }
    assert raw.model_dump_json() == original and protected_hashes() == initial
    manifest = {
        "experiment": "PR5G-1", "base_main_commit": "21f58f9c4e5c528236b22dd57be97164db049a8b",
        "baseline_reproduced": True, "protected_hashes": initial,
        "raw_prediction_unchanged": True, "gold_unchanged": True, "registry_unchanged": True,
        "extraction_prompt_unchanged": True, "semantic_judge_cache_unchanged": True,
        "identity_mapping_sha256": digest([m.model_dump(mode="json") for m in before.entity_matches]),
        "production_input_sha256": digest(raw.model_dump(mode="json")),
        "production_input": "frozen PR5F-2 projection; coverage=None; no Gold or cross-side links",
        "projection_sha256": digest(result.prediction.model_dump(mode="json")),
        "production_gold_input": False, "network_disabled": True, "api_calls": 0,
        "new_semantic_judgments": 0, "historical_judgment_count": len(cache),
        "historical_judgment_payload_hashes": {j["input_sha256"]: digest(j) for j in cache},
        "coverage_certificates_supplied": 0,
        "authority_policy": "Reuse Absence Authority v1.1 COMPLETE/non-targeted/source-universe semantics; absent receipt fails closed.",
        "new_pdf_content": False, "new_extraction": False,
    }
    artifacts = {
        "SUMMARY.json": summary, "RUN_MANIFEST.json": manifest,
        "CANONICAL_PREDICTION.json": result.prediction.model_dump(mode="json"),
        "HYBRID_REPORT.json": after.model_dump(mode="json"),
        "MISSINGNESS_DECISIONS.json": result.decisions,
        "MISSINGNESS_UNRESOLVED.json": still, "COVERAGE_PROOFS.json": result.coverage_proofs,
        "PR5G2_EXTRACTION_INPUT.json": handoff,
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in artifacts.items():
        write_json(output / name, value)
    (output / "REPORT.md").write_bytes(render_report(summary).encode("utf-8"))
    return summary


def render_report(s):
    lines = ["# PR5G-1 — Missingness Resolution", "",
        "范围：仅缺失状态投影；无新增提取、无 API、无 identity 修复。Gold 仅用于事后评分。",
        "", "## 状态含义", "",
        "- NOT_APPLICABLE：当前结果语义不适用该字段。mean/SD 的样本量用 n；event_count/denominator 是事件语义。",
        "- NOT_REPORTED：字段适用，已有完整且可核验的来源覆盖证明，逐来源审查无阳性/冲突/未决信息。",
        "- UNRESOLVED：证据不足，不等于文章没有报告。不能把模型未抽到视为 NR。",
        "", "## Before → after", "", "| 指标 | Before | After |", "|---|---:|---:|"]
    for key in ("hybrid_hard_acceptable", "hybrid_status_accuracy", "hybrid_production_coverage",
                "hybrid_supported_value_accuracy"):
        a, b = s["before"][key], s["after"][key]
        lines.append(f"| {key} | {a['numerator']}/{a['denominator']} | {b['numerator']}/{b['denominator']} |")
    for k in ("NOT_REPORTED", "NOT_APPLICABLE"):
        lines.append(f"| HARD {k} unresolved | {s['missingness_before'][k]} | {s['missingness_after'][k]} |")
    lines += [f"| HARD missingness total | {s['total_missingness_unresolved_before']} | {s['total_missingness_unresolved_after']} |"]
    for kind in ("ArmResult", "ComparisonResult", "Outcome"):
        a, b = s["before"]["hybrid_entity_metrics"][kind], s["after"]["hybrid_entity_metrics"][kind]
        lines.append(f"| {kind} | {a['matched']}/{a['gold']} | {b['matched']}/{b['gold']} |")
    lines += ["", "## 决策与来源", "",
        f"NA 状态变化 {s['na_decisions']}；NR 状态变化 {s['nr_decisions']}。",
        "24 个 NA 依据已保存的 mean/SD 字段及 reciprocal evidence；没有按 Gold 或文章 ID 选择对象。",
        "34 个 HARD NR 候选保留 UNRESOLVED：冻结生产产物未提供绑定这些字段的完整 scope certificate + field review。",
        "现有表格片段、成功 extraction 或 surface context 均不等于全文/字段范围的完整覆盖。",
        "COVERAGE_PROOFS.json 同时记录失败的覆盖检查；coverage_sufficient=false 不授权 NR。",
        "生产 resolver 按字段家族遍历 source graph，而不是接收 58 个 Gold targets。未匹配 source 也记录判定，"
        "但不创建匹配关系、不计入这 58 项的分母；all_source_unresolved_decisions 与 HARD backlog 不同口径。",
        "原始字段保存在独立投影的 legacy_fields.missingness.raw_fields；原始 evidence 和所有 PRESENT 值不变。",
        "既有 SOURCE_CONFLICT 保留候选及 evidence；resolver 的未决结论不抹掉原始冲突。",
        "", "## 审计与交接", "",
        "RUN_MANIFEST.json 保存受保护输入哈希；语义 cache、Gold、Registry、prompt、identity links 全部原样复用。",
        "PR5G2_EXTRACTION_INPUT.json 只含 34 个已匹配、Gold=PRESENT、缺少结构化值的 HARD 字段，"
        "不含 NR/NA、未匹配实体、timepoint PARTIAL。它是事后评估诊断，不进入本 PR 生产 resolver。",
        "105 个 identity-unresolved HARD 与 1 个 timepoint PARTIAL 不变。",
        "完整 CLI 在禁止网络的上下文中复现基线、运行两次、逐字节对比全部 9 个输出文件。",
        "", "## 尚未解决", "", *["- " + x for x in s["remaining_blockers"]],
        "", ATTRIBUTION, ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/pr5g1_missingness")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()):
        raise ValueError("Output must be below outputs")
    prior = predecessor()
    with prior.api_disabled():
        verify_baseline(output.parent / (output.name + "_baseline"))
        a = run(output)
        other = output.parent / (output.name + "_replay2")
        b = run(other)
        assert a == b
        for name in FILES:
            data = (output / name).read_bytes()
            assert data == (other / name).read_bytes(), "Non-deterministic artifact: " + name
        if args.snapshot:
            SNAPSHOT.mkdir(parents=True, exist_ok=True)
            for name in FILES:
                data, target = (output / name).read_bytes(), SNAPSHOT / name
                if target.exists() and target.read_bytes() != data:
                    raise ValueError("Refusing to overwrite different frozen missingness snapshot")
                target.write_bytes(data)
    print(json.dumps({k: a[k] for k in ("missingness_before", "missingness_after",
        "nr_decisions", "na_decisions", "after", "api_calls")}, indent=2))
    print("Offline replay: all 9 artifacts byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
