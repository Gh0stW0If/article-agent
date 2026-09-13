"""Generic source-only tests; no Gold, study-specific rules or online calls."""
from copy import deepcopy
from dataclasses import replace
import inspect
from pathlib import Path

import pytest

from article_agent.domain.models import (
    Article, ArticleExtraction, Arm, ArmResult, CanonicalField, Comparison,
    ComparisonResult, ConflictCandidate, Evidence, EvidenceTarget, Outcome, Study,
)
from article_agent.missingness import CoverageContext, FieldScopeReview, resolve_missingness
from article_agent.missingness.coverage import coverage_proof, digest
from article_agent.missingness.resolver import MissingnessResolver, applicability


def field(value, eid):
    return CanonicalField(status="PRESENT", value=value, evidence_ids=[eid])


def graph(kind="mean", article_id="synthetic-rct"):
    a = ArticleExtraction(
        article=Article(article_id=article_id),
        studies=[Study(study_id="s", article_id=article_id)],
        arms=[Arm(arm_id="a", study_id="s")],
        outcomes=[Outcome(outcome_id="o", study_id="s")],
        comparisons=[Comparison(comparison_id="c", study_id="s", arm_ids=["a"])],
        comparison_results=[ComparisonResult(comparison_result_id="cr", comparison_id="c", outcome_id="o")],
        arm_results=[ArmResult(arm_result_id="ar", arm_id="a", outcome_id="o",
            value_kind=field(kind, "K"), value=field(10.0, "V"),
            standard_deviation=field(2.0, "SD"))],
        evidence=[Evidence(evidence_id=eid, quote=quote, source_type="table", source_id="source",
            targets=[EvidenceTarget(entity_type="ArmResult", entity_id="ar", field_id=name)])
            for name, eid, quote in (("value_kind", "K", kind),
                ("value", "V", "10 (2)"), ("standard_deviation", "SD", "10 (2)"))],
    )
    return ArticleExtraction.model_validate_json(a.model_dump_json())


def complete_context():
    """Synthetic *source* receipt using existing TS v1.1 keys, not Gold."""
    fid = "armResult.n"
    policy = {"scopeId": "SAMPLE_FLOW_SCOPE", "skillId": "sample_flow",
        "fieldIds": [fid], "authorityClass": "TABLE_REQUIRED",
        "targetedMissCanAuthorizeNr": False, "goldIndependent": True,
        "requiredModalitiesAll": ["TABLE"], "requiredModalitiesAnyOf": [],
        "requiredSectionGroups": [["RESULTS"]],
        "includeFrontMatterPage": False, "unavailableExternalSourceBlocks": True,
        "contextBudgetPolicy": "FAIL_CLOSED_UNLESS_COMPLETE_AGGREGATION_VALIDATED"}
    universe = {
        "schemaVersion": "1.0.0", "contractId": "FIELD_SCOPE_SOURCE_UNIVERSE/1.0.0",
        "documentId": "synthetic-rct", "documentMapHash": "A" * 64,
        "fieldIds": [fid], "skillId": "sample_flow", "scopeId": "SAMPLE_FLOW_SCOPE",
        "eligibleTextUnitIds": ["text1"], "eligibleVisualUnitIds": [],
        "eligibleTableUnitIds": ["table1"], "eligibleExternalReferences": [],
        "universeDerivationPolicy": {
            "policyId": "HIGH_RECALL_FIELD_SCOPE_UNIVERSE_DERIVATION/1.0.0",
            "structuralSectionClasses": ["RESULTS"], "lexicalNeighborhoodEnabled": False,
            "lexicalFamilies": [], "adjacencyRadius": 1,
            "targetedRetrievalReused": False, "goldUsed": False},
        "derivationValid": True, "diagnostics": [],
    }
    universe["universeHash"] = digest(universe)
    diff = {"eligibleSourceUnitIds": ["text1"], "includedSourceUnitIds": ["text1"],
        "missingSourceUnitIds": [], "excludedSourceUnits": [],
        "eligibleVisualUnitIds": [], "includedVisualUnitIds": [], "missingVisualUnitIds": [],
        "eligibleTableUnitIds": ["table1"], "includedTableUnitIds": ["table1"], "missingTableUnitIds": []}
    certificate = {
        "schemaVersion": "1.1.0", "contractId": "ABSENCE_COVERAGE_CERTIFICATE/1.1.0",
        "evaluatorVersion": "FIELD_SCOPE_COMPLETENESS_EVALUATOR/1.1.0",
        "documentId": "synthetic-rct", "documentEvidenceMapHash": "A" * 64,
        "skillId": "sample_flow", "scopeId": "SAMPLE_FLOW_SCOPE", "coveredFieldIds": [fid],
        "scopeUnionPolicy": "REQUEST_FIELD_SCOPE_UNION/1.0.0",
        "eligibleSourceUniverseHash": universe["universeHash"], **diff,
        "eligibleExternalReferences": [], "unavailableExternalReferences": [],
        "coverageStatus": "COMPLETE", "authorityGranted": True,
        "sourceUniverseDerivationValid": True, "allRequestedFieldsCovered": True,
        "contextTruncated": False, "parserGap": False,
        "estimatedContextTokens": 20, "maxContextTokens": 1000,
        "coverageDiffHash": digest(diff), "diagnostics": [],
        "provenance": {"goldUsed": False, "modelResultUsed": False,
                       "expectedValueUsed": False, "coercionApplied": False},
    }
    certificate["certificateHash"] = digest(certificate)
    review = FieldScopeReview("ArmResult", "ar", "n", certificate, universe, policy,
                             {"text1": "ABSENT", "table1": "ABSENT"})
    return CoverageContext("synthetic-rct", "A" * 64, (review,))


