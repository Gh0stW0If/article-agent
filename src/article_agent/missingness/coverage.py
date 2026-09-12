"""Fail-closed consumer of the existing Absence Authority v1.1 receipts.

Source of authority: field-scope-source-universe.ts / field-scope-completeness.ts.
This module does not derive a source universe, issue a certificate, retrieve text,
or interpret an empty extraction as a negative source review. A source producer
must supply both its coverage receipt and a field-specific review of every unit.
"""
from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import json
from typing import Literal


CERTIFICATE = "ABSENCE_COVERAGE_CERTIFICATE/1.1.0"
AUTHORITY_RULE = "COMPLETE_NON_TARGETED_FIELD_SCOPE_WITH_NO_POSITIVE_OR_UNRESOLVED_SOURCE"


def digest(value):
    # The authority contract has ASCII lower-camel-case object keys and integer
    # token counts. This is its stableJson/SHA256 representation, not a new hash.
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest().upper()


@dataclass(frozen=True)
class FieldScopeReview:
    entity_type: str
    entity_id: str
    field: str
    certificate: dict
    source_universe: dict
    scope_policy: dict
    # Included source unit -> field-level assessment, not extraction success.
    findings: dict[str, Literal["ABSENT", "POSITIVE", "CONFLICT", "UNRESOLVED"]]
    review_source: Literal["source_review", "deterministic_source_scan"] = "source_review"


@dataclass(frozen=True)
class CoverageContext:
    document_id: str
    document_evidence_map_hash: str
    reviews: tuple[FieldScopeReview, ...] = field(default_factory=tuple)


def _hashed(value, hash_key):
    return isinstance(value, dict) and hash_key in value and value[hash_key] == digest(
        {k: v for k, v in value.items() if k != hash_key})


def _ids(value, key):
    items = value[key]
    if not isinstance(items, list) or any(not isinstance(x, str) or not x for x in items):
        raise ValueError("Invalid source unit IDs")
    if len(items) != len(set(items)):
        raise ValueError("Duplicate source unit IDs")
    return set(items)


