"""Offline deterministic evaluation of canonical predictions against Gold 2.0."""
import argparse
from collections import Counter
import json
from pathlib import Path
from ..domain.models import ArticleExtraction
from .gold_contract import GoldStandardV2
from .registry import EvaluatorRegistryV3, load_registry
from .registry_audit import ENTITIES, VALUE_COMPARATORS, _canonical_fields
from .normalization import OPERATIONS
from .comparators import compare_values
from .entity_matcher import GROUPS, entities, match_entities
from .models import EvaluationReportV2, FieldResult

ORDINARY = {"PRESENT", "NOT_REPORTED", "NOT_APPLICABLE"}


def ratio(numerator, denominator):
    return {"numerator":numerator,"denominator":denominator,
            "rate":numerator/denominator if denominator else None}


def validate_contract(prediction, gold, registry):
    # Round trips deliberately revalidate model_copy/model_construct inputs too.
    prediction = ArticleExtraction.model_validate_json(prediction.model_dump_json())
    gold = GoldStandardV2.model_validate_json(gold.model_dump_json())
    registry = EvaluatorRegistryV3.model_validate_json(registry.model_dump_json())
    if prediction.article.article_id != gold.article_id:
        raise ValueError("Article ID mismatch: contract error; no accuracy calculated")
    if registry.registry_version != "EVALUATOR_FIELD_REGISTRY/3.0.0" or registry.article_schema_version != "ARTICLE_EXTRACTION/2.0":
        raise ValueError("Unsupported registry/schema version")
    if set(GROUPS) - set(registry.entities):
        raise ValueError("Missing entity identity rule")
    domain = _canonical_fields()
    registered = set()
    for f in registry.fields:
        if f.entity_type not in ENTITIES or f.field_path not in ENTITIES[f.entity_type].model_fields:
            raise ValueError(f"Invalid field_path: {f.field_id}:{f.field_path}")
        expected_id = f.entity_type[0].lower()+f.entity_type[1:]+"."+f.field_path
        if f.field_id != expected_id or f.field_id not in domain:
            raise ValueError(f"Field ID/path mismatch: {f.field_id}")
        registered.add(f.field_id)
        if f.value_type != domain[f.field_id][0]:
            raise ValueError(f"Value type mismatch: {f.field_id}")
        if set(f.normalization) - set(OPERATIONS):
            raise ValueError(f"Unknown normalization operation: {f.field_id}")
        if f.normalization and f.value_type not in {"string", "list[string]"}:
            raise ValueError("String normalization applied to non-string field")
        if f.enabled and (f.comparator or {}).get("type") not in VALUE_COMPARATORS[f.value_type]:
            raise ValueError(f"Comparator type mismatch: {f.field_id}")
    if set(domain) - registered:
        raise ValueError("Unregistered canonical fields")
    return prediction, gold, registry


def grounded(graph, field, kind, entity_id, name):
    by_id = {e.evidence_id:e for e in graph.evidence}
    lists = [field.evidence_ids]
    if field.status == "SOURCE_CONFLICT":
        lists = [c.evidence_ids for c in field.conflict_candidates]
        if field.evidence_ids:
            lists.append(field.evidence_ids)
    return bool(lists) and all(ids and all(
        eid in by_id and any(t.entity_type==kind and t.entity_id==entity_id and t.field_id==name
                             for t in by_id[eid].targets) for eid in ids) for ids in lists)


def candidate_set_match(gold_field, prediction_field, registry_field):
    gs, ps = gold_field.conflict_candidates, prediction_field.conflict_candidates
    if len(gs) != len(ps):
        return False
    if any(c.value is None for c in gs+ps):
        return None
    # Bipartite perfect matching handles overlapping numeric tolerances without greedy loss.
    edges = [[j for j,p in enumerate(ps) if compare_values(g.value,p.value,registry_field).matched] for g in gs]
    assigned = {}
    def augment(i, seen):
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in assigned or augment(assigned[j], seen):
                assigned[j] = i
                return True
        return False
    return all(augment(i,set()) for i in range(len(gs)))