def decision(result, name="n"):
    return next(d for d in result.decisions if d["entity_id"] == "ar" and d["field"] == name)


def test_mean_event_slots_are_na_sample_n_stays_unresolved():
    result = resolve_missingness(graph())
    r = result.prediction.arm_results[0]
    assert r.event_count.status == r.denominator.status == "NOT_APPLICABLE"
    assert r.n.status == "UNRESOLVED"
    assert decision(result, "event_count")["reason_code"] == "NOT_APPLICABLE_BY_RESULT_TYPE"
    assert r.event_count.evidence_ids
    ArticleExtraction.model_validate_json(result.prediction.model_dump_json())


def test_applicable_complete_review_absent_is_nr_with_auditable_proof():
    result = resolve_missingness(graph(), complete_context())
    assert result.prediction.arm_results[0].n.status == "NOT_REPORTED"
    d = decision(result)
    proof = next(p for p in result.coverage_proofs if p["proof_id"] == d["coverage_proof_id"])
    assert proof["coverage_sufficient"] and proof["positive_evidence_found"] is False
    assert proof["source_scopes_checked"] == ["table1", "text1"]
    assert proof["certificate_hash"] and proof["final_status"] == "NOT_REPORTED"
    assert result.prediction.arm_results[0].n.evidence_ids == []  # proof != positive evidence


@pytest.mark.parametrize("kind", ["count", "proportion", "percentage", "rate", "other", "median"])
def test_applicability_depends_on_result_type(kind):
    result = resolve_missingness(graph(kind))
    assert result.prediction.arm_results[0].event_count.status == "UNRESOLVED"
    assert result.prediction.arm_results[0].denominator.status == "UNRESOLVED"


@pytest.mark.parametrize("name", ["event_count", "denominator", "n"])
def test_present_never_downgraded_even_if_coverage_says_absent(name):
    raw = graph()
    setattr(raw.arm_results[0], name, field(7, "NEW"))
    raw.evidence.append(Evidence(evidence_id="NEW", quote="n=7", source_type="table", source_id="source",
        targets=[EvidenceTarget(entity_type="ArmResult", entity_id="ar", field_id=name)]))
    original = raw.model_dump_json()
    result = resolve_missingness(raw, complete_context())
    assert getattr(result.prediction.arm_results[0], name) == getattr(raw.arm_results[0], name)
    assert decision(result, name)["reason_code"] == "POSITIVE_EVIDENCE_KEEP_PRESENT"
    assert raw.model_dump_json() == original


@pytest.mark.parametrize("finding", ["POSITIVE", "CONFLICT", "UNRESOLVED"])
def test_positive_or_conflicting_or_unresolved_source_blocks_nr(finding):
    context = complete_context()
    context.reviews[0].findings["table1"] = finding
    result = resolve_missingness(graph(), context)
    assert result.prediction.arm_results[0].n.status == "UNRESOLVED"
    assert decision(result)["reason_code"] in {
        "CONFLICT_KEEP_UNRESOLVED", "POSITIVE_SOURCE_REQUIRES_EXTRACTION"}


def test_existing_conflict_is_preserved_not_erased_by_unresolved_conclusion():
    raw = graph()
    raw.arm_results[0].n = CanonicalField(status="SOURCE_CONFLICT",
        conflict_candidates=[ConflictCandidate(value=38, evidence_ids=["C1"]),
                             ConflictCandidate(value=34, evidence_ids=["C2"])])
    for eid, quote in (("C1", "n=38"), ("C2", "n=34")):
        raw.evidence.append(Evidence(evidence_id=eid, quote=quote, source_type="table", source_id="s",
            targets=[EvidenceTarget(entity_type="ArmResult", entity_id="ar", field_id="n")]))
    result = resolve_missingness(raw, complete_context())
    assert result.prediction.arm_results[0].n == raw.arm_results[0].n
    assert decision(result)["resolution_status"] == "UNRESOLVED"
    assert decision(result)["after_status"] == "SOURCE_CONFLICT"
    assert decision(result)["reason_code"] == "CONFLICT_KEEP_UNRESOLVED"


def test_uninterpreted_raw_or_mixed_event_source_blocks_na_and_nr():
    for name in ("event_count", "denominator", "n"):
        raw = graph()
        getattr(raw.arm_results[0], name).raw_value = "sample or event count 7?"
        result = resolve_missingness(raw, complete_context())
        assert getattr(result.prediction.arm_results[0], name).status == "UNRESOLVED"
        assert decision(result, name)["reason_code"] == "SOURCE_SIGNAL_KEEP_UNRESOLVED"
    raw = graph()
    raw.arm_results[0].denominator.raw_value = "7?"
    assert resolve_missingness(raw).prediction.arm_results[0].event_count.status == "UNRESOLVED"


