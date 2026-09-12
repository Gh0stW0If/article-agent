"""Offline replay of frozen extraction with source-preserving identity normalization."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.gold_contract import GoldStandardV2
from article_agent.evaluation.registry import load_registry
from article_agent.evaluation.hybrid import HybridEvaluationReportV1, load_semantic_registry
from article_agent.evaluation.hybrid.semantic_judge import write_json
from article_agent.result_identity.evaluation_replay import evaluate_with_canonical_identity
from article_agent.result_identity.models import SourceIdentityContext

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "benchmarks/2015-06/hybrid_eval_v1"
RAW = ROOT / "benchmarks/2015-06/baseline_v1"
FILES = ("REPORT.md", "SUMMARY.json", "HYBRID_REPORT.json", "RESULT_IDENTITY_BEFORE_AFTER.json",
         "RESULT_IDENTITY_NORMALIZATION.json", "RESULT_IDENTITY_UNRESOLVED.json", "RUN_MANIFEST.json",
         "SOURCE_IDENTITY_CONTEXT.json")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_hashes():
    paths = [*(p for directory in (BEFORE, RAW) for p in directory.iterdir() if p.is_file()),
             ROOT / "gold/2015-06/gold.json", ROOT / "schemas/evaluator-field-registry-v3.json",
             ROOT / "schemas/article-extraction.schema.json", ROOT / "src/article_agent/domain/models.py",
             ROOT / "src/article_agent/evaluation/hybrid/prompts.py",
             ROOT / "src/article_agent/evaluation/engine.py",
             ROOT / "src/article_agent/evaluation/entity_matcher.py",
             ROOT / "src/article_agent/evaluation/comparators.py",
             ROOT / "MinerU method/mineru_method/table_parser.py"]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def context_from_markdown(path):
    # The existing lossless parser is reused without changes or any API/classifier call.
    sys.path.insert(0, str(ROOT / "MinerU method"))
    from mineru_method.table_parser import extract_outcome_table_blocks, parse_table_column_map, attach_source_cells
    from article_agent.result_identity.source_context import (
        context_from_table_blocks, explicit_header_blocks, reporting_statements,
    )
    text = Path(path).read_text(encoding="utf-8")
    blocks = explicit_header_blocks(extract_outcome_table_blocks(text, defer_classification=True),
                                   parse_table_column_map, attach_source_cells)
    return context_from_table_blocks(blocks, reporting_statements(text),
                                    source_ref="production/article.md", source_sha256=sha(path))


def baseline_check(output):
    # Reuse the merged PR5E runner, including PR5B byte validation. Never republish its snapshot.
    import runpy
    from article_agent.evaluation.hybrid import CachedSemanticJudge
    script = runpy.run_path(str(ROOT / "scripts/pr5e1_hybrid_evaluate.py"))
    artifacts = json.loads((BEFORE / "semantic_judgments.json").read_text(encoding="utf-8"))
    script["run"](output, CachedSemanticJudge(artifacts=artifacts))
    for name in script["OUTPUT_NAMES"]:
        if (Path(output) / name).read_bytes() != (BEFORE / name).read_bytes():
            raise RuntimeError("BASELINE_DRIFT: " + name)


def run(output, context, *, baseline_reproduced=False):
    initial = frozen_hashes()
    before = HybridEvaluationReportV1.model_validate_json((BEFORE / "HYBRID_REPORT.json").read_text(encoding="utf-8"))
    prediction = ArticleExtraction.model_validate_json((RAW / "prediction.json").read_text(encoding="utf-8"))
    gold = GoldStandardV2.model_validate_json((ROOT / "gold/2015-06/gold.json").read_text(encoding="utf-8"))
    before_dump = prediction.model_dump_json()
    report, links, pp, gp, outcomes = evaluate_with_canonical_identity(
        prediction, gold, load_registry(ROOT / "schemas/evaluator-field-registry-v3.json"),
        load_semantic_registry(ROOT / "schemas/hybrid-semantic-registry-v1.json"),
        before, context, prediction_sha256=sha(RAW / "prediction.json"),
        gold_sha256=sha(ROOT / "gold/2015-06/gold.json"))
    if prediction.model_dump_json() != before_dump or initial != frozen_hashes():
        raise RuntimeError("Protected input changed")
    old, new = before.metrics, report.metrics
    for key in ("hybrid_hard_acceptable", "hybrid_production_coverage"):
        assert new[key]["denominator"] == old[key]["denominator"]
        assert new[key]["numerator"] >= old[key]["numerator"]
    for kind in ("Arm", "Intervention", "Comparison", "Outcome"):
        assert new["hybrid_entity_metrics"][kind]["matched"] >= old["hybrid_entity_metrics"][kind]["matched"]
    previous_pairs = {(m.entity_type, m.gold_entity_id, m.prediction_entity_id)
                      for m in before.entity_matches if m.match_status == "MATCHED"}
    current_pairs = {(m.entity_type, m.gold_entity_id, m.prediction_entity_id)
                     for m in report.entity_matches if m.match_status == "MATCHED"}
    assert previous_pairs <= current_pairs
    for key in ("conflict_detected", "candidate_set_exact"):
        assert new["conflicts"][key] == old["conflicts"][key]
    after_fields = {f.target_id: f for f in report.field_results}
    assert all(after_fields[f.target_id].value_acceptable is True for f in before.field_results if f.value_acceptable is True)
    unresolved = [a for a in links.audit if a.after_status != "MATCHED"]
    summary = {
        "article_id": gold.article_id, "attribution": "identity normalization / canonical linking",
        "production_rerun": False, "numerical_values_used_for_identity": False,
        "before": {k: old[k] for k in ("hybrid_hard_acceptable", "hybrid_production_coverage",
                  "hybrid_supported_value_accuracy", "hybrid_status_accuracy", "hybrid_entity_metrics",
                  "hard_failure_decomposition", "failure_decomposition")},
        "after": {k: new[k] for k in ("hybrid_hard_acceptable", "hybrid_production_coverage",
                 "hybrid_supported_value_accuracy", "hybrid_status_accuracy", "hybrid_entity_metrics",
                 "hard_failure_decomposition", "failure_decomposition")},
        "identity_unresolved_hard": {
            "before": old["hard_failure_decomposition"]["IDENTITY_UNRESOLVED"]["count"],
            "after": new["hard_failure_decomposition"]["IDENTITY_UNRESOLVED"]["count"]},
        "newly_matched_results": sum(a.side == "Gold" and a.after_status == "MATCHED" and a.before_status != "MATCHED" for a in links.audit),
        "remaining_blockers": {side: dict(sorted(Counter(
            code for a in unresolved if a.side == side for code in a.reason_codes).items()))
            for side in ("Gold", "Prediction")},
        "uncached_field_judgments": new["judge_unavailable_field_count"],
        "api_calls": 0, "conflicts": new["conflicts"],
        "raw_representation_preserved": True,
        "previous_successful_identity_pairs_preserved": True,
        "previous_value_correct_targets_preserved": sum(f.value_acceptable is True for f in before.field_results),
        "supported_value_accuracy_breakdown": dict(sorted(Counter(
            f.hybrid_classification for f in report.field_results if f.in_value_accuracy_denominator).items())),
        "new_deterministic_mismatches": [
            {"target_id": f.target_id, "field_id": f.field_id,
             "gold_value": f.gold_value, "prediction_value": f.prediction_value}
            for f in report.field_results if f.in_value_accuracy_denominator
            and f.hybrid_classification == "VALUE_WRONG"],
    }
    def projection_rows(side, projections):
        lookup = {(a.entity_type, a.entity_id): a for a in links.audit if a.side == side}
        return [{"side": side, **p.model_dump(mode="json"), "deterministic_status": "DETERMINISTIC",
                 "mapping_changed": lookup[(p.entity_type, p.entity_id)].before_status != lookup[(p.entity_type, p.entity_id)].after_status}
                for p in projections]
    artifacts = {
        "SUMMARY.json": summary, "HYBRID_REPORT.json": report.model_dump(mode="json"),
        "RESULT_IDENTITY_BEFORE_AFTER.json": [a.model_dump(mode="json") for a in links.audit],
        "RESULT_IDENTITY_UNRESOLVED.json": [a.model_dump(mode="json") for a in unresolved],
        "RESULT_IDENTITY_NORMALIZATION.json": {
            "results": projection_rows("Prediction", pp) + projection_rows("Gold", gp),
            "outcomes": outcomes.model_dump(mode="json")},
        "SOURCE_IDENTITY_CONTEXT.json": context.model_dump(mode="json"),
        "RUN_MANIFEST.json": {
            "experiment": "PR5F-1", "baseline_reproduced": baseline_reproduced,
            "protected_hashes": initial, "source_context_sha256": hashlib.sha256(context.model_dump_json().encode()).hexdigest(),
            "api_calls": 0, "extraction_prompts_changed": False,
            "grading_rules_changed": False, "numerical_values_used_for_identity": False,
            "raw_prediction_sha256": sha(RAW / "prediction.json"),
            "semantic_prompt": before.semantic_judge,
            "judge_policy": "Frozen FIELD judgments only; uncached new field targets remain JUDGE_UNAVAILABLE. No identity grade is repurposed as a field grade.",
        }}
    output = Path(output)
    if output.resolve().is_relative_to(BEFORE) or output.resolve().is_relative_to(RAW):
        raise ValueError("Cannot overwrite frozen baseline")
    output.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        write_json(output / name, data)
    (output / "REPORT.md").write_bytes(render_report(summary, links, outcomes, pp, report).encode("utf-8"))
    return summary


def _fraction(m):
    return f"{m['numerator']}/{m['denominator']} ({m['rate']:.2%})" if m["rate"] is not None else "N/A"


def render_report(summary, links, outcomes, projections, report):
    old, new = summary["before"], summary["after"]
    lines = ["# PR5F-1 — Result Identity Normalization & Canonical Linking", "",
        "PR5F-1 improved canonical result identity resolution. No extraction prompt was changed; newly scorable fields "
        "reflect recovery of previously unresolved result mappings rather than newly extracted source values.", "",
        "原始 prediction、Gold、数值、状态、证据均未改写。只改变身份投影和安全关联。", "",
        "## Before → after", "", "| Metric | PR5E-1 | PR5F-1 |", "|---|---|---|"]
    for kind in ("Arm", "Intervention", "Outcome", "Comparison", "ArmResult", "ComparisonResult"):
        a, b = old["hybrid_entity_metrics"][kind], new["hybrid_entity_metrics"][kind]
        lines.append(f"| {kind} matched | {a['matched']}/{a['gold']} | {b['matched']}/{b['gold']} |")
    for key in ("hybrid_hard_acceptable", "hybrid_production_coverage", "hybrid_supported_value_accuracy", "hybrid_status_accuracy"):
        lines.append(f"| {key} | {_fraction(old[key])} | {_fraction(new[key])} |")
    lines += [f"| Identity-unresolved HARD | {summary['identity_unresolved_hard']['before']} | {summary['identity_unresolved_hard']['after']} |",
        "", f"Newly matched results: {summary['newly_matched_results']}.",
        f"新关联后有 {summary['uncached_field_judgments']} 个字段缺少既有 FIELD Judge 缓存，标记 JUDGE_UNAVAILABLE；本次 API 调用为 0。",
        "Identity EXACT/COMPATIBLE 不会自动成为字段 EXACT；raw value_kind=other、原始时间点和 missing statuses 仍按冻结评分规则评价。",
        "因此 supported value accuracy 若下降，须区分新纳入的未评价字段与原有正确字段的退化；本次原有 value_acceptable=True 的字段全部保持正确。",
        "以下分类解释新的 supported value accuracy 分母；VALUE_WRONG 明细单列，不能将 raw_value 的严格字符串不一致表述成已确认的临床数值错误。",
        "", "```json", json.dumps(summary["supported_value_accuracy_breakdown"], ensure_ascii=False, indent=2), "```",
        "", "### Newly visible deterministic mismatches (grading only, never identity inputs)", "",
        "```json", json.dumps(summary["new_deterministic_mismatches"], ensure_ascii=False, indent=2), "```",
        "", "## Failure decomposition", "",
        "| Category | Ordinary before | Ordinary after | HARD before | HARD after |", "|---|---|---|---|---|"]
    for category in old["failure_decomposition"]:
        lines.append("| " + category + " | " + " | ".join(str(x[family][category]["count"])
            for family in ("failure_decomposition", "hard_failure_decomposition") for x in (old, new)) + " |")
    lines += ["", "## Remaining unmatched reasons", "",
              "Counts below are reason incidences, separated by Gold and Prediction; each result is fully listed in RESULT_IDENTITY_UNRESOLVED.json.",
              "", "```json", json.dumps(summary["remaining_blockers"], ensure_ascii=False, indent=2), "```", "",
              "## Required outcome audit", ""]
    for p in outcomes.projections:
        lines.append(f"- {p.outcome_id}: `{p.raw_name.value}` → `{p.canonical_concept}`; canonical group `{outcomes.canonical_ids[p.outcome_id]}`; source blocks `{p.source_blocks}`.")
    lines += ["", "```json", json.dumps(outcomes.decisions, ensure_ascii=False, indent=2), "```", "",
        "Different source blocks without an explicit common definition/row are not merged. No count/rate numeric agreement was consulted.",
        "", "## Spot checks", "", "| Category | Representative evidence |", "|---|---|"]
    cases = [
        ("canonical exact timepoint", "TIMEPOINT_NORMALIZED_EQUIVALENT"),
        ("normalized ordinal timepoint", "TIMEPOINT_ORDINAL_FORMAT_NORMALIZED"),
        ("anchor-compatible timepoint", "TIMEPOINT_COMPATIBLE_UNSPECIFIED_ANCHOR"),
        ("timepoint contradiction", "TIMEPOINT_CONTRADICTION"),
        ("statistic kind rescued", "STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE"),
        ("unique result link", "UNIQUE_SAFE_RESULT_LINK"),
        ("ambiguous result intentionally abstained", "MULTIPLE_SAFE_CANDIDATES"),
    ]
    for title, reason in cases:
        found = next((a for a in links.audit if reason in a.reason_codes), None)
        if not found:
            pair = next((c for a in links.audit for c in a.candidate_decisions if any(v.reason == reason for v in c.dimensions.values())), None)
            detail = f"{pair.gold_id} ↔ {pair.prediction_id}: {reason}" if pair else "No real case; generic regression fixture covers this case."
        else:
            detail = f"{found.side} {found.entity_id}: {found.after_status}; {found.selected_pair or found.reason_codes}"
        lines.append(f"| {title} | {detail} |")
    lines += ["| statistic kind unresolved | Naked numeric observation + `other` stays `other`; synthetic source-structure negative test. |",
        "| outcome merged | Same source row + explicit construct + count/rate wrappers; synthetic generic fixture (no real forced merge). |",
        "| outcome intentionally not merged | Table and narrative blocks do not supply a shared row/definition bridge; see outcome decisions above. |",
        "", "## Normalization events", ""]
    for p in projections:
        lines.append(f"- {p.entity_id}: raw time `{p.raw_timepoint.value}` → `{p.canonical_timepoint.model_dump(mode='json')}`; "
            f"raw statistic `{p.raw_statistic_kind.value}` → `{p.canonical_statistic_kind}`; rules `{[e.rule for e in p.normalization_events]}`.")
    lines += ["", "## Limitations and follow-up (not implemented here)", "",
        "- Missing baseline/CIC records are not created. Gold-only result targets retain explicit unmatched reasons.",
        "- A statistic inferred safely for identity does not rewrite the raw source field for scoring.",
        "- No new semantic judgment is made for newly scorable fields; these remain visibly unevaluated where necessary.",
        "- Duplicate result candidates are not selected using their values, even if one value exactly equals Gold.",
        "- Existing comparison SOURCE_CONFLICT due to punctuation/case remains a follow-up issue; parent binding was already available.",
        "- No time-unit arithmetic, clinical synonym dictionary, effect-size calculation or automatic pairwise comparison generation.",
        "", "No production rerun. No API. No numerical value was used for identity matching.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source-markdown", type=Path)
    inputs.add_argument("--source-context", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/pr5f1_2015_06_identity")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args(argv)
    baseline_check(args.output.parent / "pr5f1_baseline_replay")
    context = context_from_markdown(args.source_markdown) if args.source_markdown else SourceIdentityContext.model_validate_json(
        args.source_context.read_text(encoding="utf-8"))
    summary = run(args.output, context, baseline_reproduced=True)
    replay = args.output.parent / (args.output.name + "_replay")
    assert run(replay, context, baseline_reproduced=True) == summary
    assert all((args.output / name).read_bytes() == (replay / name).read_bytes() for name in FILES)
    if args.snapshot:
        for kind in ("ArmResult", "ComparisonResult"):
            assert summary["after"]["hybrid_entity_metrics"][kind]["matched"] > 0, "Sanity failure; do not publish"
        destination = ROOT / "benchmarks/2015-06/result_identity_v1"
        destination.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            target, data = destination / name, (args.output / name).read_bytes()
            if target.exists() and target.read_bytes() != data:
                raise ValueError("Refusing to overwrite a different identity snapshot")
            target.write_bytes(data)
    print(json.dumps({k: summary[k] for k in ("newly_matched_results", "identity_unresolved_hard",
        "remaining_blockers", "uncached_field_judgments")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
