"""Deterministic applicability -> coverage -> source-check status projection."""
from copy import deepcopy
from dataclasses import dataclass, field

from ..domain.models import ArticleExtraction, CanonicalField, Evidence, EvidenceTarget
from .coverage import CoverageContext, coverage_proof, digest

# Source-side field families, not Gold target IDs or an evaluator-selected list.
# Other fields, identities, source values and existing statuses are out of scope.
FIELD_FAMILIES = {
    "Arm": ("arms", "arm_id", ("received_n", "analyzed_n", "dropout_n")),
    "Outcome": ("outcomes", "outcome_id", ("role",)),
    "ArmResult": ("arm_results", "arm_result_id", ("event_count", "denominator", "n")),
    "ComparisonResult": ("comparison_results", "comparison_result_id", ("estimate",)),
}


@dataclass
class MissingnessProjection:
    prediction: ArticleExtraction
    decisions: list[dict] = field(default_factory=list)
    coverage_proofs: list[dict] = field(default_factory=list)


def _source_signal(value):
    """Even unparsed raw content blocks absence; NR is not proof of absence."""
    raw = (value.raw_value or "").strip().casefold()
    return (value.value is not None or bool(value.evidence_ids) or bool(value.conflict_candidates)
            or raw not in {"", "nr", "n/r", "not reported", "unresolved"})


def _grounded(graph, entity_type, entity_id, name, value):
    expected = EvidenceTarget(entity_type=entity_type, entity_id=entity_id, field_id=name)
    evidence = {e.evidence_id: e for e in graph.evidence}
    return value.status == "PRESENT" and bool(value.evidence_ids) and all(
        eid in evidence and expected in evidence[eid].targets for eid in value.evidence_ids)


def applicability(graph, kind, entity_id, entity, name):
    """NA only for event slots of a source-grounded mean/SD representation.

    `n` is the sample count for a mean; `denominator` is the event denominator,
    not a substitute for `n`. Count/rate/proportion/unknown representations do
    not authorize this rule. Mixed event and mean evidence causes abstention.
    """
    result = {"status": "APPLICABLE", "rule": "FIELD_SEMANTICS_APPLICABLE",
              "evidence_ids": [], "contract": "ARTICLE_EXTRACTION/2.0"}
    if kind != "ArmResult" or name not in {"event_count", "denominator"}:
        return result
    related = (entity.event_count, entity.denominator)
    if any(_source_signal(f) for f in related):
        return {**result, "status": "UNKNOWN", "rule": "MIXED_OR_UNRESOLVED_EVENT_SOURCE"}
    if entity.value_kind.status != "PRESENT":
        return {**result, "status": "UNKNOWN", "rule": "RESULT_TYPE_UNRESOLVED"}
    if entity.value_kind.value in {"count", "event_count", "proportion", "percentage", "rate"}:
        return result
    if entity.value_kind.value == "mean" and all(
        _grounded(graph, kind, entity_id, f, getattr(entity, f))
        for f in ("value_kind", "value", "standard_deviation")
    ):
        return {**result, "status": "NOT_APPLICABLE",
            "rule": "MEAN_SD_RESULT_HAS_SAMPLE_N_NOT_EVENT_DENOMINATOR",
            "evidence_ids": sorted(set(
                entity.value_kind.evidence_ids + entity.value.evidence_ids
                + entity.standard_deviation.evidence_ids)),
            "statistic_type": "mean", "sample_size_field": "n"}
    return {**result, "status": "UNKNOWN", "rule": "NO_SUPPORTED_RESULT_TYPE_APPLICABILITY"}