def test_mean_without_reciprocal_source_support_does_not_authorize_na():
    raw = graph()
    raw.arm_results[0].value_kind.evidence_ids = []
    raw.evidence = [e for e in raw.evidence if e.evidence_id != "K"]
    assert resolve_missingness(raw).prediction.arm_results[0].event_count.status == "UNRESOLVED"
    raw = graph()
    raw.evidence[0].targets = []
    with pytest.raises(ValueError, match="reciprocal"):
        resolve_missingness(raw)


@pytest.mark.parametrize("key,value", [
    ("coverageStatus", "INCOMPLETE"), ("authorityGranted", False),
    ("parserGap", True), ("contextTruncated", True),
    ("sourceUniverseDerivationValid", False), ("allRequestedFieldsCovered", False),
    ("includedSourceUnitIds", []), ("includedTableUnitIds", []),
    ("missingSourceUnitIds", ["text1"]), ("unavailableExternalReferences", ["supplement"]),
    ("documentId", "different-document"), ("documentEvidenceMapHash", "B" * 64),
    ("coveredFieldIds", ["armResult.denominator"]), ("skillId", "different-skill"),
    ("coverageDiffHash", "B" * 64), ("maxContextTokens", 5),
    ("provenance", {"goldUsed": True, "modelResultUsed": False,
                    "expectedValueUsed": False, "coercionApplied": False}),
])
def test_incomplete_or_misbound_receipt_fails_closed_even_with_valid_self_hash(key, value):
    context = complete_context()
    c = context.reviews[0].certificate
    c[key] = value
    c["certificateHash"] = digest({k: v for k, v in c.items() if k != "certificateHash"})
    result = resolve_missingness(graph(), context)
    assert result.prediction.arm_results[0].n.status == "UNRESOLVED"
    assert decision(result)["reason_code"] == "INSUFFICIENT_COVERAGE_KEEP_UNRESOLVED"


def test_no_receipt_targeted_or_incomplete_field_review_never_authorizes_nr():
    assert resolve_missingness(graph()).prediction.arm_results[0].n.status == "UNRESOLVED"
    contexts = [complete_context() for _ in range(6)]
    contexts[0].reviews[0].scope_policy["authorityClass"] = "TARGETED_CONTEXT_INSUFFICIENT"
    contexts[1].reviews[0].findings.pop("table1")
    contexts[2].reviews[0].certificate["certificateHash"] = "F" * 64
    contexts[3].reviews[0].findings["another-unit"] = "ABSENT"
    contexts[4] = replace(contexts[4], reviews=(replace(contexts[4].reviews[0],
        entity_id="wrong-entity"),))
    contexts[5] = replace(contexts[5], reviews=contexts[5].reviews * 2)
    for context in contexts:
        assert resolve_missingness(graph(), context).prediction.arm_results[0].n.status == "UNRESOLVED"


def test_production_gold_leakage_and_no_study_specific_hardcoding():
    assert set(inspect.signature(resolve_missingness).parameters) == {"prediction", "coverage"}
    assert set(inspect.signature(MissingnessResolver.resolve).parameters) == {"self", "prediction", "coverage"}
    module_dir = Path(inspect.getfile(MissingnessResolver)).parent
    for path in module_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "2015-" not in text
        assert "from ..evaluation" not in text and "import requests" not in text
    raw = graph()
    before = resolve_missingness(raw).decisions
    raw.article.legacy_fields["gold_status"] = {"denominator": "PRESENT", "n": "NOT_REPORTED"}
    assert resolve_missingness(raw).decisions == before


def test_resolver_cannot_access_gold_disk_or_network_and_replays_idempotently(monkeypatch):
    raw, context = graph(), complete_context()
    expected = resolve_missingness(raw, context)
    def forbidden(*args, **kwargs):
        raise AssertionError("Production resolver must not read files or call API")
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    actual = resolve_missingness(raw, context)
    assert actual == expected
    assert resolve_missingness(actual.prediction, context).prediction == actual.prediction
    with pytest.raises(TypeError):
        resolve_missingness(raw, gold_status="NOT_REPORTED")
    for article_id in ("trial-Z", "any-unseen-document", "study-42"):
        a = graph(article_id=article_id)
        r = resolve_missingness(a)
        assert r.prediction.arm_results[0].denominator.status == "NOT_APPLICABLE"


def test_applicability_and_context_are_not_mutated():
    raw, context = graph(), complete_context()
    original, copied = raw.model_dump_json(), deepcopy(context)
    resolve_missingness(raw, context)
    assert raw.model_dump_json() == original and context == copied
    assert applicability(raw, "ArmResult", "ar", raw.arm_results[0], "n")["status"] == "APPLICABLE"
    bad = replace(context, document_id="wrong")
    assert not coverage_proof(bad, "synthetic-rct", "ArmResult", "ar", "n")["coverage_sufficient"]
