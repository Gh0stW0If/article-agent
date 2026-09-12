"""Read an already sealed production prediction; PR5B evaluation/reporting only."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation import GoldStandardV2, evaluate_article
from article_agent.evaluation.entity_matcher import GROUPS, entities
from article_agent.evaluation.models import EvaluationReportV2
from article_agent.evaluation.registry import load_registry

METRICS = ("hard_exact", "production_coverage", "supported_value_accuracy", "status_accuracy", "evidence_grounding")
STRUCTURE = {"ENTITY_MISSING", "ENTITY_EXTRA", "ENTITY_AMBIGUOUS", "OUTCOME_IDENTITY_SPLIT",
             "OUTCOME_IDENTITY_MERGE", "ARM_BINDING_UNRESOLVED", "COMPARATOR_SCOPE_UNRESOLVED"}
ROOT_GROUPS = {
    "COVERAGE": {"NOT_EXTRACTED"}, "VALUE": {"VALUE_WRONG"},
    "STATUS": {"FALSE_NR", "FALSE_PRESENT", "STATUS_WRONG"},
    "CONFLICT": {"SOURCE_CONFLICT_MISSED", "SOURCE_CONFLICT_SPURIOUS"},
    "EVIDENCE": {"EVIDENCE_UNGROUNDED"},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wire(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def cell(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text.replace("|", "\\|").replace("\n", "<br>")


def percentage(metric):
    rate = metric.get("rate")
    return "N/A" if rate is None else f"{rate:.2%}"


def table(headers, rows):
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)]


def counts(rows):
    return dict(sorted(Counter(r.classification for r in rows if r.classification).items()))


def make_summary(report, prediction_sha256):
    """Frozen evaluator metrics copied verbatim; groupings below are descriptive."""
    fields = [f for f in report.field_results if f.gold_status != "REVIEW_REQUIRED"]
    matched = [f for f in fields if f.prediction_entity_id is not None]
    cascaded = [f for f in fields if f.prediction_entity_id is None and f.classification == "ENTITY_MISSING"]
    layers = {}
    for kind in GROUPS:
        group = [f for f in fields if f.entity_type == kind and f.gold_status in {"PRESENT", "NOT_REPORTED", "NOT_APPLICABLE"}]
        layers[kind] = {"ordinary_targets": len(group), "exact": sum(f.classification == "EXACT" for f in group),
                        "wrong_value": sum(f.classification == "VALUE_WRONG" for f in group),
                        "wrong_status": sum(f.classification in {"STATUS_WRONG", "FALSE_NR", "FALSE_PRESENT"} for f in group),
                        "not_extracted": sum(f.classification == "NOT_EXTRACTED" for f in group),
                        "entity_missing_cascade": sum(f.classification == "ENTITY_MISSING" for f in group)}
    root = {"STRUCTURE": {"entity_failure_events": sum(report.entity_failure_counts.get(c, 0) for c in STRUCTURE),
                           "cascaded_field_losses": len(cascaded)}}
    root.update({group: sum(report.field_failure_counts.get(c, 0) for c in classes) for group, classes in ROOT_GROUPS.items()})
    root["CONFLICT"] += sum(c["candidate_set_match"] is False for c in report.conflict_results)
    abstentions = [f for f in matched if f.classification == "NOT_EXTRACTED"]
    return {
        "benchmark_id": "2015-06-baseline-v1", "article_id": report.article_id,
        "gold_id": "2015-06-gold-v1", "prediction_sha256": prediction_sha256,
        "metrics": {k: report.metrics[k] for k in METRICS}, "entities": report.metrics["entities"],
        "conflicts": report.metrics["conflicts"], "field_failure_counts": report.field_failure_counts,
        "entity_failure_counts": report.entity_failure_counts, "root_cause_groups": root,
        "field_layers": layers, "matched_entity_field_classifications": counts(matched),
        "cascaded_field_losses": len(cascaded),
        "false_present_by_field": dict(Counter(f.field_id for f in matched if f.gold_status == "NOT_REPORTED" and f.classification == "FALSE_PRESENT").most_common()),
        "abstention": {"not_extracted": len(abstentions),
                       "hard_not_extracted": sum(f.evaluation_tier == "HARD" for f in abstentions),
                       "supported_present_not_extracted": sum(f.gold_status == "PRESENT" and f.support_status == "SUPPORTED" for f in abstentions),
                       "by_field": dict(Counter(f.field_id for f in abstentions).most_common())},
        "reviewed_uncertainty_excluded": [f.target_id for f in report.field_results if f.gold_status == "REVIEW_REQUIRED"],
        "performance_threshold": None, "possible_gold_issue": None,
    }


def failure_table(fields):
    return table(["Entity", "Gold ID", "Pred ID", "Field", "Gold status", "Pred status", "Gold value", "Pred value", "Classification"],
                 [[f.entity_type, f.gold_entity_id, f.prediction_entity_id, f.field_id, f.gold_status,
                   f.prediction_status, f.gold_value, f.prediction_value, f.classification] for f in fields])


def bottlenecks(report):
    """Rank observed counts, not proposed fixes. Cascade counts are not extra bugs."""
    candidates = []
    # Reporting priority only: upstream identities before result cascades.
    structural_priority = {
        "Article": 0, "Study": 0, "Arm": 0, "Outcome": 1,
        "Comparison": 2, "Intervention": 3, "ArmResult": 4, "ComparisonResult": 4,
    }
    for kind in GROUPS:
        events = [e for e in report.entity_failures if e.get("entity_type") == kind]
        cascade = sum(f.entity_type == kind and f.classification == "ENTITY_MISSING" for f in report.field_results)
        if events:
            candidates.append((structural_priority[kind], -cascade, -len(events), f"STRUCTURE / {kind}: {len(events)} entity failure events; {cascade} cascading field losses (not independent extraction bugs)."))
    hard = [f for f in report.field_results if f.evaluation_tier == "HARD" and f.support_status == "SUPPORTED" and f.classification == "NOT_EXTRACTED"]
    if hard:
        candidates.append((5, -len(hard), 0, f"COVERAGE: {len(hard)} HARD/SUPPORTED targets not extracted on matched entities."))
    for priority, category in ((6, "VALUE_WRONG"), (7, "FALSE_PRESENT"), (7, "STATUS_WRONG"), (8, "EVIDENCE_UNGROUNDED")):
        n = report.field_failure_counts.get(category, 0)
        if n:
            candidates.append((priority, -n, 0, f"{category}: {n} reported field failures."))
    return [x[-1] for x in sorted(candidates)[:5]]


def production_audit(production, output, pred):
    """Summarize existing artifacts only; never call extraction or invent requests."""
    raw_dir = production / "raw_module_responses"
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    tablewise = load(raw_dir / "outcomes.tablewise.manifest.json")
    requests = [json.loads(line) for line in (raw_dir / "request_manifest.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    post = load(raw_dir / "outcomes.postprocess.manifest.json")
    bundle = load(production / "extraction.json")
    graph = ArticleExtraction.model_validate_json(
        (production / "arm_details/arm_details.canonical.json").read_bytes())
    assert pred.article.legacy_fields["production_source_bundle"] == bundle
    assert pred.arms == graph.arms and pred.interventions == graph.interventions
    source = load(output / "ISOLATED_SOURCE_MANIFEST.json")
    isolated = output.parent / output.name.replace("_benchmark", "_isolated_workspace", 1)
    root = Path(__file__).resolve().parents[1]
    mismatches = [name for name, digest in source["files"].items()
                  if sha((isolated / name).read_bytes()) != digest or sha((root / name).read_bytes()) != digest]
    assert not mismatches
    tables = [{
        "table_id": t["table_id"], "category": t["table_category"], "status": t["status"],
        "selected_rows": t["selected_row_count"], "covered_row_ids": t.get("covered_row_ids", []),
        "missing_row_ids": t.get("missing_row_ids", []), "outcomes": t["outcome_count"],
        "column_map_count": len(t.get("column_map", [])),
    } for t in tablewise["tables"] + tablewise["narrative"]]
    return {
        "source_integrity": {"verified_files": len(source["files"]), "mismatches": mismatches},
        "raw_source_bundle_preserved": True, "arm_intervention_sample_flow_unchanged": True,
        "raw_outcome_count": len(bundle["outcomes"]["outcomes"]),
        "table_outcome_count": sum(t["outcomes"] for t in tables if not t["table_id"].startswith("narrative")),
        "narrative_outcome_count": tablewise["narrative_outcome_count"],
        "row_coverage": tables,
        "coverage_note": "Coverage means selected rows acknowledged, not clinical completeness or correct values. Baseline table was skipped.",
        "documented_outcome_request_operations": len(requests),
        "outcome_request_status_counts": dict(sorted(Counter(r["response_status"] for r in requests).items())),
        "outcome_row_fallback_operations": sum(r["request_mode"] == "row" and bool(r.get("fallback_reason")) for r in requests),
        "topology_requests": len(list((production / "trial_topology").glob("topology.request-*.json"))),
        "topology_validation_or_transport_failures": len(list((production / "trial_topology").glob("topology.error-*.txt"))),
        "arm_details_requests": len(list((production / "arm_details").glob("request-*.json"))),
        "arm_details_failures": len(list((production / "arm_details").glob("error-*.json"))),
        "postprocessed_records": post["processed_outcome_count"],
        "postprocessing_part_status_counts": dict(sorted(Counter(p["status"] for p in post["parts"]).items())),
        "complete_http_request_total": None,
        "request_count_note": "Counts are persisted stage operations, not a complete wire-level request trace; unrecorded transport attempts cannot be reconstructed.",
        "request_run_ids": sorted({r.get("run_id") for r in requests}),
        "run_id_note": "Production manifest identifies retry06; row request manifests retain the production-written NR. Original artifacts were not edited.",
        "model_configuration": load(output / "PRODUCTION_ISOLATION.json")["model_configuration"],
        "api_mode": load(output / "PRODUCTION_ISOLATION.json")["api_mode"],
        "gold_used_for_postprocess_comparison": post["gold_used_for_postprocess_comparison"],
    }


def reports(pred, gold, report, summary):
    lines = ["# 2015-06 Real Baseline Benchmark", "", "第一次 production baseline；未调优、未人工修改 prediction。", ""]
    lines += table(["Metric", "Numerator", "Denominator", "Rate"],
                   [[name, summary["metrics"][name]["numerator"], summary["metrics"][name]["denominator"],
                     percentage(summary["metrics"][name])] for name in METRICS])
    lines += ["", "注意：supported value accuracy 只评价已匹配且 PRESENT 的 supported 值；分母很小时，100% 不代表整篇提取正确。Entity 未匹配造成的级联丢失仍计入 HARD exact / coverage。"]
    lines += ["", "人工只读诊断见 [ROOT_CAUSE_NOTES.md](ROOT_CAUSE_NOTES.md)。它不改 prediction 或正式评分。"]
    lines += ["", "## Entity match summary", ""]
    lines += table(["Entity", "Gold", "Pred", "Matched", "Missing", "Extra", "Ambiguous Gold/Pred", "Recall", "Precision"],
                   [[kind, m["gold"], m["prediction"], m["matched"], m["missing"], m["extra"],
                     f"{m['ambiguous_gold']}/{m['ambiguous_prediction']}", percentage(m["recall"]), percentage(m["precision"])] for kind, m in summary["entities"].items()])
    lines += ["", "## Top failure classes", "", "Field: " + cell(report.field_failure_counts), "", "Entity: " + cell(report.entity_failure_counts),
              "", "## 2015-06 structural checks", "",
              f"1. Arms 数量：{len(pred.arms)}；是否为三臂：{len(pred.arms) == 3}。",
              "2. 冻结来源 Arm ID、实际名称与 components 如下（不按 Gold 改名）：", ""]
    interventions = {i.intervention_id: i for i in pred.interventions}
    lines += table(["Arm ID", "Label", "Intervention IDs", "Component names"],
                   [[a.arm_id, a.label.value, a.intervention_ids, [interventions[i].name.value for i in a.intervention_ids]] for a in pred.arms])
    shared = set.intersection(*(set(a.intervention_ids) for a in pred.arms)) if pred.arms else set()
    lines += ["", "3. 三组共同引用的 Intervention 实体（据实际结构显示，不做额外同义词匹配）：" + cell({i: interventions[i].name.value for i in sorted(shared)}),
              f"4. Outcome 数量：{len(pred.outcomes)}；是否为 4：{len(pred.outcomes) == 4}。", ""]
    lines += ["## Outcome identity", ""]
    lines += table(["Side", "Outcome ID", "Name", "Instrument status/value"],
                   [[side, o.outcome_id, o.name.value, {"status": o.instrument.status.value, "value": o.instrument.value}]
                    for side, graph in (("Gold", gold.truth), ("Pred", pred)) for o in graph.outcomes])
    lines += ["", "Outcome matching records: " + cell([m.model_dump(mode="json") for m in report.entity_matches if m.entity_type == "Outcome"]),
              "", "5. 各 prediction Outcome 的时间点与来源行（用于检查 baseline、1 month、3 months 是否被拆成不同实体）：", ""]
    lines += table(["Outcome", "ArmResult timepoints", "Source rows"],
                   [[o.outcome_id, sorted({str(r.timepoint.value) for r in pred.arm_results if r.outcome_id == o.outcome_id}),
                     sorted({str(r.source_row_id) for r in pred.arm_results if r.outcome_id == o.outcome_id})] for o in pred.outcomes])
    lines += ["", "## Comparison / result checks", "",
              f"6. 实际 Comparisons：{len(pred.comparisons)}；正式 matched 数见 entity table，未自动补成三项。",
              "7. 原始 P1/P2/P3 participant mapping 只依赖 production source；下面保留 comparison 原始显式关系供核对。", ""]
    lines += table(["Side", "Comparison", "Ordered arms", "Relation", "Contrast"],
                   [[side, c.comparison_id, c.arm_ids, c.relation.value, c.contrast.value]
                    for side, graph in (("Gold", gold.truth), ("Pred", pred)) for c in graph.comparisons])
    lines += ["", "Comparison relation/contrast 的完整状态（参与组正确并不保证身份字段匹配）：", ""]
    lines += table(["Comparison", "Relation status", "Contrast status", "Contrast candidates"],
                   [[c.comparison_id, c.relation.status.value, c.contrast.status.value,
                     [v.value for v in c.contrast.conflict_candidates]] for c in pred.comparisons])
    lines += ["", f"8. ArmResults={len(pred.arm_results)}；ComparisonResults={len(pred.comparison_results)}。匹配/缺失/额外/歧义见 entity table，不合并为单一 result accuracy。",
              "9. Sample-size source conflict：", ""]
    lines += table(["Arm", "Status", "Value", "Candidates"],
                   [[a.arm_id, a.randomized_n.status.value, a.randomized_n.value,
                     [c.model_dump(mode="json") for c in a.randomized_n.conflict_candidates]] for a in pred.arms])
    lines += ["", "Conflict metrics: " + cell(summary["conflicts"]),
              "", "10. Assembly 没有生成 pairwise combinations；只调用现有 PR4 canonicalizer。是否多生成实体以 evaluator 的 Extra/ambiguous 记录为准；数量等于 C(3,2) 本身不是自动 all-pairs 的证据。",
              "", "## Field-level layers", ""]
    lines += table(["Entity", "Ordinary", "Exact", "Wrong value", "Wrong status", "Not extracted", "Missing cascade"],
                   [[kind, *m.values()] for kind, m in summary["field_layers"].items()])
    lines += ["", "## Production provenance / unresolved source warnings", "",
              "生产原始模块完整保存在本地 output；canonicalization warnings（不作为第二套正式 taxonomy）：", "",
              *[f"- {w}" for w in pred.adapter_warnings],
              "", "## REVIEW_REQUIRED", "",
              "centre_count、participant_blinding 是已审核后的不确定状态，不进入 ordinary HARD denominator，不解释为 Agent 错误。",
              "", "## Evidence grounding", "", cell(summary["metrics"]["evidence_grounding"]),
              "", f"EVIDENCE_UNGROUNDED: {report.field_failure_counts.get('EVIDENCE_UNGROUNDED', 0)}。这里只检查结构 evidence linkage，不独立重验 PDF 语义。",
              "", "## Top 5 bottlenecks", "", *[f"{i}. {s}" for i, s in enumerate(summary["top_bottlenecks"], 1)],
              "", "## Possible Gold Issues", "", "None. Prediction 与 Gold 不同不构成修改 Gold 的理由。",
              "", "## HARD targets", "", "全部 HARD targets 见 HARD_TARGETS.md；REVIEW_REQUIRED 另外标明 excluded，不纳入普通评分。"]
    matched = [f for f in report.field_results if f.prediction_entity_id is not None and f.gold_status != "REVIEW_REQUIRED"]
    failure = ["# Failure Analysis", "", "正式分类来自 PR5B；六类 root-cause grouping 仅用于报告。结构事件、匹配实体字段错误与级联丢失分开，不相加当成独立 bugs。", "",
               "## 1. Primary structural failures", "", cell(report.entity_failure_counts), ""]
    failure += table(["Entity", "Classification", "Details"], [[e.get("entity_type"), e["classification"], e] for e in report.entity_failures])
    for heading, classes in (("2. Coverage / NOT_EXTRACTED", {"NOT_EXTRACTED"}),
                             ("3. Wrong values", {"VALUE_WRONG"}),
                             ("4. Status errors", {"FALSE_NR", "FALSE_PRESENT", "STATUS_WRONG"}),
                             ("5. Conflict handling", {"SOURCE_CONFLICT_MISSED", "SOURCE_CONFLICT_SPURIOUS", "SOURCE_CONFLICT_DETECTED"})):
        subset = [f for f in matched if f.classification in classes]
        failure += ["", "## " + heading, "", "Matched-entity field counts: " + cell(counts(subset)), ""]
        # Each major failure class has representatives; full HARD table remains lossless.
        representatives = []
        for kind in GROUPS:
            for classification in sorted(classes):
                representatives.extend([f for f in subset if f.entity_type == kind and f.classification == classification][:3])
        failure += failure_table(representatives)
        if "Coverage" in heading:
            failure += ["", cell(summary["abstention"])]
        if "Wrong values" in heading:
            failure += ["", "Value errors by entity family: " + cell(dict(Counter(f.entity_type for f in subset)))]
        if "Status errors" in heading:
            failure += ["", "Top 10 FALSE_PRESENT fields (Gold NOT_REPORTED): " + cell(list(summary["false_present_by_field"].items())[:10])]
        if "Conflict" in heading:
            failure += ["", cell(summary["conflicts"]), "", cell(report.conflict_results)]
    failure += ["", "## 6. Evidence grounding", "", cell(summary["metrics"]["evidence_grounding"]),
                "", "只测结构引用闭环，不独立判定 PDF 语义。", ""]
    failure += failure_table([f for f in matched if "EVIDENCE_UNGROUNDED" in f.additional_failures][:12])
    cascades = [f for f in report.field_results if f.prediction_entity_id is None and f.classification == "ENTITY_MISSING"]
    failure += ["", "## 7. Cascaded losses", "", f"{len(cascades)} fields were lost because their Gold entity did not match, not {len(cascades)} independently diagnosed extraction bugs.", ""]
    failure += table(["Entity family", "Cascaded fields"], sorted(Counter(f.entity_type for f in cascades).items()))
    failure += ["", "All formal field counts: " + cell(report.field_failure_counts), "", "Root-cause groups: " + cell(summary["root_cause_groups"]),
                "", "## 8. Most important next bottlenecks", "", *[f"{i}. {s}" for i, s in enumerate(summary["top_bottlenecks"], 1)],
                "", "仅按观测数量与影响范围排序。本 PR 不给新规则、不优化、不重跑 production。"]
    if "production_audit" in summary:
        audit_lines = ["", "## Production coverage and provenance audit", "", cell(summary["production_audit"]),
                       "", "原文行覆盖不等于 Gold target coverage；已选行全部返回，也可能因组别、结局、比较语义缺失而得低分。"]
        lines += audit_lines
        failure += audit_lines
    hard = ["# All HARD targets", "", "Includes all HARD entries for audit; REVIEW_REQUIRED entries are excluded from ordinary scoring.", ""]
    hard += failure_table([f for f in report.field_results if f.evaluation_tier == "HARD"])
    return {"REPORT.md": "\n".join(lines) + "\n", "FAILURE_ANALYSIS.md": "\n".join(failure) + "\n", "HARD_TARGETS.md": "\n".join(hard) + "\n"}


def benchmark(prediction_path, gold_path, registry_path, output):
    output = Path(output)
    manifest = json.loads((output / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    raw = Path(prediction_path).read_bytes()
    assert manifest["status"] in {"PREDICTION_FROZEN", "BENCHMARK_COMPLETE"} and manifest["prediction_frozen_before_evaluation"]
    assert sha(raw) == manifest["prediction_sha256"]
    pred = ArticleExtraction.model_validate_json(raw)
    # This is the first reference-annotation read in the benchmark path.
    gold_bytes = Path(gold_path).read_bytes()
    gold = GoldStandardV2.model_validate_json(gold_bytes)
    assert gold.state == "FROZEN" and gold.gold_id == "2015-06-gold-v1"
    registry = load_registry(registry_path)
    report = evaluate_article(pred, gold, registry)
    first = (report.model_dump_json(indent=2) + "\n").encode("utf-8")
    second = (evaluate_article(pred, gold, registry).model_dump_json(indent=2) + "\n").encode("utf-8")
    assert first == second, "PR5B evaluator is not byte-deterministic"
    if (output / "evaluation.json").exists():
        assert (output / "evaluation.json").read_bytes() == first, "Never overwrite a different frozen evaluation"
    EvaluationReportV2.model_validate_json(first)
    assert sha(Path(prediction_path).read_bytes()) == manifest["prediction_sha256"]
    excluded = [f for f in report.field_results if f.gold_status == "REVIEW_REQUIRED"]
    assert len(excluded) == 2 and all(not f.in_hard_denominator for f in excluded)
    summary = make_summary(report, manifest["prediction_sha256"])
    summary["top_bottlenecks"] = bottlenecks(report)
    summary["authorized_transport_patch"] = manifest.get("authorized_transport_patch", {})
    summary["authorized_configuration_change"] = manifest.get("authorized_configuration_change")
    summary["acceptance"] = {"status": "PASS", "evaluator_byte_identical": True,
                             "production_unmodified": not bool(manifest.get("authorized_transport_patch")),
                             "extraction_algorithms_unmodified": True,
                             "prediction_unchanged_after_evaluation": True, "no_performance_threshold": True}
    manifest.update(status="BENCHMARK_COMPLETE", gold_id=gold.gold_id, gold_version=gold.gold_version,
                    gold_json_sha256=sha(gold_bytes), registry_version=registry.registry_version,
                    registry_sha256=sha(Path(registry_path).read_bytes()), evaluation_report_version=report.report_version,
                    evaluator_byte_identical=True)
    production = Path(manifest["production_output_root"]) / "2015-06"
    pipeline_manifest = json.loads((production / "manifest.json").read_text(encoding="utf-8"))
    manifest["actual_parser_backend"] = pipeline_manifest["parser_backend"]
    assert pipeline_manifest.get("outcome_postprocessing", {}).get("gold_comparison") != "provided"
    audit = production_audit(production, output, pred)
    summary["production_audit"] = audit
    manifest["source_integrity"] = audit["source_integrity"]
    manifest["requests"] = {k: v for k, v in audit.items() if k in {
        "documented_outcome_request_operations", "outcome_request_status_counts", "outcome_row_fallback_operations",
        "topology_requests", "topology_validation_or_transport_failures", "arm_details_requests", "arm_details_failures",
        "postprocessing_part_status_counts", "complete_http_request_total", "request_count_note",
    }}
    manifest["evaluation_sha256"] = sha(first)
    manifest["api_mode"] = audit["api_mode"]
    summary["acceptance"]["protocol_note"] = "PASS under explicit Responses/model-change authorization; original clean-main-only condition is not claimed."
    (output / "evaluation.json").write_bytes(first)
    (output / "SUMMARY.json").write_bytes(wire(summary))
    (output / "RUN_MANIFEST.json").write_bytes(wire(manifest))
    (output / "PRODUCTION_AUDIT.json").write_bytes(wire(audit))
    for name, text in reports(pred, gold, report, summary).items():
        if name == "REPORT.md" and manifest.get("authorized_transport_patch"):
            text += ("\n## Authorized transport/configuration retry\n\n"
                     "本次使用用户授权的 Responses 通信适配与全 sol 配置；不是原始 main 的字节完全相同运行。"
                     "提取算法、提示词、Gold、Registry、evaluator 未更改。\n\n"
                     + cell(summary["authorized_transport_patch"]) + "\n\n"
                     + cell(summary["authorized_configuration_change"]) + "\n")
        (output / name).write_text(text, encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    for name in ("prediction", "gold", "registry", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--snapshot", type=Path, help="Create a new immutable baseline directory; never overwrite")
    args = parser.parse_args()
    if args.snapshot is not None and args.snapshot.exists():
        raise FileExistsError("The baseline snapshot must not be overwritten")
    summary = benchmark(args.prediction, args.gold, args.registry, args.output)
    if args.snapshot is not None:
        freeze_snapshot(args.output, args.snapshot)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def freeze_snapshot(output, destination):
    """Copy an explicit artifact allowlist, excluding PDFs, credentials and logs."""
    output, destination = Path(output), Path(destination)
    manifest = json.loads((output / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "BENCHMARK_COMPLETE"
    assert sha((output / "prediction.json").read_bytes()) == manifest["prediction_sha256"]
    assert sha((output / "evaluation.json").read_bytes()) == manifest["evaluation_sha256"]
    required = (
        "prediction.json", "evaluation.json", "SUMMARY.json", "REPORT.md", "FAILURE_ANALYSIS.md",
        "RUN_MANIFEST.json", "HARD_TARGETS.md", "PRODUCTION_AUDIT.json", "ROOT_CAUSE_NOTES.md",
        "ASSEMBLY.json", "ISOLATED_SOURCE_MANIFEST.json", "PRODUCTION_ISOLATION.json",
    )
    for name in required:
        if not (output / name).is_file():
            raise FileNotFoundError(name)
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in required:
        shutil.copy2(output / name, destination / name)
        hashes[name] = sha((destination / name).read_bytes())
        assert hashes[name] == sha((output / name).read_bytes())
    (destination / "SNAPSHOT_MANIFEST.json").write_bytes(wire({
        "benchmark_id": manifest["benchmark_id"], "files": hashes,
        "publication_status": "local snapshot; not yet committed or pushed",
    }))


if __name__ == "__main__":
    main()