def _resolve_field(graph, kind, entity_id, entity, name, context):
    value = getattr(entity, name)
    decision = {
        "entity_type": kind, "entity_id": entity_id, "field": name,
        "before_status": value.status.value, "after_status": value.status.value,
        "resolution_status": value.status.value, "changed": False,
        "decision_type": "KEEP", "rule": None, "reason_code": None,
        "applicability_evidence": None, "coverage_proof_id": None,
    }
    # Preserve factual fields verbatim. Existing SOURCE_CONFLICT is retained;
    # UNRESOLVED is the resolver's conclusion, not deletion of its candidates.
    if value.status == "PRESENT":
        decision.update(reason_code="POSITIVE_EVIDENCE_KEEP_PRESENT", rule="NEVER_DOWNGRADE_PRESENT")
        return decision, None
    if value.status == "SOURCE_CONFLICT":
        decision.update(reason_code="CONFLICT_KEEP_UNRESOLVED", rule="PRESERVE_SOURCE_CONFLICT",
                        resolution_status="UNRESOLVED")
        return decision, None
    if value.status != "UNRESOLVED":
        decision.update(reason_code="EXISTING_STATUS_PRESERVED", rule="UNRESOLVED_ONLY")
        return decision, None
    if _source_signal(value):
        decision.update(reason_code="SOURCE_SIGNAL_KEEP_UNRESOLVED",
                        rule="UNINTERPRETED_SOURCE_IS_NOT_ABSENCE")
        return decision, None
    app = applicability(graph, kind, entity_id, entity, name)
    decision["applicability_evidence"] = app
    decision["rule"] = app["rule"]
    if app["status"] == "NOT_APPLICABLE":
        decision.update(after_status="NOT_APPLICABLE", resolution_status="NOT_APPLICABLE",
            changed=True, decision_type="APPLICABILITY", reason_code="NOT_APPLICABLE_BY_RESULT_TYPE")
        return decision, None
    if app["status"] == "UNKNOWN":
        decision.update(reason_code="APPLICABILITY_UNRESOLVED", resolution_status="UNRESOLVED")
        return decision, None
    proof = coverage_proof(context, graph.article.article_id, kind, entity_id, name)
    if proof["positive_evidence_found"] or proof["conflicting_or_unresolved_source"]:
        reason = ("CONFLICT_KEEP_UNRESOLVED" if proof["conflicting_or_unresolved_source"]
                  else "POSITIVE_SOURCE_REQUIRES_EXTRACTION")
    elif not proof["coverage_sufficient"]:
        reason = "INSUFFICIENT_COVERAGE_KEEP_UNRESOLVED"
    else:
        reason = "NOT_REPORTED_WITH_SUFFICIENT_COVERAGE"
        proof["final_status"] = "NOT_REPORTED"
        decision.update(after_status="NOT_REPORTED", resolution_status="NOT_REPORTED",
                        changed=True, decision_type="COVERAGE")
    proof["proof_id"] = "MP-" + digest(proof)
    decision.update(reason_code=reason, coverage_proof_id=proof["proof_id"],
                    rule=proof["authority_rule"])
    return decision, proof


class MissingnessResolver:
    def resolve(self, prediction: ArticleExtraction,
                coverage: CoverageContext | None = None) -> MissingnessProjection:
        """No Gold, evaluator mappings, target counts, I/O, or API parameters."""
        original = prediction.model_dump_json()
        # Revalidate model_copy/model_construct input, including reciprocal links.
        source = ArticleExtraction.model_validate_json(original)
        result = MissingnessProjection(source.model_copy(deep=True))
        for kind, (collection, id_field, names) in FIELD_FAMILIES.items():
            for old, projected in zip(getattr(source, collection),
                                      getattr(result.prediction, collection), strict=True):
                entity_id = getattr(old, id_field)
                for name in names:
                    decision, proof = _resolve_field(source, kind, entity_id, old, name, coverage)
                    result.decisions.append(decision)
                    if proof is not None:
                        result.coverage_proofs.append(proof)
                    if not decision["changed"]:
                        continue
                    prior = getattr(old, name)
                    trace = projected.legacy_fields.setdefault("missingness", {"raw_fields": {}, "decisions": []})
                    trace["raw_fields"][name] = prior.model_dump(mode="json")
                    trace["decisions"].append(deepcopy(decision))
                    ids = list(prior.evidence_ids)
                    if decision["after_status"] == "NOT_APPLICABLE":
                        eid = "MA-" + digest(decision)
                        support = decision["applicability_evidence"]
                        evidence = Evidence(
                            evidence_id=eid,
                            targets=[EvidenceTarget(entity_type=kind, entity_id=entity_id, field_id=name)],
                            quote="Source-backed mean/SD representation; sample n is distinct from event denominator.",
                            source_type="other", source_id="canonical-result-semantics",
                            support_type="derived", derivation=decision["rule"],
                            legacy_fields={"source_evidence_ids": support["evidence_ids"],
                                           "applicability_evidence": deepcopy(support)})
                        result.prediction.evidence.append(evidence)
                        ids.append(eid)
                    # NR authority is provenance, never fabricated positive evidence.
                    setattr(projected, name, CanonicalField(
                        status=decision["after_status"], value=None,
                        raw_value=prior.raw_value, evidence_ids=ids))
        result.prediction = ArticleExtraction.model_validate_json(result.prediction.model_dump_json())
        if prediction.model_dump_json() != original:
            raise AssertionError("Raw prediction mutated")
        return result


def resolve_missingness(prediction: ArticleExtraction,
                        coverage: CoverageContext | None = None) -> MissingnessProjection:
    return MissingnessResolver().resolve(prediction, coverage)
