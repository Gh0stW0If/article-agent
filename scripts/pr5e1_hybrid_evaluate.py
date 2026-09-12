"""Evaluate the frozen baseline, never production. Default mode is API-free replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.engine import evaluate_article
from article_agent.evaluation.gold_contract import GoldStandardV2
from article_agent.evaluation.registry import load_registry
from article_agent.evaluation.hybrid import (
    CachedSemanticJudge, LiveSemanticJudge, evaluate_article_hybrid, load_semantic_registry,
)
from article_agent.evaluation.hybrid.engine import ACCEPTABLE
from article_agent.evaluation.hybrid.semantic_judge import write_json

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "benchmarks/2015-06/baseline_v1"
GOLD = ROOT / "gold/2015-06/gold.json"
PREDICTION_SHA256 = "ebe87d48a43c065f866b136854da65532d90dcf644e74fc2b33a68eb7cf53ffb"
OUTPUT_NAMES = (
    "HYBRID_REPORT.json", "SUMMARY.json", "REPORT.md", "SEMANTIC_RESCUES.md",
    "SEMANTIC_DISAGREEMENTS.md", "semantic_judgments.json", "RUN_MANIFEST.json",
)
PROTECTED = (
    GOLD, ROOT / "schemas/evaluator-field-registry-v3.json",
    ROOT / "src/article_agent/evaluation/engine.py",
    ROOT / "src/article_agent/evaluation/entity_matcher.py",
    ROOT / "src/article_agent/evaluation/comparators.py",
    ROOT / "src/article_agent/evaluation/models.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protected_hashes():
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(
        [*PROTECTED, *(p for p in BASELINE.rglob("*") if p.is_file())])}


def replay_pr5b(prediction, gold, registry):
    reference = evaluate_article(prediction, gold, registry)
    expected = {"hard_exact": (6, 271), "production_coverage": (6, 165), "supported_value_accuracy": (6, 6)}
    for key, (n, d) in expected.items():
        assert reference.metrics[key]["numerator"] == n and reference.metrics[key]["denominator"] == d
    conflicts = reference.metrics["conflicts"]
    assert conflicts["conflict_detected"] == conflicts["gold_conflict_total"] == 2
    assert conflicts["candidate_set_exact"] == conflicts["candidate_set_evaluated"] == 2
    original = (BASELINE / "evaluation.json").read_bytes()
    rendered = reference.model_dump_json(indent=2) + "\n"
    if b"\r\n" in original:
        rendered = rendered.replace("\n", "\r\n")
    assert rendered.encode("utf-8") == original, "PR5B replay differs from frozen evaluation bytes"
    return reference


def summary_for(report):
    m = report.metrics
    return {
        "article_id": report.article_id, "prediction_sha256": report.prediction_sha256,
        "deterministic_reference": report.deterministic_reference,
        "hybrid": {
            "hard_acceptable": m["hybrid_hard_acceptable"],
            "production_coverage": m["hybrid_production_coverage"],
            "supported_value_accuracy": m["hybrid_supported_value_accuracy"],
            "status_accuracy": m["hybrid_status_accuracy"],
            "semantic_acceptable_accuracy": m["semantic_acceptable_accuracy"],
            "semantic_weighted_score": m["semantic_weighted_score"],
        },
        "semantic_grades": m["semantic_grade_distribution"],
        "result_identity_grades": m["result_identity_grade_distribution"],
        "entity_metrics": {"deterministic": m["deterministic_entity_metrics"], "hybrid": m["hybrid_entity_metrics"]},
        "semantic_rescued_fields": m["semantic_rescued_field_count"],
        "semantic_rescued_entities": m["semantic_rescued_entity_count"],
        "semantic_confirmed_wrong": m["semantic_confirmed_wrong"],
        "judge_failures": m["judge_failure_count"],
        "judge_unavailable_fields": m["judge_unavailable_field_count"],
        "failure_decomposition": m["failure_decomposition"],
        "hard_failure_decomposition": m["hard_failure_decomposition"],
        "conflicts": m["conflicts"],
        "semantic_metric_scope": "Successful LLM FIELD judgments only; deterministic fast paths and identity decisions excluded.",
    }


def fraction(value):
    return f"{value['numerator']} / {value['denominator']} ({value['rate']:.2%})" if value["rate"] is not None else "N/A (0 denominator)"


def _text(value):
    return json.dumps(value, ensure_ascii=False).replace("|", "\\|").replace("\n", " ")


def audit_text(report, prediction, gold):
    by_judgment = {j.judgment_id: j for j in report.semantic_judgments}
    old_entities = report.deterministic_reference["entities"]
    rescues = ["# Semantic rescues — manual review required", "",
        "Counts include structural-context/dependency rescue as well as LLM wording rescue; method is explicit.", ""]
    disagreements = ["# Semantic disagreements — no rejudging for higher scores", ""]
    from article_agent.evaluation.entity_matcher import entities
    from article_agent.evaluation.entity_matcher import match_entities
    old = match_entities(prediction, gold)[0]
    locked = {(m.entity_type, m.gold_entity_id, m.prediction_entity_id) for m in old if m.match_status == "MATCHED"}
    for m in report.entity_matches:
        if m.match_status != "MATCHED" or (m.entity_type, m.gold_entity_id, m.prediction_entity_id) in locked:
            continue
        g, p = entities(gold.truth, m.entity_type)[m.gold_entity_id], entities(prediction, m.entity_type)[m.prediction_entity_id]
        identity_names = {
            "Intervention": ("name", "kind"), "Outcome": ("name", "instrument"),
            "Comparison": ("arm_ids", "relation", "contrast"),
            "ArmResult": ("arm_id", "outcome_id", "timepoint", "analysis_set", "value_kind"),
            "ComparisonResult": ("comparison_id", "outcome_id", "timepoint", "analysis_set", "effect_measure"),
        }[m.entity_type]
        def values(obj):
            return {k: getattr(obj, k).model_dump(mode="json") if hasattr(getattr(obj, k), "model_dump")
                    else getattr(obj, k) for k in identity_names}
        reasons = [by_judgment[j].result["reason"] for j in m.semantic_judgment_ids
                   if by_judgment[j].result is not None]
        old_statuses = [x.match_status for x in old if x.entity_type == m.entity_type
                       and (x.gold_entity_id == m.gold_entity_id or x.prediction_entity_id == m.prediction_entity_id)]
        rescues += [f"## Entity {m.entity_type}: {m.gold_entity_id} → {m.prediction_entity_id}", "",
                    f"Old: {old_statuses}; New: MATCHED; method: {m.match_method}; field grade: N/A.",
                    "Gold: " + _text(values(g)), "Prediction: " + _text(values(p)),
                    "Reason: " + ("; ".join(reasons) or "Deterministic structural context; no LLM decision."), ""]
    for f in report.field_results:
        judgment = by_judgment.get(f.semantic_judgment_id)
        reason = judgment.result["reason"] if judgment and judgment.result else (
            "Deterministic value/status comparison after structural or parent-identity rescue.")
        details = [f"## {f.target_id}", "",
                   f"Gold ({f.gold_status}): {_text(f.gold_value)}",
                   f"Prediction ({f.prediction_status}): {_text(f.prediction_value)}",
                   f"Old: {f.deterministic_classification}; New: {f.hybrid_classification}; grade: {f.semantic_grade.value if f.semantic_grade else None}",
                   f"Method: {f.semantic_method}; judgment: {f.semantic_judgment_id}", "Reason: " + reason, ""]
        if f.deterministic_classification in {"VALUE_WRONG", "ENTITY_MISSING"} and f.hybrid_classification in ACCEPTABLE:
            rescues += details
        if f.semantic_grade in {"PARTIAL", "ERROR", "WRONG"} or f.hybrid_classification == "JUDGE_UNAVAILABLE":
            disagreements += details
            if judgment and judgment.result:
                disagreements += ["Details: " + _text(judgment.result), ""]
    disagreements += ["## Identity rejections and uncertainty (not ordinary field accuracy)", "",
        "These decisions can block Result matching. They are not silently counted as ordinary field WRONG "
        "and are not omitted from the manual audit.", ""]
    for item in report.semantic_judgments:
        if item.judge_type == "FIELD":
            continue
        rejected = item.status != "SUCCESS" or (
            item.result.get("grade") in {"PARTIAL", "ERROR", "WRONG"}
            or item.result.get("decision") in {"DIFFERENT", "AMBIGUOUS"})
        if rejected:
            disagreements += [f"### {item.judgment_id}", "",
                f"{item.judge_type}: {item.field_id or item.entity_type}",
                "Gold: " + _text(item.gold_representation),
                "Prediction: " + _text(item.prediction_representation),
                "Judgment: " + _text(item.result), ""]
    lines = ["# PR5E-1 — Frozen 2015-06 hybrid evaluator experiment", "",
        "Same frozen prediction, no production rerun. Gold, Registry V3 and PR5B are unchanged.", "",
        "## Deterministic PR5B baseline", "",
        "| Metric | Unchanged result |", "|---|---|"]
    for key in ("hard_exact", "production_coverage", "supported_value_accuracy"):
        lines.append(f"| {key} | {fraction(report.deterministic_reference[key])} |")
    for kind in ("Outcome", "Comparison", "Intervention"):
        lines.append(f"| {kind} matched | {old_entities[kind]['matched']} / {old_entities[kind]['gold']} |")
    lines += ["", "## Hybrid semantic evaluation", "", "| Metric | Result |", "|---|---|"]
    for key, value in summary_for(report)["hybrid"].items():
        lines.append(f"| {key} | {fraction(value)} |")
    lines += ["", "| Entity | Deterministic matched | Hybrid matched | Gold | Ambiguous Gold |", "|---|---|---|---|---|"]
    for kind, new in report.metrics["hybrid_entity_metrics"].items():
        lines.append(f"| {kind} | {old_entities[kind]['matched']} | {new['matched']} | {new['gold']} | {new['ambiguous_gold']} |")
    lines += ["", "## Grade and technical audit", "",
        "Grade distribution (successful LLM field targets only): " + _text(report.metrics["semantic_grade_distribution"]),
        "Result-identity grade distribution (unique pair judgments, separate denominator): "
        + _text(report.metrics["result_identity_grade_distribution"]),
        f"Deterministic semantic fast paths: {report.metrics['deterministic_fast_path_count']}.",
        f"Rescued entities: {report.metrics['semantic_rescued_entity_count']}; rescued fields: {report.metrics['semantic_rescued_field_count']}.",
        f"LLM-confirmed ERROR/WRONG among old failures: {report.metrics['semantic_confirmed_wrong']}.",
        f"Judge failures: {report.metrics['judge_failure_count']}; unavailable field targets: {report.metrics['judge_unavailable_field_count']}.",
        "Semantic accuracy excludes technical failures; they are JUDGE_UNAVAILABLE, never WRONG. Fixed HARD/coverage denominators are unchanged. "
        "If any judge is unavailable, aggregate acceptable rates are conservative observed rates, not a resolved assessment of those targets.",
        "Conflicts: " + _text(report.metrics["conflicts"]), "",
        "## Why was the baseline low?", "",
        "The following is a disjoint decomposition of prior ordinary-target failures. "
        "Identity-ambiguous targets are kept separate: absence of a match does NOT prove absence of extraction.",
        "", "| Category | All ordinary old failures | HARD old failures |", "|---|---|---|"]
    labels = {
        "A_NOT_EXTRACTED": "A — Matched entity, field not extracted",
        "B_STATUS_ERROR": "B — Status error",
        "C_WORDING_OR_IDENTITY_RESCUED": "C — Wording/identity mismatch rescued",
        "D_PARTIAL": "D — Partial, not fully correct",
        "E_SEMANTIC_ERROR_OR_WRONG": "E — Related-but-incorrect or wrong semantic content",
        "DETERMINISTIC_VALUE_ERROR": "Deterministic value mismatch (not semantic)",
        "IDENTITY_UNRESOLVED": "Identity still unresolved (cannot assign to A–E)",
        "JUDGE_UNAVAILABLE": "Judge unavailable (not prediction wrong)", "OTHER": "Other",
    }
    for key, label in labels.items():
        lines.append(f"| {label} | {report.metrics['failure_decomposition'][key]['count']} | {report.metrics['hard_failure_decomposition'][key]['count']} |")
    lines += ["", "### Result identity blockers (not ordinary field grades)", "",
        "Identity judgments do not use observed values, estimates, CI or P to choose a result. "
        "A semantic identity failure is not evidence that every downstream value is wrong.",
        "", "| Identity field | Gold | Prediction | Grade | Reason |", "|---|---|---|---|---|"]
    for item in report.semantic_judgments:
        if item.judge_type == "RESULT_IDENTITY_FIELD":
            lines.append(f"| {item.field_id} | {_text(item.gold_representation['value'])} | "
                f"{_text(item.prediction_representation['value'])} | "
                f"{item.result['grade'] if item.result else item.status} | "
                f"{_text(item.result['reason']) if item.result else 'Technical failure'} |")
    lines += ["", "Missing identity qualifiers and unresolved parent bindings are also retained. "
        "See the complete identity-only inputs below; these never include result values.", "",
        "| Side | Entity | ID | Parent | Outcome | Timepoint (status/value) | Analysis set | Statistic kind | Derived |",
        "|---|---|---|---|---|---|---|---|---|"]
    for side, graph in (("Gold", gold.truth), ("Prediction", prediction)):
        for kind in ("ArmResult", "ComparisonResult"):
            for eid, entity in entities(graph, kind).items():
                parent = entity.arm_id if kind == "ArmResult" else entity.comparison_id
                statistic = entity.value_kind if kind == "ArmResult" else entity.effect_measure
                show = lambda f: f"{f.status.value}: {_text(f.value)}"
                lines.append(f"| {side} | {kind} | {eid} | {parent} | {entity.outcome_id} | "
                             f"{show(entity.timepoint)} | {show(entity.analysis_set)} | {show(statistic)} | {entity.derived} |")
    lines += ["", "## Required manual spot checks", "",
        "| Target | Gold | Prediction | Old | Hybrid |", "|---|---|---|---|---|"]
    for f in report.field_results:
        if f.field_id in {"study.condition", "intervention.name", "outcome.name", "outcome.instrument",
                          "comparison.relation", "comparison.contrast"}:
            lines.append(f"| {f.target_id} | {f.gold_status}: {_text(f.gold_value)} | {f.prediction_status}: {_text(f.prediction_value)} | {f.deterministic_classification} | {f.hybrid_classification} |")
    lines += ["", "## Unresolved identity graph", ""]
    for m in report.entity_matches:
        if m.match_status in {"AMBIGUOUS", "SPLIT", "MERGED"}:
            lines.append(f"- {m.entity_type} {m.gold_entity_id or m.prediction_entity_id}: {m.match_status}; {m.diagnostic}")
    lines += ["", "## Reproducibility", "", "Judge: " + _text(report.semantic_judge),
        "Prediction SHA256: `" + report.prediction_sha256 + "`.",
        "Successful judgments are never retried for their grade. Only technical retries are allowed.",
        "Offline replay loads frozen judgments only; RUN_MANIFEST records protected input hashes.",
        "Review SEMANTIC_RESCUES.md and SEMANTIC_DISAGREEMENTS.md before any extraction optimization.", ""]
    return {"REPORT.md": "\n".join(lines), "SEMANTIC_RESCUES.md": "\n".join(rescues),
            "SEMANTIC_DISAGREEMENTS.md": "\n".join(disagreements)}


def run(output, judge):
    before = protected_hashes()
    assert sha(BASELINE / "prediction.json") == PREDICTION_SHA256
    prediction = ArticleExtraction.model_validate_json((BASELINE / "prediction.json").read_text(encoding="utf-8"))
    gold = GoldStandardV2.model_validate_json(GOLD.read_text(encoding="utf-8"))
    assert gold.state == "FROZEN" and gold.gold_id == "2015-06-gold-v1"
    registry = load_registry(ROOT / "schemas/evaluator-field-registry-v3.json")
    reference = replay_pr5b(prediction, gold, registry)
    report = evaluate_article_hybrid(prediction, gold, registry,
        load_semantic_registry(ROOT / "schemas/hybrid-semantic-registry-v1.json"), judge,
        prediction_sha256=PREDICTION_SHA256, gold_sha256=sha(GOLD))
    assert report.deterministic_reference == reference.metrics
    assert report.metrics["conflicts"]["conflict_detected"] == 2
    assert report.metrics["conflicts"]["candidate_set_exact"] == 2
    assert before == protected_hashes(), "Protected input changed"
    output = Path(output).resolve()
    if output == ROOT or output.is_relative_to(BASELINE) or output.is_relative_to(ROOT / "gold"):
        raise ValueError("Refusing to write to protected input directory")
    output.mkdir(parents=True, exist_ok=True)
    data = {
        "HYBRID_REPORT.json": report.model_dump(mode="json"),
        "SUMMARY.json": summary_for(report),
        "semantic_judgments.json": [j.model_dump(mode="json") for j in report.semantic_judgments],
        "RUN_MANIFEST.json": {
            "experiment": "PR5E-1", "mode": "frozen-judge-evaluation", "production_rerun": False,
            "semantic_judge": report.semantic_judge,
            "prediction_sha256": PREDICTION_SHA256,
            "protected_input_hashes": before,
            "semantic_registry_sha256": sha(ROOT / "schemas/hybrid-semantic-registry-v1.json"),
            "pr5b_replay_byte_identical": True,
            "judgment_count": len(report.semantic_judgments),
            "technical_retry_count": sum(max(0, j.attempts - 1) for j in report.semantic_judgments),
            "judge_failure_count": report.metrics["judge_failure_count"],
        },
    }
    for name, value in data.items():
        write_json(output / name, value)
    for name, text in audit_text(report, prediction, gold).items():
        (output / name).write_bytes((text.rstrip() + "\n").encode("utf-8"))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable the evaluator-only Responses API")
    parser.add_argument("--model", default=None)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "outputs/pr5e1_semantic_cache")
    parser.add_argument("--judgments", type=Path, help="Frozen semantic_judgments.json, API-free replay")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/pr5e1_2015_06_hybrid")
    parser.add_argument("--snapshot", action="store_true", help="Publish only after byte-identical offline replay")
    args = parser.parse_args(argv)
    if args.live and args.judgments:
        parser.error("--live and --judgments are mutually exclusive")
    if args.live:
        from article_agent.models import OpenAICompatibleClient, load_env_file
        load_env_file()
        client = OpenAICompatibleClient(model=args.model or os.getenv("ARTICLE_AGENT_SEMANTIC_JUDGE_MODEL", "gpt-5.6-sol"),
                                        timeout=180, api_mode="responses")
        judge = LiveSemanticJudge(client, args.cache_dir,
            progress=lambda value: print(json.dumps(value), flush=True))
    else:
        artifacts = json.loads(args.judgments.read_text(encoding="utf-8")) if args.judgments else None
        judge = CachedSemanticJudge(None if artifacts is not None else args.cache_dir,
                                    artifacts=artifacts, model=args.model or "gpt-5.6-sol")
    report = run(args.output, judge)
    if args.snapshot:
        frozen = json.loads((args.output / "semantic_judgments.json").read_text(encoding="utf-8"))
        replay_dir = args.output.parent / (args.output.name + "_replay")
        replay_judge = CachedSemanticJudge(artifacts=frozen, model=judge.model)
        run(replay_dir, replay_judge)
        for name in OUTPUT_NAMES:
            assert (args.output / name).read_bytes() == (replay_dir / name).read_bytes(), name
        destination = ROOT / "benchmarks/2015-06/hybrid_eval_v1"
        destination.mkdir(parents=True, exist_ok=True)
        for name in OUTPUT_NAMES:
            target = destination / name
            if target.exists() and target.read_bytes() != (args.output / name).read_bytes():
                raise ValueError(f"Refusing to overwrite a different frozen snapshot: {name}")
            shutil.copyfile(args.output / name, target)
    summary = summary_for(report)
    print(json.dumps({k: summary[k] for k in (
        "article_id", "hybrid", "semantic_grades", "result_identity_grades",
        "semantic_rescued_fields", "semantic_rescued_entities", "judge_failures")}, ensure_ascii=False, indent=2))
    return 0 if report.metrics["judge_failure_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
