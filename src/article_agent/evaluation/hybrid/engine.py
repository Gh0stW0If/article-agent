"""Read-only hybrid evaluation alongside the unchanged deterministic PR5B engine."""
from collections import Counter
import hashlib

from ..engine import ORDINARY, candidate_set_match, classify, evaluate_article, grounded, ratio, validate_contract
from ..entity_matcher import GROUPS, entities
from .entity_matcher import match_entities_hybrid
from .models import HybridEvaluationReportV1, HybridFieldResult, SemanticGrade
from .prompts import SEMANTIC_PROMPT_SHA256, SEMANTIC_PROMPT_VERSION
from .registry import SemanticRegistryV1
from .semantic_judge import JudgeSession, field_representation, field_request

ACCEPTABLE = {"EXACT", "SEMANTIC_EXACT", "SEMANTIC_EQUIVALENT"}


def _entity_metrics(matches, prediction, gold):
    result = {}
    for kind in GROUPS:
        rows = [m for m in matches if m.entity_type == kind]
        ng, np = len(entities(gold.truth, kind)), len(entities(prediction, kind))
        nm = sum(m.match_status == "MATCHED" for m in rows)
        result[kind] = {
            "gold": ng, "prediction": np, "matched": nm,
            "missing": sum(m.match_status == "MISSING" for m in rows),
            "extra": sum(m.match_status == "EXTRA" for m in rows),
            "ambiguous_gold": sum(m.gold_entity_id is not None and m.match_status in {"AMBIGUOUS", "SPLIT", "MERGED"} for m in rows),
            "ambiguous_prediction": sum(m.prediction_entity_id is not None and m.match_status in {"AMBIGUOUS", "SPLIT", "MERGED"} for m in rows),
            "recall": ratio(nm, ng), "precision": ratio(nm, np),
        }
    return result


def failure_decomposition(fields):
    """Disjoint audit of old failures, not a claim that unresolved identity = missing extraction."""
    buckets = {k: [] for k in (
        "A_NOT_EXTRACTED", "B_STATUS_ERROR", "C_WORDING_OR_IDENTITY_RESCUED",
        "D_PARTIAL", "E_SEMANTIC_ERROR_OR_WRONG", "DETERMINISTIC_VALUE_ERROR",
        "IDENTITY_UNRESOLVED", "JUDGE_UNAVAILABLE", "OTHER")}
    for f in fields:
        if f.gold_status not in ORDINARY or f.deterministic_classification == "EXACT":
            continue
        c = f.hybrid_classification
        if c in ACCEPTABLE:
            bucket = "C_WORDING_OR_IDENTITY_RESCUED"
        elif c == "ENTITY_MISSING":
            bucket = "IDENTITY_UNRESOLVED"
        elif c == "JUDGE_UNAVAILABLE":
            bucket = "JUDGE_UNAVAILABLE"
        elif c == "NOT_EXTRACTED":
            bucket = "A_NOT_EXTRACTED"
        elif c in {"FALSE_NR", "FALSE_PRESENT", "STATUS_WRONG", "SOURCE_CONFLICT_SPURIOUS"}:
            bucket = "B_STATUS_ERROR"
        elif c == "SEMANTIC_PARTIAL":
            bucket = "D_PARTIAL"
        elif c in {"SEMANTIC_ERROR", "SEMANTIC_WRONG"}:
            bucket = "E_SEMANTIC_ERROR_OR_WRONG"
        elif c == "VALUE_WRONG":
            bucket = "DETERMINISTIC_VALUE_ERROR"
        else:
            bucket = "OTHER"
        buckets[bucket].append(f.target_id)
    return {k: {"count": len(v), "target_ids": v} for k, v in buckets.items()}


