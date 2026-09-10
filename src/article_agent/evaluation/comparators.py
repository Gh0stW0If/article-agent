"""Value comparators. No API, ontology, fuzzy matching or numeric parsing."""
from collections import Counter
import math
from .models import ComparatorResult
from .normalization import normalize, OPERATIONS
from .registry import COMPARATORS


def compare_values(gold_value, prediction_value, registry_field):
    config = registry_field.comparator or {}
    kind = config.get("type")
    if kind not in COMPARATORS:
        raise ValueError(f"Unknown comparator: {kind}")
    operations = registry_field.normalization
    if set(operations) - set(OPERATIONS):
        raise ValueError("Unknown normalization operation")
    a, b = gold_value, prediction_value
    if operations:
        a, b = normalize(a, operations), normalize(b, operations)
    diagnostic = None
    if kind in {"EXACT_VALUE", "SEMANTIC_CODE"}:
        matched = type(a) is type(b) and a == b
    elif kind == "NORMALIZED_STRING":
        if not isinstance(a, str) or not isinstance(b, str):
            raise ValueError("NORMALIZED_STRING requires strings")
        a, b = normalize(a), normalize(b)
        matched = a == b
    elif kind == "NORMALIZED_NUMERIC":
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (a, b)):
            raise ValueError("NORMALIZED_NUMERIC requires finite typed numbers")
        absolute = config.get("absolute_tolerance", 1e-6)
        relative = config.get("relative_tolerance", 0)
        if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in (absolute, relative)):
            raise ValueError("Invalid numeric tolerance")
        matched = abs(a-b) <= max(absolute, relative * max(abs(a), abs(b)))
    elif kind in {"SET_EQUALITY", "ORDERED_LIST", "UNORDERED_LIST"}:
        if any(not isinstance(x, list) or any(not isinstance(v, str) for v in x) for x in (a, b)):
            raise ValueError("List comparators require list[string]")
        a, b = normalize(a), normalize(b)
        if kind == "SET_EQUALITY":
            a, b = sorted(set(a)), sorted(set(b))
            matched = a == b
        elif kind == "UNORDERED_LIST":
            matched = Counter(a) == Counter(b)
            a, b = sorted(a), sorted(b)
        else:
            matched = a == b
    elif kind == "STATUS_ONLY":
        # Caller supplies statuses, never clinical values.
        from ..domain.models import FieldStatus
        matched = FieldStatus(a) == FieldStatus(b)
    else:
        # Structural grounding is computed against the graph by the engine.
        if type(a) is not bool or type(b) is not bool:
            raise ValueError("EVIDENCE_GROUNDED requires structural grounding flags")
        matched = a and b
        diagnostic = "Structural linkage only; not PDF semantic verification"
    return ComparatorResult(matched=matched, comparator=kind, normalized_gold=a,
                            normalized_prediction=b, diagnostic=diagnostic)