def classify(g, p, registry_field):
    if g.status == "REVIEW_REQUIRED":
        return None, None
    if g.status == "SOURCE_CONFLICT":
        return ("SOURCE_CONFLICT_DETECTED" if p and p.status=="SOURCE_CONFLICT" else "SOURCE_CONFLICT_MISSED"), None
    if registry_field.required and registry_field.support_status == "UNSUPPORTED":
        return "REQUIRED_BUT_UNSUPPORTED", None
    if p is None:
        return "ENTITY_MISSING", None
    if p.status == "SOURCE_CONFLICT":
        return "SOURCE_CONFLICT_SPURIOUS", None
    if p.status in {"UNRESOLVED", "INSUFFICIENT_CONTEXT"}:
        return "NOT_EXTRACTED", None
    if g.status == p.status:
        if g.status != "PRESENT":
            return "EXACT", None
        matched = compare_values(g.value,p.value,registry_field).matched
        return ("EXACT" if matched else "VALUE_WRONG"), matched
    if p.status == "PRESENT":
        return "FALSE_PRESENT", None
    if g.status == "PRESENT" and p.status == "NOT_REPORTED":
        return "FALSE_NR", None
    return "STATUS_WRONG", None


def evaluate_article(prediction, gold, registry):
    prediction, gold, registry = validate_contract(prediction,gold,registry)
    matches, failures = match_entities(prediction,gold)
    matched = {(m.entity_type,m.gold_entity_id):m.prediction_entity_id for m in matches if m.match_status=="MATCHED"}
    fields, conflicts = [], []
    for kind in GROUPS:
        ps = entities(prediction,kind)
        for gid, gentity in entities(gold.truth,kind).items():
            pid = matched.get((kind,gid))
            for spec in sorted((f for f in registry.fields if f.enabled and f.entity_type==kind),key=lambda f:f.field_id):
                g = getattr(gentity,spec.field_path)
                p = getattr(ps[pid],spec.field_path) if pid else None
                classification, value_match = classify(g,p,spec)
                result = FieldResult(target_id=f"{kind}:{gid}:{spec.field_path}",entity_type=kind,
                    gold_entity_id=gid,prediction_entity_id=pid,field_id=spec.field_id,
                    comparator=(spec.comparator or {}).get("type"),evaluation_tier=spec.evaluation_tier,
                    support_status=spec.support_status,gold_status=g.status.value,
                    prediction_status=p.status.value if p else None,status_match=p is not None and g.status==p.status,
                    value_match=value_match,classification=classification,gold_value=g.value,
                    prediction_value=p.value if p else None,
                    in_hard_denominator=spec.evaluation_tier=="HARD" and g.status in ORDINARY,
                    in_value_accuracy_denominator=g.status=="PRESENT" and spec.support_status=="SUPPORTED" and p is not None and p.status=="PRESENT")
                if g.status == "REVIEW_REQUIRED":
                    result.diagnostic = "Gold review required; excluded from ordinary scoring"
                if p and p.status in {"PRESENT","SOURCE_CONFLICT"} and spec.evidence_policy=="REQUIRED_WHEN_PRESENT":
                    result.evidence_grounded = bool(grounded(prediction,p,kind,pid,spec.field_path))
                    if not result.evidence_grounded:
                        result.additional_failures.append("EVIDENCE_UNGROUNDED")
                if g.status == "SOURCE_CONFLICT":
                    detected = p is not None and p.status=="SOURCE_CONFLICT"
                    conflicts.append({"target_id":result.target_id,"classification":classification,
                        "candidate_set_match":candidate_set_match(g,p,spec) if detected else None,
                        "gold_candidates":[c.model_dump(mode="json") for c in g.conflict_candidates],
                        "prediction_candidates":[c.model_dump(mode="json") for c in p.conflict_candidates] if detected else []})
                fields.append(result)
    hard = [f for f in fields if f.in_hard_denominator]
    coverage = [f for f in fields if f.gold_status=="PRESENT" and f.support_status=="SUPPORTED"]
    values = [f for f in fields if f.in_value_accuracy_denominator]
    ordinary = [f for f in fields if f.gold_status in ORDINARY]
    evidence = [f for f in fields if f.evidence_grounded is not None and f.gold_status!="REVIEW_REQUIRED"]
    detected = sum(c["classification"]=="SOURCE_CONFLICT_DETECTED" for c in conflicts)
    candidate_results = [c for c in conflicts if c["candidate_set_match"] is not None]
    metrics = {
        "hard_exact":ratio(sum(f.classification=="EXACT" for f in hard),len(hard)),
        "production_coverage":ratio(len(values),len(coverage)),
        "supported_value_accuracy":ratio(sum(f.value_match is True for f in values),len(values)),
        "status_accuracy":ratio(sum(f.status_match for f in ordinary),len(ordinary)),
        "evidence_grounding":ratio(sum(f.evidence_grounded for f in evidence),len(evidence)),
        "conflicts":{"gold_conflict_total":len(conflicts),"conflict_detected":detected,
            "conflict_missed":len(conflicts)-detected,"conflict_detection_rate":ratio(detected,len(conflicts)),
            "spurious_conflict_count":sum(f.classification=="SOURCE_CONFLICT_SPURIOUS" for f in fields),
            "candidate_set_exact":sum(c["candidate_set_match"] for c in candidate_results),
            "candidate_set_evaluated":len(candidate_results),
            "candidate_set_accuracy":ratio(sum(c["candidate_set_match"] for c in candidate_results),len(candidate_results))},
        "entities":{},
    }
    for kind in GROUPS:
        rows = [m for m in matches if m.entity_type==kind]
        ng, np = len(entities(gold.truth,kind)),len(entities(prediction,kind))
        nm = sum(m.match_status=="MATCHED" for m in rows)
        metrics["entities"][kind] = {"gold":ng,"prediction":np,"matched":nm,
            "missing":sum(m.match_status=="MISSING" for m in rows),
            "extra":sum(m.match_status=="EXTRA" for m in rows),
            "ambiguous_gold":sum(m.gold_entity_id is not None and m.match_status in {"AMBIGUOUS","SPLIT","MERGED"} for m in rows),
            "ambiguous_prediction":sum(m.prediction_entity_id is not None and m.match_status in {"AMBIGUOUS","SPLIT","MERGED"} for m in rows),
            "recall":ratio(nm,ng),"precision":ratio(nm,np)}
    counts = Counter()
    for f in fields:
        if f.classification and f.classification!="EXACT":
            counts[f.classification]+=1
        if f.gold_status != "REVIEW_REQUIRED":
            counts.update(f.additional_failures)
    return EvaluationReportV2(article_id=gold.article_id,gold_state=gold.state,
        entity_matches=matches,field_results=fields,entity_failures=failures,conflict_results=conflicts,
        metrics=metrics,field_failure_counts=dict(sorted(counts.items())),
        entity_failure_counts=dict(sorted(Counter(f["classification"] for f in failures).items())))


def main(argv=None):
    parser=argparse.ArgumentParser()
    for name in ("prediction","gold","registry","output"):
        parser.add_argument("--"+name,required=True)
    args=parser.parse_args(argv)
    report=evaluate_article(ArticleExtraction.model_validate_json(Path(args.prediction).read_text(encoding="utf-8")),
        GoldStandardV2.model_validate_json(Path(args.gold).read_text(encoding="utf-8")),load_registry(args.registry))
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(report.model_dump_json(indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"article":report.article_id,"metrics":{k:report.metrics[k] for k in (
        "hard_exact", "production_coverage", "supported_value_accuracy", "conflicts")},
        "entity_failures":report.entity_failure_counts},ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
