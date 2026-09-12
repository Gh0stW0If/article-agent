"""Incrementally adjudicate frozen PR5F-1 FIELD cache misses; default is dry-run."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation.gold_contract import GoldStandardV2
from article_agent.evaluation.registry import load_registry
from article_agent.evaluation.hybrid import HybridEvaluationReportV1, LiveSemanticJudge, load_semantic_registry
from article_agent.evaluation.hybrid.incremental_adjudication import (
    MODEL, ManifestOnlyJudge, merge_judgments, plan_targets, replay_frozen_pairs, validated_successes,
)
from article_agent.evaluation.hybrid.prompts import SEMANTIC_PROMPT_SHA256, SEMANTIC_PROMPT_VERSION
from article_agent.evaluation.hybrid.semantic_judge import canonical_json, digest, write_json

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "benchmarks/2015-06/result_identity_v1"
OLD = ROOT / "benchmarks/2015-06/hybrid_eval_v1/semantic_judgments.json"
PREDICTION = ROOT / "benchmarks/2015-06/baseline_v1/prediction.json"
GOLD = ROOT / "gold/2015-06/gold.json"
SNAPSHOT = ROOT / "benchmarks/2015-06/newly_scorable_adjudication_v1"
OUTPUT = ROOT / "outputs/pr5e2_2015_06_adjudication"
FILES = ("REPORT.md", "SUMMARY.json", "HYBRID_REPORT.json", "NEWLY_SCORABLE_TARGETS.json",
    "planned_api_calls.json", "NEWLY_ADJUDICATED_JUDGMENTS.json", "semantic_judgments.json",
    "NEW_SEMANTIC_ERRORS.md", "NEW_SEMANTIC_PARTIALS.md", "PR5G_EXTRACTION_CANDIDATES.json", "RUN_MANIFEST.json")
GRADES = ("EXACT", "EQUIVALENT", "PARTIAL", "ERROR", "WRONG")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def baseline_module():
    spec = importlib.util.spec_from_file_location("pr5f1_baseline", ROOT / "scripts/pr5f1_result_identity_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protected_hashes():
    before = baseline_module().frozen_hashes()
    paths = [*FROZEN.glob("*"),
        ROOT / "schemas/hybrid-semantic-registry-v1.json",
        ROOT / "src/article_agent/evaluation/hybrid/engine.py",
        ROOT / "src/article_agent/evaluation/hybrid/entity_matcher.py",
        ROOT / "src/article_agent/evaluation/hybrid/semantic_judge.py",
        ROOT / "src/article_agent/evaluation/hybrid/models.py",
        *[p for p in (ROOT / "src/article_agent/result_identity").glob("*") if p.is_file()],
        ROOT / "MinerU method/mineru_method/prompts.py",
        ROOT / "MinerU method/mineru_method/llm.py",
        ROOT / "src/article_agent/trial_topology_agent.py",
        ROOT / "src/article_agent/arm_details_agent.py",
        ROOT / "baml_src/clinical_extraction.baml"]
    before.update({p.relative_to(ROOT).as_posix(): sha(p) for p in paths if p.is_file()})
    return dict(sorted(before.items()))


def check_baseline(directory):
    baseline = baseline_module()
    baseline.baseline_check(directory / "pr5e1")
    from article_agent.result_identity.models import SourceIdentityContext
    context = SourceIdentityContext.model_validate(read(FROZEN / "SOURCE_IDENTITY_CONTEXT.json"))
    summary = baseline.run(directory / "pr5f1", context, baseline_reproduced=True)
    for name in baseline.FILES:
        if (directory / "pr5f1" / name).read_bytes() != (FROZEN / name).read_bytes():
            raise ValueError("STOP: PR5F-1 baseline drift: " + name)
    return summary


def load_inputs():
    return (
        ArticleExtraction.model_validate(read(PREDICTION)),
        GoldStandardV2.model_validate(read(GOLD)),
        load_registry(ROOT / "schemas/evaluator-field-registry-v3.json"),
        load_semantic_registry(ROOT / "schemas/hybrid-semantic-registry-v1.json"),
        HybridEvaluationReportV1.model_validate(read(FROZEN / "HYBRID_REPORT.json")),
        HybridEvaluationReportV1.model_validate(read(ROOT / "benchmarks/2015-06/hybrid_eval_v1/HYBRID_REPORT.json")),
        read(OLD),
    )


def get_plan(inputs):
    plan = plan_targets(*inputs)
    # This is the explicitly requested frozen-article acceptance check, not a
    # hardcoded production selector: the actual target set is computed above.
    expected = {"armResult.timepoint": 12, "comparisonResult.timepoint": 10, "armResult.value_kind": 12}
    actual = dict(Counter(t["field_id"] for t in plan["targets"]))
    if actual != expected or plan["new_unique_api_requests"] != sum(expected.values()):
        raise ValueError("STOP before API: unexpected target set: " + canonical_json(actual))
    if sum(t["in_hard_denominator"] for t in plan["targets"]) != 22:
        raise ValueError("STOP before API: HARD-related target membership drift")
    return plan


def safe_output(path):
    output = Path(path).resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()):
        raise ValueError("Runner writes only below outputs; publishing uses an explicit new snapshot")
    return output


def write_plan(output, plan):
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "NEWLY_SCORABLE_TARGETS.json", plan)
    write_json(output / "planned_api_calls.json", {
        "model": MODEL, "api": "responses", "temperature": 0,
        "prompt_version": SEMANTIC_PROMPT_VERSION, "prompt_sha256": SEMANTIC_PROMPT_SHA256,
        "unique_api_requests": plan["new_unique_api_requests"], "targets": plan["targets"]})


def cached_new(plan, cache_dir):
    result = []
    for key in sorted({t["cache_key"] for t in plan["targets"]}):
        path = cache_dir / (key + ".json")
        if path.exists():
            result.append(read(path))
    # Extra entries cannot be imported via a broad directory glob.
    return result


def adjudicate(plan, old, cache_dir, *, client=None):
    """Only this function can create a live client, after target-set validation."""
    if client is None:
        from article_agent.models import OpenAICompatibleClient
        client = OpenAICompatibleClient(model=MODEL, api_mode="responses", timeout=180)
    names = {t["cache_key"]: t["target_key"] for t in plan["targets"]}
    def progress(event):
        print(json.dumps({"target": names[event["input_sha256"]], "attempt": event["attempt"]},
                         ensure_ascii=False), flush=True)
    # Identical PR5E-1 technical retry defaults: two retries, serial, 10 ms.
    live = LiveSemanticJudge(client, cache_dir, retries=2, progress=progress)
    gated = ManifestOnlyJudge(live, plan, old)
    seen = set()
    for target in plan["targets"]:
        if target["cache_key"] in seen:
            continue
        seen.add(target["cache_key"])
        item = gated.judge(target["request"])
        print(json.dumps({"completed": len(seen), "planned": len(names), "target": target["target_key"],
            "status": item.status, "grade": item.result["grade"] if item.result else None},
            ensure_ascii=False), flush=True)
    return cached_new(plan, cache_dir)


def distribution(artifacts):
    counts = Counter(item["result"]["grade"] for item in artifacts
                     if item["status"] == "SUCCESS" and item["judge_type"] != "ENTITY")
    return {g: counts[g] for g in GRADES}


def category(field):
    if field.hybrid_classification == "JUDGE_UNAVAILABLE":
        return "judge_unavailable"
    if field.semantic_grade:
        grade = field.semantic_grade.value
        return "fully_acceptable" if grade in {"EXACT", "EQUIVALENT"} else grade.lower()
    return "fully_acceptable" if field.value_acceptable is True else "deterministic_mismatch"


def finalize(output, inputs, plan, new, initial_hashes):
    prediction, gold, registry, overlay, before, prior, old = inputs
    combined = merge_judgments(old, new, plan)
    known = {r["input_sha256"] for r in combined}
    # Keep unattempted technical placeholders explicit, never assign them WRONG.
    replay_cache = combined + [j.model_dump(mode="json") for j in before.semantic_judgments
                              if j.input_sha256 not in known]
    prediction_before = prediction.model_dump_json()
    after = replay_frozen_pairs(prediction, gold, registry, overlay, before, replay_cache)
    if prediction.model_dump_json() != prediction_before or protected_hashes() != initial_hashes:
        raise ValueError("STOP: protected input changed")
    after_fields = {f.target_id: f for f in after.field_results}
    targets = {t["target_key"]: t for t in plan["targets"]}
    for previous in before.field_results:
        if previous.target_id not in targets and previous != after_fields[previous.target_id]:
            raise ValueError("STOP: a non-target field changed")
    by_key = {r["input_sha256"]: r for r in new}
    candidates, backlog, grouped = [], 0, {}
    for target in plan["targets"]:
        result = by_key.get(target["cache_key"])
        grade = result["result"]["grade"] if result and result["status"] == "SUCCESS" else "JUDGE_UNAVAILABLE"
        group = "value_kind" if target["field_id"].endswith(".value_kind") else "timepoint"
        grouped.setdefault(group, Counter())[grade] += 1
        if grade == "JUDGE_UNAVAILABLE":
            backlog += 1
        if grade in {"PARTIAL", "ERROR", "WRONG"}:
            candidates.append({
                "target_key": target["target_key"], "entity": target["entity_type"],
                "gold_entity_id": target["gold_entity_id"], "prediction_entity_id": target["prediction_entity_id"],
                "field": target["field_id"], "gold": target["gold"]["value"],
                "prediction": target["prediction"]["value"], "grade": grade,
                "reason": result["result"]["reason"],
                "source_evidence_reference": target["prediction"]["evidence"],
                "judgment_id": result["judgment_id"],
            })
    new_sorted = sorted(new, key=lambda r: r["input_sha256"])
    successful = [r for r in new_sorted if r["status"] == "SUCCESS"]
    technical = [r for r in new_sorted if r["status"] == "JUDGE_UNAVAILABLE"]
    old_hashes = {r["input_sha256"]: digest(r) for r in old}
    combined_keys = {r["input_sha256"]: r for r in combined}
    assert all(digest(combined_keys[key]) == value for key, value in old_hashes.items())
    metric_keys = ("hybrid_hard_acceptable", "hybrid_production_coverage",
                  "hybrid_supported_value_accuracy", "hybrid_status_accuracy",
                  "hybrid_entity_metrics", "hard_failure_decomposition", "failure_decomposition")
    breakdown = Counter(category(f) for f in after.field_results if f.in_value_accuracy_denominator)
    summary = {
        "article_id": gold.article_id,
        "attribution": "Additional frozen adjudication of already extracted and matched fields; no extraction improvement",
        "before": {k: before.metrics[k] for k in metric_keys},
        "after": {k: after.metrics[k] for k in metric_keys},
        "evaluation_backlog_before": len(targets), "evaluation_backlog_after": backlog,
        "judge_unavailable_fields_before": before.metrics["judge_unavailable_field_count"],
        "judge_unavailable_fields_after": after.metrics["judge_unavailable_field_count"],
        "old_cached_judgments_retained": len(old),
        "old_cached_field_judgments_reused": plan["cached_successful_unique_keys_used"],
        "new_target_count": len(targets), "new_api_call_count": sum(r["attempts"] for r in new),
        "successful_new_judgments": len(successful), "technical_failures": len(technical),
        "unattempted_targets": len(targets) - len(new),
        "retry_count": sum(max(0, r["attempts"] - 1) for r in new),
        "call_count_unit": "Existing LiveSemanticJudge client.chat_json attempts; internal transport failover is not a separate semantic rejudgment",
        "semantic_grades": {"existing_frozen_non_entity": distribution(old),
                           "newly_adjudicated": distribution(new),
                           "combined_non_entity": distribution(combined)},
        "old_cache_judge_types": dict(sorted(Counter(r["judge_type"] for r in old).items())),
        "existing_field_only_grades": distribution([r for r in old if r["judge_type"] == "FIELD"]),
        "combined_field_only_grades": distribution([r for r in combined if r["judge_type"] == "FIELD"]),
        "new_grades_by_field_type": {k: {g: c[g] for g in (*GRADES, "JUDGE_UNAVAILABLE")}
                                    for k, c in sorted(grouped.items())},
        "supported_value_accuracy_breakdown": {k: breakdown[k] for k in
            ("fully_acceptable", "partial", "error", "wrong", "deterministic_mismatch", "judge_unavailable")},
        "frozen_mapping_unchanged": True, "old_judgments_unchanged": True,
        "conflicts": after.metrics["conflicts"],
        "offline_replay_api_calls": 0,
    }
    # These are measurements of the unchanged baseline, not selectors or tuning rules.
    taxonomy = before.metrics["hard_failure_decomposition"]
    summary["remaining_nonsemantic_hard_blockers"] = {
        "identity_unresolved": taxonomy["IDENTITY_UNRESOLVED"]["count"],
        "field_or_status_unresolved": taxonomy["A_NOT_EXTRACTED"]["count"],
        "raw_deterministic_mismatch": taxonomy["DETERMINISTIC_VALUE_ERROR"]["count"],
        "spurious_source_conflict": taxonomy["B_STATUS_ERROR"]["count"],
    }
    write_plan(output, plan)
    data = {
        "SUMMARY.json": summary, "HYBRID_REPORT.json": after.model_dump(mode="json"),
        "NEWLY_ADJUDICATED_JUDGMENTS.json": new_sorted,
        "semantic_judgments.json": combined,
        "PR5G_EXTRACTION_CANDIDATES.json": candidates,
        "RUN_MANIFEST.json": {
            "experiment": "PR5E-2", "base_main_commit": "fb587bd3cd328cf68efc8d41e73d0ae3792f9193",
            "model": MODEL, "api": "responses", "temperature": 0,
            "prompt_version": SEMANTIC_PROMPT_VERSION, "prompt_sha256": SEMANTIC_PROMPT_SHA256,
            "prediction_sha256": sha(PREDICTION), "gold_sha256": sha(GOLD),
            "registry_sha256": sha(ROOT / "schemas/evaluator-field-registry-v3.json"),
            "identity_mapping_sha256": digest([m.model_dump(mode="json") for m in before.entity_matches]),
            "identity_audit_file_sha256": sha(FROZEN / "RESULT_IDENTITY_BEFORE_AFTER.json"),
            "old_cache_file_sha256": sha(OLD), "old_judgment_payload_hashes": old_hashes,
            "new_cache_payload_sha256": digest(new_sorted), "combined_cache_payload_sha256": digest(combined),
            "new_api_call_count": summary["new_api_call_count"],
            "call_count_unit": summary["call_count_unit"],
            "successful_judgment_count": len(successful), "technical_failure_count": len(technical),
            "retry_count": summary["retry_count"], "serial_request_delay_seconds": 0.01,
            "technical_retries_per_key": 2, "online_grade_based_retries": 0,
            "offline_replay_api_calls": 0, "baseline_byte_identical": True,
            "protected_hashes": initial_hashes, "old_cache_payloads_unchanged": True,
            "target_manifest_sha256": digest(plan), "all_inputs_frozen": True,
        }}
    for name, value in data.items():
        write_json(output / name, value)
    for name, grades in (("NEW_SEMANTIC_ERRORS.md", {"ERROR", "WRONG"}),
                         ("NEW_SEMANTIC_PARTIALS.md", {"PARTIAL"})):
        chosen = [c for c in candidates if c["grade"] in grades]
        content = "# " + name.removesuffix(".md") + "\n\n"
        content += "Only newly adjudicated semantic field errors; no identity/missingness/raw-binding cases.\n\n"
        content += "\n\n".join("## " + c["target_key"] + "\n\n```json\n" +
                              json.dumps(c, ensure_ascii=False, indent=2) + "\n```" for c in chosen) or "None.\n"
        (output / name).write_bytes((content.rstrip() + "\n").encode("utf-8"))
    (output / "REPORT.md").write_bytes(render_report(summary).encode("utf-8"))
    return summary


def fraction(item):
    return f"{item['numerator']}/{item['denominator']} ({item['rate']:.2%})" if item["rate"] is not None else "N/A"


def render_report(s):
    lines = ["# PR5E-2 — Adjudicate newly scorable frozen fields", "",
        "本次只补充已经存在、已经匹配但此前未冻结评分的字段判断，不代表 extraction 能力提高。", "",
        "## Before → after", "", "| Metric | PR5F-1 | PR5E-2 |", "|---|---|---|"]
    for k in ("hybrid_hard_acceptable", "hybrid_production_coverage", "hybrid_supported_value_accuracy", "hybrid_status_accuracy"):
        lines.append(f"| {k} | {fraction(s['before'][k])} | {fraction(s['after'][k])} |")
    for k in ("ArmResult", "ComparisonResult", "Outcome"):
        a, b = s["before"]["hybrid_entity_metrics"][k], s["after"]["hybrid_entity_metrics"][k]
        lines.append(f"| {k} matched | {a['matched']}/{a['gold']} | {b['matched']}/{b['gold']} |")
    lines += [f"| Identity-unresolved HARD | {s['before']['hard_failure_decomposition']['IDENTITY_UNRESOLVED']['count']} | {s['after']['hard_failure_decomposition']['IDENTITY_UNRESOLVED']['count']} |",
        f"| Evaluation backlog | {s['evaluation_backlog_before']} | {s['evaluation_backlog_after']} |",
        f"| JUDGE_UNAVAILABLE fields | {s['judge_unavailable_fields_before']} | {s['judge_unavailable_fields_after']} |", "",
        "基线真实的JUDGE_UNAVAILABLE为34个零调用占位，并非0；实际已尝试但失败的请求数另列technical_failures。",
        "Coverage公式保持：SUPPORTED且Gold=PRESENT的165项中，已匹配且prediction=PRESENT的72项。补语义评分不改变它。", "",
        "## Cache and calls", "",
        f"旧成功判断保留 {s['old_cached_judgments_retained']} 条，逐条payload哈希不变。其中本次字段评分直接复用 {s['old_cached_field_judgments_reused']} 条；其余历史身份/字段判断保留，不重算。",
        f"新增目标 {s['new_target_count']}；API判断尝试 {s['new_api_call_count']}；成功 {s['successful_new_judgments']}；技术失败 {s['technical_failures']}；retry {s['retry_count']}；未尝试 {s['unattempted_targets']}。",
        s["call_count_unit"], "所有离线重放禁止API。成功grade无论好坏均只冻结一次，不因PARTIAL/ERROR/WRONG重试。", "",
        "## New semantic quality by field family", "", "```json", json.dumps(s["new_grades_by_field_type"], indent=2), "```", "",
        "## Existing / new / combined grades", "",
        "ENTITY判断使用SAME/DIFFERENT/AMBIGUOUS，不能混入五级grade；以下non_entity含历史RESULT_IDENTITY_FIELD，并另列FIELD-only分布。", "",
        "```json", json.dumps({"semantic_grades": s["semantic_grades"],
            "old_cache_judge_types": s["old_cache_judge_types"],
            "existing_field_only_grades": s["existing_field_only_grades"],
            "combined_field_only_grades": s["combined_field_only_grades"]}, indent=2), "```", "",
        "## Supported value accuracy denominator breakdown", "", "```json",
        json.dumps(s["supported_value_accuracy_breakdown"], indent=2), "```", "",
        "## Frozen boundaries and remaining blockers", "",
        "Gold、Registry、prediction、原始字段值/状态/证据、抽取prompt、semantic prompt、model/temperature、identity normalizer/linker、PR5F mappings、评分口径均未修改。",
        "value_kind仍以Gold=mean / Prediction=other送评，未替换为投影层的mean。保留原FIELD证据输入，冻结rubric禁止用证据修补缺失预测内容；未增加任何提示指令。",
        "7个raw字符串不一致、2个假SOURCE_CONFLICT、58个NR/NA缺失状态均未交给judge。", "",
        "```json", json.dumps(s["remaining_nonsemantic_hard_blockers"], indent=2), "```", "",
        "新增PARTIAL见NEW_SEMANTIC_PARTIALS.md；ERROR/WRONG见NEW_SEMANTIC_ERRORS.md。",
        "PR5G_EXTRACTION_CANDIDATES.json只收新增PARTIAL/ERROR/WRONG，不混入身份或缺失状态等问题。", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--judgments", type=Path, help="Offline replay of only new judgments")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=OUTPUT / "new_cache")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args(argv)
    output = safe_output(args.output)
    initial = protected_hashes()
    check_baseline(output.parent / "pr5e2_baseline_check")
    inputs = load_inputs()
    plan = get_plan(inputs)
    write_plan(output, plan)
    print(f"Existing cached judgments retained: {plan['old_successful_cache_count']}", flush=True)
    print(f"Existing cached judgments reused for fields: {plan['cached_successful_unique_keys_used']}", flush=True)
    print(f"New API judgments required: {plan['new_unique_api_requests']}", flush=True)
    if args.dry_run or (not args.live and args.judgments is None):
        print(json.dumps({k: plan[k] for k in ("total_field_targets", "total_scorable_semantic_targets",
            "cached_successful_field_targets", "new_cache_miss_targets", "new_unique_api_requests",
            "technical_unresolved", "excluded_targets_by_reason")}, indent=2), flush=True)
        assert protected_hashes() == initial
        return 0
    if args.live:
        cache_dir = safe_output(args.cache_dir)
        new = adjudicate(plan, inputs[-1], cache_dir)
    else:
        new = read(args.judgments)
    summary = finalize(output, inputs, plan, new, initial)
    for suffix in ("offline_replay_1", "offline_replay_2"):
        replay = output.parent / (output.name + "_" + suffix)
        assert finalize(replay, inputs, plan, new, initial) == summary
        for name in FILES:
            assert (output / name).read_bytes() == (replay / name).read_bytes(), name
    if args.snapshot:
        SNAPSHOT.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            data, dest = (output / name).read_bytes(), SNAPSHOT / name
            if dest.exists() and dest.read_bytes() != data:
                raise ValueError("Refusing to overwrite a different adjudication snapshot")
            dest.write_bytes(data)
    print(json.dumps({k: summary[k] for k in ("successful_new_judgments", "technical_failures",
        "evaluation_backlog_before", "evaluation_backlog_after", "new_grades_by_field_type")}, indent=2), flush=True)
    return 0 if not summary["evaluation_backlog_after"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
