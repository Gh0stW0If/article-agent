"""Canonical, evaluator-facing domain model for Article Agent.

The legacy extraction models remain the runtime output contract.  Importing
this package has no side effects on extraction; callers opt into conversion by
calling :func:`legacy_bundle_to_canonical`.
"""

from .legacy_adapter import legacy_bundle_to_canonical
from .models import (
    Arm,
    ArmResult,
    Article,
    ArticleExtraction,
    CanonicalField,
    ConflictCandidate,
    FieldStatus,
    EvidenceTarget,
    merge_field_observation,
    Comparison,
    ComparisonResult,
    Evidence,
    Intervention,
    Outcome,
    Study,
)

__all__ = [
    "ArticleExtraction",
    "CanonicalField",
    "ConflictCandidate",
    "FieldStatus",
    "EvidenceTarget",
    "merge_field_observation",
    "Article",
    "Study",
    "Arm",
    "Intervention",
    "Outcome",
    "ArmResult",
    "Comparison",
    "ComparisonResult",
    "Evidence",
    "legacy_bundle_to_canonical",
]