def evaluate_article_hybrid(prediction, gold, deterministic_registry, semantic_registry, semantic_judge,
                            *, prediction_sha256=None, gold_sha256=None):
    prediction, gold, registry = validate_contract(prediction, gold, deterministic_registry)
    semantic_registry = SemanticRegistryV1.model_validate_json(semantic_registry.model_dump_json())
    overlay = semantic_registry.by_id()
    specs = {f.field_id: f for f in registry.fields}
    if any(k not in specs or specs[k].value_type not in {"string", "list[string]"} for k in overlay):
        raise ValueError("Semantic overlay contains a non-text or unknown base field")
    reference = evaluate_article(prediction, gold, registry)
    old = {f.target_id: f for f in reference.field_results}
    judge = JudgeSession(semantic_judge)
    matches = match_entities_hybrid(prediction, gold, registry, semantic_registry, judge, reference.entity_matches)
    matched = {(m.entity_type, m.gold_entity_id): m.prediction_entity_id
               for m in matches if m.match_status == "MATCHED"}
    fields, conflicts = [], []
    for kind in GROUPS:
        ps = entities(prediction, kind)
        for gid, gentity in entities(gold.truth, kind).items():
            pid = matched.get((kind, gid))
            for spec in sorted((f for f in registry.fields if f.enabled and f.entity_type == kind), key=lambda f: f.field_id):
                g = getattr(gentity, spec.field_path)
                p = getattr(ps[pid], spec.field_path) if pid else None
                classification, value_match = classify(g, p, spec)
                target_id = f"{kind}:{gid}:{spec.field_path}"
                result = HybridFieldResult(
                    target_id=target_id, entity_type=kind, gold_entity_id=gid, prediction_entity_id=pid,
                    field_id=spec.field_id, gold_status=g.status.value, prediction_status=p.status.value if p else None,
                    deterministic_classification=old[target_id].classification,
                    routed_deterministic_classification=classification, hybrid_classification=classification,
                    status_match=p is not None and g.status == p.status, value_acceptable=value_match,
                    gold_value=g.value, prediction_value=p.value if p else None,
                    evaluation_tier=spec.evaluation_tier, support_status=spec.support_status,
                    in_hard_denominator=spec.evaluation_tier == "HARD" and g.status in ORDINARY,
                    in_value_accuracy_denominator=g.status == "PRESENT" and spec.support_status == "SUPPORTED"
                        and p is not None and p.status == "PRESENT")
                if spec.field_id in overlay and g.status == "PRESENT" and p is not None and p.status == "PRESENT":
                    if value_match is True:
                        result.hybrid_classification = "SEMANTIC_EXACT"
                        result.semantic_grade, result.semantic_score = SemanticGrade.EXACT, 1.0
                        result.semantic_method = "DETERMINISTIC_EXACT"
                    else:
                        item = judge.judge(field_request(
                            overlay[spec.field_id], field_representation(gold.truth, g),
                            field_representation(prediction, p)))
                        result.semantic_judgment_id, result.semantic_method = item.judgment_id, "LLM"
                        if item.status == "SUCCESS":
                            result.semantic_grade = SemanticGrade(item.result["grade"])
                            result.semantic_score = item.result["score"]
                            result.hybrid_classification = "SEMANTIC_" + item.result["grade"]
                            result.value_acceptable = item.result["grade"] in {"EXACT", "EQUIVALENT"}
                        else:
                            result.hybrid_classification, result.value_acceptable = "JUDGE_UNAVAILABLE", None
                            result.additional_failures.append("SEMANTIC_JUDGE_ERROR")
                if p and p.status in {"PRESENT", "SOURCE_CONFLICT"} and spec.evidence_policy == "REQUIRED_WHEN_PRESENT":
                    result.evidence_grounded = bool(grounded(prediction, p, kind, pid, spec.field_path))
                    if not result.evidence_grounded:
                        result.additional_failures.append("EVIDENCE_UNGROUNDED")
                if g.status == "SOURCE_CONFLICT":
                    detected = p is not None and p.status == "SOURCE_CONFLICT"
                    conflicts.append({
                        "target_id": target_id, "classification": classification,
                        "candidate_set_match": candidate_set_match(g, p, spec) if detected else None,
                        "gold_candidates": [c.model_dump(mode="json") for c in g.conflict_candidates],
                        "prediction_candidates": [c.model_dump(mode="json") for c in p.conflict_candidates] if detected else [],
                    })
                fields.append(result)
    hard = [f for f in fields if f.in_hard_denominator]
    coverage = [f for f in fields if f.gold_status == "PRESENT" and f.support_status == "SUPPORTED"]
    values = [f for f in fields if f.in_value_accuracy_denominator]
    ordinary = [f for f in fields if f.gold_status in ORDINARY]
    judged = [f for f in fields if f.semantic_method == "LLM" and f.semantic_grade is not None]
    grade_counts = Counter(f.semantic_grade for f in judged)
    detected = sum(c["classification"] == "SOURCE_CONFLICT_DETECTED" for c in conflicts)
    candidate_results = [c for c in conflicts if c["candidate_set_match"] is not None]
    old_pairs = {(m.entity_type, m.gold_entity_id, m.prediction_entity_id)
                 for m in reference.entity_matches if m.match_status == "MATCHED"}
    rescued_entities = [m for m in matches if m.match_status == "MATCHED"
                        and (m.entity_type, m.gold_entity_id, m.prediction_entity_id) not in old_pairs]
    rescued_fields = [f for f in fields if f.deterministic_classification in {
        "VALUE_WRONG", "ENTITY_MISSING"} and f.hybrid_classification in ACCEPTABLE]
    artifacts = judge.artifacts()
    identity_grades = Counter(a.result["grade"] for a in artifacts
                              if a.judge_type == "RESULT_IDENTITY_FIELD" and a.status == "SUCCESS")
    metrics = {
        "hybrid_hard_acceptable": ratio(sum(f.hybrid_classification in ACCEPTABLE for f in hard), len(hard)),
        "hybrid_production_coverage": ratio(len(values), len(coverage)),
        "hybrid_supported_value_accuracy": ratio(sum(f.value_acceptable is True for f in values), len(values)),
        "hybrid_status_accuracy": ratio(sum(f.status_match for f in ordinary), len(ordinary)),
        "semantic_acceptable_accuracy": ratio(sum(f.value_acceptable is True for f in judged), len(judged)),
        "semantic_weighted_score": ratio(sum(f.semantic_score for f in judged), len(judged)),
        "semantic_grade_distribution": {grade: grade_counts[grade] for grade in ("EXACT", "EQUIVALENT", "PARTIAL", "ERROR", "WRONG")},
        "result_identity_grade_distribution": {grade: identity_grades[grade] for grade in ("EXACT", "EQUIVALENT", "PARTIAL", "ERROR", "WRONG")},
        "deterministic_fast_path_count": sum(f.semantic_method == "DETERMINISTIC_EXACT" for f in fields),
        "deterministic_entity_metrics": reference.metrics["entities"],
        "hybrid_entity_metrics": _entity_metrics(matches, prediction, gold),
        "semantic_rescued_entity_count": len(rescued_entities),
        "semantic_rescued_field_count": len(rescued_fields),
        "semantic_confirmed_wrong": sum(f.deterministic_classification in {"VALUE_WRONG", "ENTITY_MISSING"}
                                        and f.semantic_grade in {"ERROR", "WRONG"} for f in fields),
        "judge_failure_count": sum(a.status != "SUCCESS" for a in artifacts),
        "judge_unavailable_field_count": sum(f.hybrid_classification == "JUDGE_UNAVAILABLE" for f in fields),
        "failure_decomposition": failure_decomposition(fields),
        "hard_failure_decomposition": failure_decomposition(hard),
        "conflicts": {
            "gold_conflict_total": len(conflicts), "conflict_detected": detected,
            "conflict_detection_rate": ratio(detected, len(conflicts)),
            "candidate_set_exact": sum(c["candidate_set_match"] for c in candidate_results),
            "candidate_set_accuracy": ratio(sum(c["candidate_set_match"] for c in candidate_results), len(candidate_results)),
        },
    }
    return HybridEvaluationReportV1(
        article_id=gold.article_id, gold_id=gold.gold_id,
        prediction_sha256=prediction_sha256 or hashlib.sha256(prediction.model_dump_json().encode()).hexdigest(),
        gold_sha256=gold_sha256 or hashlib.sha256(gold.model_dump_json().encode()).hexdigest(),
        semantic_judge={"model": judge.model, "prompt_version": SEMANTIC_PROMPT_VERSION,
                        "prompt_sha256": SEMANTIC_PROMPT_SHA256, "temperature": 0},
        deterministic_reference=reference.metrics, entity_matches=matches, field_results=fields,
        conflict_results=conflicts, semantic_judgments=artifacts, metrics=metrics)
