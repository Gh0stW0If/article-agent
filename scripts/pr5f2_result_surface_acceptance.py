"""Offline source-supported surface projection and frozen-identity Hybrid replay."""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.entity_matcher import entities
from article_agent.evaluation.hybrid import CachedSemanticJudge, HybridEvaluationReportV1
from article_agent.evaluation.hybrid.engine import ACCEPTABLE, evaluate_article_hybrid
from article_agent.evaluation.hybrid.semantic_judge import digest, write_json
from article_agent.result_surface import normalize_result_surfaces
from article_agent.result_surface.source_context import context_from_blocks

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "benchmarks/2015-06/newly_scorable_adjudication_v1"
SNAPSHOT = ROOT / "benchmarks/2015-06/result_surface_v1"
OUTPUT = ROOT / "outputs/pr5f2_2015_06_surface"
FILES = ("REPORT.md", "SUMMARY.json", "CANONICAL_PREDICTION.json", "HYBRID_REPORT.json",
         "SOURCE_SURFACE_CONTEXT.json", "STATISTIC_REPRESENTATION_NORMALIZATION.json",
         "FIELD_SOURCE_BINDINGS.json", "SURFACE_CONFLICT_NORMALIZATION.json",
         "BEFORE_AFTER_FIELD_EVALUATION.json", "PR5G1_MISSINGNESS_INPUT.json", "RUN_MANIFEST.json")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def predecessor():
    spec = importlib.util.spec_from_file_location("pr5e2_predecessor", ROOT / "scripts/pr5e2_adjudicate_new_fields.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def api_disabled():
    def forbidden(*args, **kwargs):
        raise RuntimeError("STOP: this acceptance forbids all network/API calls")
    with patch("socket.create_connection", forbidden), patch("socket.socket.connect", forbidden), \
            patch("socket.socket.connect_ex", forbidden):
        yield


def protected_hashes():
    hashes = predecessor().protected_hashes()
    hashes.update({p.relative_to(ROOT).as_posix(): sha(p) for p in BEFORE.iterdir() if p.is_file()})
    return dict(sorted(hashes.items()))


def verify_baseline(output):
    previous = predecessor()
    previous.check_baseline(output / "prior")
    inputs = previous.load_inputs()
    plan = previous.get_plan(inputs)
    actual = previous.finalize(output, inputs, plan,
        read(BEFORE / "NEWLY_ADJUDICATED_JUDGMENTS.json"), previous.protected_hashes())
    for name in previous.FILES:
        if (output / name).read_bytes() != (BEFORE / name).read_bytes():
            raise RuntimeError("STOP: baseline drift: " + name)
    for key, expected in {
        "hybrid_hard_acceptable": (64, 271), "hybrid_production_coverage": (72, 165),
        "hybrid_supported_value_accuracy": (64, 72), "hybrid_status_accuracy": (97, 595),
    }.items():
        metric = actual["after"][key]
        if (metric["numerator"], metric["denominator"]) != expected:
            raise RuntimeError("STOP: unexpected frozen baseline " + key)
    assert actual["evaluation_backlog_after"] == 0
    assert actual["remaining_nonsemantic_hard_blockers"] == {
        "identity_unresolved": 105, "field_or_status_unresolved": 92,
        "raw_deterministic_mismatch": 7, "spurious_source_conflict": 2}


def source_context(path):
    expected = read(ROOT / "benchmarks/2015-06/result_identity_v1/SOURCE_IDENTITY_CONTEXT.json")
    if sha(path) != expected["source_document_sha256"]:
        raise RuntimeError("STOP: source Markdown is not the frozen production source")
    sys.path.insert(0, str(ROOT / "MinerU method"))
    from mineru_method.table_parser import extract_outcome_table_blocks, parse_table_column_map, attach_source_cells
    from article_agent.result_identity.source_context import explicit_header_blocks
    text = Path(path).read_text(encoding="utf-8")
    blocks = explicit_header_blocks(extract_outcome_table_blocks(text, defer_classification=True),
                                   parse_table_column_map, attach_source_cells)
    return context_from_blocks(blocks, text, source_ref="production/article.md",
                               source_document_sha256=sha(path))


def scope_check(raw, projected):
    for name in ("article", "studies", "arms", "interventions", "outcomes", "adapter_warnings"):
        assert getattr(raw, name) == getattr(projected, name), "STOP: out-of-scope graph change: " + name
    assert projected.evidence[:len(raw.evidence)] == raw.evidence, "STOP: original evidence modified"
    allowed = {"ArmResult": {"value_kind"}, "ComparisonResult": {"raw_value", "p_value"},
               "Comparison": {"contrast"}}
    for kind, fields in allowed.items():
        a, b = entities(raw, kind), entities(projected, kind)
        assert a.keys() == b.keys(), "STOP: entity created or deleted"
        for key, original in a.items():
            changes = b[key].legacy_fields.get("result_surface", {})
            for field in type(original).model_fields:
                if field not in fields | {"legacy_fields"}:
                    assert getattr(original, field) == getattr(b[key], field), "STOP: identity/non-surface field changed"
                elif field in fields and getattr(original, field) != getattr(b[key], field):
                    saved = changes["raw_fields"][field]
                    assert saved == getattr(original, field).model_dump(mode="json")
                    assert getattr(original, field).status in {"PRESENT", "SOURCE_CONFLICT"}
    ArticleExtraction.model_validate_json(projected.model_dump_json())


def missingness(report):
    return [{"target_id": f.target_id, "entity_type": f.entity_type,
             "gold_entity_id": f.gold_entity_id, "prediction_entity_id": f.prediction_entity_id,
             "field": f.field_id, "gold_status": f.gold_status, "prediction_status": f.prediction_status,
             "classification": f.hybrid_classification, "evaluation_tier": f.evaluation_tier,
             "support_status": f.support_status, "in_hard_denominator": f.in_hard_denominator}
            for f in report.field_results if f.gold_status in {"NOT_REPORTED", "NOT_APPLICABLE"}
            and f.prediction_status == "UNRESOLVED"]


def failures(report):
    counts = {key: 0 for key in ("identity_unresolved", "field_missing", "status_unresolved",
              "raw_deterministic_mismatch", "semantic_partial", "semantic_error",
              "semantic_wrong", "source_conflict", "other")}
    for f in report.field_results:
        if not f.in_hard_denominator or f.hybrid_classification in ACCEPTABLE:
            continue
        c = f.hybrid_classification
        if c == "ENTITY_MISSING":
            key = "identity_unresolved"
        elif c == "NOT_EXTRACTED":
            key = "field_missing" if f.gold_status == "PRESENT" else "status_unresolved"
        elif c == "VALUE_WRONG":
            key = "raw_deterministic_mismatch"
        elif c in {"SEMANTIC_PARTIAL", "SEMANTIC_ERROR", "SEMANTIC_WRONG"}:
            key = c.lower()
        elif "CONFLICT" in c:
            key = "source_conflict"
        elif c in {"FALSE_NR", "FALSE_PRESENT", "STATUS_WRONG"}:
            key = "status_unresolved"
        else:
            key = "other"
        counts[key] += 1
    return counts


def value_breakdown(report):
    counts = Counter()
    for f in report.field_results:
        if not f.in_value_accuracy_denominator:
            continue
        key = "fully_acceptable" if f.value_acceptable else (
            "partial" if f.hybrid_classification == "SEMANTIC_PARTIAL" else
            "deterministic_mismatch" if f.hybrid_classification == "VALUE_WRONG" else "other")
        counts[key] += 1
    return {k: counts[k] for k in ("fully_acceptable", "partial", "deterministic_mismatch", "other")}


def run(output, context):
    initial = protected_hashes()
    expected_source = read(ROOT / "benchmarks/2015-06/result_identity_v1/SOURCE_IDENTITY_CONTEXT.json")
    if context.get("source_document_sha256") != expected_source["source_document_sha256"]:
        raise RuntimeError("STOP: derived context does not identify the frozen production source")
    previous = predecessor()
    raw, gold, registry, overlay, _, _, _ = previous.load_inputs()
    original = raw.model_dump_json()
    before = HybridEvaluationReportV1.model_validate(read(BEFORE / "HYBRID_REPORT.json"))
    cache = read(BEFORE / "semantic_judgments.json")
    # Production receives no Gold, expected value, mapping, match count or target ID.
    result = normalize_result_surfaces(raw, context)
    projected = result.prediction
    scope_check(raw, projected)
    judge = CachedSemanticJudge(artifacts=cache, model=before.semantic_judge["model"])
    after = evaluate_article_hybrid(projected, gold, registry, overlay, judge,
        prediction_sha256=hashlib.sha256(projected.model_dump_json().encode("utf-8")).hexdigest(),
        gold_sha256=before.gold_sha256, precomputed_matches=before.entity_matches)
    assert before.entity_matches == after.entity_matches, "STOP: identity mappings changed"
    assert before.metrics["hybrid_entity_metrics"] == after.metrics["hybrid_entity_metrics"]
    assert before.metrics["conflicts"] == after.metrics["conflicts"]
    assert before.metrics["hard_failure_decomposition"]["IDENTITY_UNRESOLVED"] == after.metrics["hard_failure_decomposition"]["IDENTITY_UNRESOLVED"]
    assert after.metrics["judge_unavailable_field_count"] == 0, "STOP: new judgment would be required"
    assert missingness(before) == missingness(after), "STOP: missingness scope leak"
    current = {f.target_id: f for f in after.field_results}
    assert all(current[f.target_id].value_acceptable is True for f in before.field_results
               if f.value_acceptable is True), "STOP: previously correct value regressed"
    assert all(current[f.target_id].hybrid_classification in ACCEPTABLE for f in before.field_results
               if f.in_hard_denominator and f.hybrid_classification in ACCEPTABLE), "STOP: acceptable HARD field regressed"
    for key in ("hybrid_hard_acceptable", "hybrid_production_coverage"):
        assert before.metrics[key]["denominator"] == after.metrics[key]["denominator"]
    # Coverage may gain resolved false conflicts under the unchanged PRESENT formula.
    promoted = [f.target_id for f in before.field_results if f.gold_status == "PRESENT"
                and f.support_status == "SUPPORTED" and f.prediction_status == "SOURCE_CONFLICT"
                and current[f.target_id].prediction_status == "PRESENT"]
    assert after.metrics["hybrid_production_coverage"]["numerator"] == before.metrics["hybrid_production_coverage"]["numerator"] + len(promoted)
    raw_judgments = {j["judgment_id"]: j for j in cache}
    changes = []
    for old in before.field_results:
        new = current[old.target_id]
        if old.prediction_entity_id is None:
            assert old == new, "STOP: unresolved identity field changed"
            continue
        p = entities(projected, old.entity_type)[old.prediction_entity_id]
        r = entities(raw, old.entity_type)[old.prediction_entity_id]
        field_name = old.field_id.split(".", 1)[1]
        if getattr(r, field_name) == getattr(p, field_name):
            # Deterministic-reference identity diagnostics can react to normalized
            # representations, but frozen routed field evaluation must stay the same.
            assert old.hybrid_classification == new.hybrid_classification
            assert old.semantic_judgment_id == new.semantic_judgment_id
            continue
        changes.append({
            "target_id": old.target_id, "entity_type": old.entity_type, "entity_id": old.prediction_entity_id,
            "field": field_name, "before_field": getattr(r, field_name).model_dump(mode="json"),
            "after_field": getattr(p, field_name).model_dump(mode="json"),
            "before_evaluation": old.model_dump(mode="json"), "after_evaluation": new.model_dump(mode="json"),
            "raw_judgment": raw_judgments.get(old.semantic_judgment_id),
            "normalization_events": [e for e in p.legacy_fields["result_surface"]["events"] if e["field"] == field_name],
        })
    # Source-side normalization never uses matchability as an input. Existing
    # unmatched source records may receive local surface bindings, but cannot
    # acquire a Gold link or contribute to scoring.
    accounted = {(c["entity_type"], c["entity_id"], c["field"]) for c in changes}
    for kind in ("ArmResult", "ComparisonResult", "Comparison"):
        for entity_id, p in entities(projected, kind).items():
            trace = p.legacy_fields.get("result_surface", {})
            for field_name, raw_field in trace.get("raw_fields", {}).items():
                if (kind, entity_id, field_name) not in accounted:
                    changes.append({
                        "target_id": f"Prediction:{kind}:{entity_id}:{field_name}", "entity_type": kind,
                        "entity_id": entity_id, "field": field_name, "before_field": raw_field,
                        "after_field": getattr(p, field_name).model_dump(mode="json"),
                        "before_evaluation": {"hybrid_classification": "UNMATCHED_NOT_SCORED"},
                        "after_evaluation": {"hybrid_classification": "UNMATCHED_NOT_SCORED"},
                        "raw_judgment": None,
                        "normalization_events": [e for e in trace["events"] if e["field"] == field_name],
                    })
    issue_sets = {
        "confirmed_mean_as_other": [f for f in before.field_results if f.field_id == "armResult.value_kind"
            and f.gold_value == "mean" and f.prediction_value == "other" and f.semantic_grade in {"ERROR", "WRONG"}],
        "raw_deterministic_mismatch": [f for f in before.field_results if f.in_hard_denominator
            and f.hybrid_classification == "VALUE_WRONG"],
        "spurious_source_conflict": [f for f in before.field_results if f.in_hard_denominator
            and f.hybrid_classification == "SOURCE_CONFLICT_SPURIOUS"],
    }
    issue_audit = {}
    for key, items in issue_sets.items():
        issue_audit[key] = {"before": len(items),
            "after": sum(current[f.target_id].hybrid_classification not in ACCEPTABLE for f in items),
            "items": [{"target_id": f.target_id, "prediction_entity_id": f.prediction_entity_id,
                       "fixed": current[f.target_id].hybrid_classification in ACCEPTABLE,
                       "before": f.hybrid_classification, "after": current[f.target_id].hybrid_classification,
                       "reason": "SOURCE_SUPPORTED_DERIVED_REPRESENTATION" if current[f.target_id].hybrid_classification in ACCEPTABLE
                           else "SOURCE_SUPPORT_INSUFFICIENT_OR_REPRESENTATION_STILL_DISTINCT"} for f in items]}
    metrics = ("hybrid_hard_acceptable", "hybrid_production_coverage", "hybrid_supported_value_accuracy",
               "hybrid_status_accuracy", "hybrid_entity_metrics", "conflicts")
    nr = missingness(after)
    summary = {
        "baseline_reproduced": True, "article_id": gold.article_id,
        "before": {k: before.metrics[k] for k in metrics}, "after": {k: after.metrics[k] for k in metrics},
        "issue_audit": issue_audit, "hard_failures_before": failures(before), "hard_failures_after": failures(after),
        "value_denominator_before": value_breakdown(before), "value_denominator_after": value_breakdown(after),
        "normalization_events": sum(len(e.legacy_fields.get("result_surface", {}).get("events", []))
            for e in [*projected.arm_results, *projected.comparison_results, *projected.comparisons]),
        "source_bindings_created": sum(b["binding_result"] == "BOUND" for b in result.source_bindings),
        "ambiguous_bindings_abstained": sum(b["binding_result"] == "AMBIGUOUS" for b in result.source_bindings),
        "statistic_candidates_unchanged": sum(not e["changed"] for e in result.statistic_events),
        "coverage_promoted_false_conflicts": promoted, "missingness_handoff_counts": dict(Counter(x["gold_status"] for x in nr)),
        "missingness_hard_counts": dict(Counter(x["gold_status"] for x in nr if x["in_hard_denominator"])),
        "missingness_soft_counts": dict(Counter(x["gold_status"] for x in nr if not x["in_hard_denominator"])),
        "api_calls": 0, "frozen_mappings_unchanged": True, "frozen_judgments_unchanged": True,
        "raw_prediction_unchanged": True, "original_evidence_unchanged": True,
        "canonical_revalidation": True, "backlog_after": after.metrics["judge_unavailable_field_count"],
        "attribution": "Deterministic source binding/statistic representation only; no new extraction, LLM judgment or PDF information",
    }
    assert raw.model_dump_json() == original and protected_hashes() == initial
    output.mkdir(parents=True, exist_ok=True)
    artifact = {
        "SUMMARY.json": summary, "CANONICAL_PREDICTION.json": projected.model_dump(mode="json"),
        "HYBRID_REPORT.json": after.model_dump(mode="json"), "SOURCE_SURFACE_CONTEXT.json": context,
        "STATISTIC_REPRESENTATION_NORMALIZATION.json": result.statistic_events,
        "FIELD_SOURCE_BINDINGS.json": result.source_bindings, "SURFACE_CONFLICT_NORMALIZATION.json": result.conflict_events,
        "BEFORE_AFTER_FIELD_EVALUATION.json": changes, "PR5G1_MISSINGNESS_INPUT.json": nr,
        "RUN_MANIFEST.json": {"experiment": "PR5F-2", "base_main_commit": "43278037eeea038018999ac3d3fbe181e51bca4e",
            "baseline_byte_identical": True, "protected_hashes": initial, "api_calls": 0,
            "identity_mapping_sha256": digest([m.model_dump(mode="json") for m in before.entity_matches]),
            "raw_prediction_sha256": sha(previous.PREDICTION),
            "canonical_prediction_payload_sha256": digest(projected.model_dump(mode="json")),
            "source_context_sha256": digest(context), "source_document_sha256": context["source_document_sha256"],
            "source_pdf_sha256": read(ROOT / "benchmarks/2015-06/baseline_v1/RUN_MANIFEST.json")["source_pdf_sha256"],
            "semantic_judge": before.semantic_judge, "historical_judgment_count": len(cache),
            "historical_judgment_payload_hashes": {j["input_sha256"]: digest(j) for j in cache},
            "frozen_cache_only": True, "network_disabled": True, "missingness_unchanged": True,
            "new_semantic_judgments": 0, "public_schema_unchanged": True, "production_gold_input": False},
    }
    for name, value in artifact.items():
        write_json(output / name, value)
    (output / "REPORT.md").write_bytes(render_report(summary).encode("utf-8"))
    return summary


def fraction(metric):
    return f"{metric['numerator']}/{metric['denominator']} ({metric['rate']:.2%})"


def render_report(s):
    lines = ["# PR5F-2 — Result Surface Binding & Statistic Representation", "",
        "只修正已保存 source 的字段绑定和规范化表示。原始 prediction、Gold、Registry、prompt、76条历史judge cache、PR5F identity mappings 均未修改。", "",
        "## Before → after", "", "| Metric | Before | After |", "|---|---:|---:|"]
    for key in ("hybrid_hard_acceptable", "hybrid_production_coverage", "hybrid_supported_value_accuracy", "hybrid_status_accuracy"):
        lines.append(f"| {key} | {fraction(s['before'][key])} | {fraction(s['after'][key])} |")
    for key in ("ArmResult", "ComparisonResult", "Outcome"):
        a, b = s["before"]["hybrid_entity_metrics"][key], s["after"]["hybrid_entity_metrics"][key]
        lines.append(f"| {key} matched | {a['matched']}/{a['gold']} | {b['matched']}/{b['gold']} |")
    lines += ["", "## Confirmed issue-level results", ""]
    for key, value in s["issue_audit"].items():
        lines.append(f"- {key}: {value['before']} → {value['after']}")
        for item in value["items"]:
            lines.append(f"  - {item['target_id']}: {item['before']} → {item['after']} ({item['reason']})")
    lines += ["", "## Coverage formula and supported-value denominator", "",
        "现有coverage计数SUPPORTED、Gold=PRESENT且Prediction=PRESENT的字段。假冲突转PRESENT后新增的覆盖项如下；没有增加Result、没有改分母，也未改任何指标公式。",
        "```json", json.dumps(s["coverage_promoted_false_conflicts"], indent=2), "```",
        "value_kind为SOFT/PARTIAL，不混入SUPPORTED value accuracy分母。", "",
        "```json", json.dumps({"before": s["value_denominator_before"], "after": s["value_denominator_after"]}, indent=2), "```", "",
        "## Source and historical judgment audit", "",
        f"Normalization events: {s['normalization_events']}; scalar bindings: {s['source_bindings_created']}; ambiguous abstentions: {s['ambiguous_bindings_abstained']}; unchanged statistic candidates: {s['statistic_candidates_unchanged']}.",
        "所有生产normalizer/binder均不接收Gold/期望值/跨侧mapping。先按parent comparison和脚注明确列身份，再读取单元格；不按数值搜索。保留完整raw container、原始证据、source row/column/header和选中scalar。",
        "历史value_kind=other的ERROR/WRONG判断仍原样保留；新投影mean走现有evaluator的deterministic exact路径。不是judge改判。",
        "source raw P<0.001仍保存在selected_source_scalar，operator=<、numeric_value=0.001，canonical scalar为<0.001。未填补UNRESOLVED的p_value_comparator。",
        "source-only流程也记录了2条未匹配正文Result的局部P表示（额外4个raw/P字段事件），但其identity仍未解决，评价为UNMATCHED_NOT_SCORED，不进入得分。未合并Outcome或新增comparison。",
        "未绑定的CI/effect等缺失字段不填充；多统计raw角色不明确时停止绑定。计数/百分比记录不被当作mean。",
        "详见STATISTIC_REPRESENTATION_NORMALIZATION.json、FIELD_SOURCE_BINDINGS.json、SURFACE_CONFLICT_NORMALIZATION.json和BEFORE_AFTER_FIELD_EVALUATION.json。", "",
        "## HARD failures and next-stage handoff", "", "```json",
        json.dumps({"before": s["hard_failures_before"], "after": s["hard_failures_after"]}, indent=2), "```",
        "105项identity unresolved、missing Result、bladder balance Outcome歧义、timepoint PARTIAL及SOFT作者/干预completeness不处理。",
        "PR5G1_MISSINGNESS_INPUT.json只整理NR/NA对UNRESOLVED，不进行修复。原先34 NR / 24 NA是HARD口径；全字段清单另含SOFT项，按tier明确区分，并非本PR新增缺失：",
        "```json", json.dumps({"all": s["missingness_handoff_counts"], "HARD": s["missingness_hard_counts"],
                               "SOFT": s["missingness_soft_counts"]}, indent=2), "```", "",
        "API calls = 0。两个完整离线回放须逐字节一致后才发布新快照。", "",
        "本 PR 的变化来自 deterministic source binding / statistic representation normalization，不来自重新 extraction、不来自新的 LLM judgment，也不代表原始 PDF 中出现了新的信息。", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source-markdown", type=Path)
    group.add_argument("--source-context", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()):
        raise ValueError("Output must be below outputs")
    with api_disabled():
        verify_baseline(output.parent / "pr5f2_frozen_baseline")
        context = source_context(args.source_markdown) if args.source_markdown else read(
            args.source_context or SNAPSHOT / "SOURCE_SURFACE_CONTEXT.json")
        a, b = run(output, context), run(output.parent / (output.name + "_replay2"), context)
        assert a == b
        for name in FILES:
            data = (output / name).read_bytes()
            assert data == (output.parent / (output.name + "_replay2") / name).read_bytes(), name
        if args.snapshot:
            SNAPSHOT.mkdir(parents=True, exist_ok=True)
            for name in FILES:
                path, data = SNAPSHOT / name, (output / name).read_bytes()
                if path.exists() and path.read_bytes() != data:
                    raise ValueError("Refusing to overwrite a different frozen surface snapshot")
                path.write_bytes(data)
    print(json.dumps({k: a[k] for k in ("after", "normalization_events", "source_bindings_created",
        "ambiguous_bindings_abstained", "missingness_handoff_counts", "api_calls")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