def coverage_proof(context, document_id, entity_type, entity_id, name):
    """Return an audit proof, never NR authority from a missing/partial receipt."""
    proof = {
        "entity_type": entity_type, "entity_id": entity_id, "field": name,
        "applicability": "APPLICABLE", "source_scopes_checked": [],
        "positive_evidence_found": None, "conflicting_or_unresolved_source": None,
        "coverage_sufficient": False, "authority_rule": AUTHORITY_RULE,
        "authority_contract": CERTIFICATE, "certificate_hash": None,
        "blockers": [], "final_status": "UNRESOLVED",
    }
    if context is None:
        proof["blockers"] = ["NO_BOUND_COVERAGE_CERTIFICATE_OR_FIELD_REVIEW"]
        return proof
    if context.document_id != document_id:
        proof["blockers"] = ["DOCUMENT_BINDING_MISMATCH"]
        return proof
    reviews = [r for r in context.reviews if
               (r.entity_type, r.entity_id, r.field) == (entity_type, entity_id, name)]
    if len(reviews) != 1:
        proof["blockers"] = ["MISSING_OR_AMBIGUOUS_FIELD_SCOPE_REVIEW"]
        return proof
    review = reviews[0]
    c, u, p = review.certificate, review.source_universe, review.scope_policy
    field_id = entity_type[0].lower() + entity_type[1:] + "." + name
    try:
        if (c["contractId"] != CERTIFICATE or c["schemaVersion"] != "1.1.0"
            or c["evaluatorVersion"] != "FIELD_SCOPE_COMPLETENESS_EVALUATOR/1.1.0"
            or u["contractId"] != "FIELD_SCOPE_SOURCE_UNIVERSE/1.0.0"
            or u["schemaVersion"] != "1.0.0"
            or not _hashed(c, "certificateHash") or not _hashed(u, "universeHash")):
            raise ValueError("INVALID_CERTIFICATE_OR_UNIVERSE_HASH")
        proof["certificate_hash"] = c["certificateHash"]
        if (c["documentId"] != document_id or u["documentId"] != document_id
            or c["documentEvidenceMapHash"] != context.document_evidence_map_hash
            or u["documentMapHash"] != context.document_evidence_map_hash
            or c["eligibleSourceUniverseHash"] != u["universeHash"]):
            raise ValueError("SOURCE_LINEAGE_MISMATCH")
        if (c["scopeId"] != p["scopeId"] or u["scopeId"] != p["scopeId"]
            or c["skillId"] != p["skillId"] or u["skillId"] != p["skillId"]
            or field_id not in p["fieldIds"]
            or field_id not in c["coveredFieldIds"]
            or set(c["coveredFieldIds"]) != set(u["fieldIds"])
            or not set(c["coveredFieldIds"]) <= set(p["fieldIds"])
            or c["scopeUnionPolicy"] != "REQUEST_FIELD_SCOPE_UNION/1.0.0"):
            raise ValueError("FIELD_OR_OWNING_SCOPE_MISMATCH")
        if (p["authorityClass"] not in {"DOCUMENT_WIDE_REQUIRED", "TABLE_REQUIRED",
                                      "FRONT_MATTER_CAN_ASSERT_ABSENCE", "CUSTOM_FIELD_SCOPE"}
            or p["targetedMissCanAuthorizeNr"] is not False or p["goldIndependent"] is not True
            or u["universeDerivationPolicy"]["targetedRetrievalReused"] is not False
            or u["universeDerivationPolicy"]["goldUsed"] is not False
            or set(c["provenance"]) != {"goldUsed", "modelResultUsed", "expectedValueUsed", "coercionApplied"}
            or any(v is not False for v in c["provenance"].values())):
            raise ValueError("INELIGIBLE_AUTHORITY_OR_PROVENANCE")
        # Do not trust a COMPLETE label: independently recompute the existing
        # source-universe differences, including table/visual and external scope.
        expected = (
            ("eligibleSourceUnitIds", "includedSourceUnitIds", "missingSourceUnitIds", "eligibleTextUnitIds"),
            ("eligibleVisualUnitIds", "includedVisualUnitIds", "missingVisualUnitIds", "eligibleVisualUnitIds"),
            ("eligibleTableUnitIds", "includedTableUnitIds", "missingTableUnitIds", "eligibleTableUnitIds"),
        )
        # Conservatively abstain on exclusions; do not add a new exclusion policy.
        if c["excludedSourceUnits"]:
            raise ValueError("EXCLUDED_SOURCE_REQUIRES_UPSTREAM_AUTHORITY_REVIEW")
        checked = set()
        for eligible, included, missing, universe_key in expected:
            e, i = _ids(c, eligible), _ids(c, included)
            if e != _ids(u, universe_key) or i != e or _ids(c, missing):
                raise ValueError("INCOMPLETE_OR_INCONSISTENT_SOURCE_UNIVERSE")
            checked.update(i)
        if (not checked or _ids(c, "eligibleExternalReferences") != _ids(u, "eligibleExternalReferences")
            or c["unavailableExternalReferences"]):
            raise ValueError("EMPTY_OR_UNAVAILABLE_SOURCE_SCOPE")
        # Available external references also need content review. This adapter
        # cannot bind their independent source maps: abstain rather than omit them.
        if c["eligibleExternalReferences"]:
            raise ValueError("EXTERNAL_SOURCE_REVIEW_NOT_BOUND")
        modalities = {"TEXT": bool(c["includedSourceUnitIds"]),
                      "TABLE": bool(c["includedTableUnitIds"]),
                      "VISUAL": bool(c["includedVisualUnitIds"])}
        if (any(not modalities[m] for m in p["requiredModalitiesAll"])
            or (p["requiredModalitiesAnyOf"] and not any(modalities[m] for m in p["requiredModalitiesAnyOf"]))
            or (p["authorityClass"] == "TABLE_REQUIRED" and not modalities["TABLE"])):
            raise ValueError("REQUIRED_SOURCE_MODALITY_MISSING")
        diff_keys = [key for group in expected for key in group[:3]] + ["excludedSourceUnits"]
        if c["coverageDiffHash"] != digest({key: c[key] for key in diff_keys}):
            raise ValueError("INVALID_COVERAGE_DIFF_HASH")
        if (c["coverageStatus"] != "COMPLETE" or c["authorityGranted"] is not True
            or c["sourceUniverseDerivationValid"] is not True or u["derivationValid"] is not True
            or c["allRequestedFieldsCovered"] is not True or c["contextTruncated"] is not False
            or c["parserGap"] is not False
            or type(c["estimatedContextTokens"]) is not int or type(c["maxContextTokens"]) is not int
            or not 0 <= c["estimatedContextTokens"] <= c["maxContextTokens"]
            or c["maxContextTokens"] <= 0):
            raise ValueError("COVERAGE_NOT_COMPLETE")
        if review.review_source not in {"source_review", "deterministic_source_scan"}:
            raise ValueError("EXTRACTION_MISS_IS_NOT_SOURCE_REVIEW")
        if set(review.findings) != checked or any(
            finding not in {"ABSENT", "POSITIVE", "CONFLICT", "UNRESOLVED"}
            for finding in review.findings.values()
        ):
            raise ValueError("FIELD_REVIEW_NOT_COMPLETE")
        proof.update(
            source_scopes_checked=sorted(checked), coverage_sufficient=True,
            document_id=document_id, document_evidence_map_hash=context.document_evidence_map_hash,
            source_universe_hash=u["universeHash"], scope_id=c["scopeId"],
            authority_class=p["authorityClass"], review_source=review.review_source,
            review_findings=dict(sorted(review.findings.items())),
            # Retain the receipt itself so a downstream auditor can revalidate
            # hashes and source scope, not merely trust a human-readable summary.
            authority_receipt={"certificate": deepcopy(c), "source_universe": deepcopy(u),
                               "scope_policy": deepcopy(p)},
            positive_evidence_found="POSITIVE" in review.findings.values(),
            conflicting_or_unresolved_source=any(
                v in {"CONFLICT", "UNRESOLVED"} for v in review.findings.values()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        proof["blockers"] = ["INVALID_OR_INSUFFICIENT_COVERAGE_RECEIPT", str(exc)]
    return proof
