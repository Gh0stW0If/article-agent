"""Conservative PR4.1 normalization of raw outcome records.

This is a source-semantics pass: it never calls an API, creates Arms, or
performs clinical/fuzzy synonym matching. Original records are retained.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .trial_topology_agent import TrialTopology


_STAT = re.compile(r"\b(mean|median|standard deviation|sd|change from baseline|change|proportion|percentage|rate|event count)\b", re.I)
_TIME = re.compile(r"\b(?:at|after)\s+\d+(?:\.\d+)?\s+(?:week|weeks|month|months|day|days)\b|\b(?:week|weeks|month|months|day|days|follow[- ]up|baseline|T\d)\s*(?:\d+(?:\.\d+)?)?\b", re.I)
_UNIT = re.compile(r"\(([^()]*\b(?:mm|ml|kg|cm|%|times/day|days?)\b[^()]*)\)", re.I)


def _text(v):
    if v is None or isinstance(v, (dict, list)):
        return None
    s = str(v).strip()
    return None if not s or s.casefold() in {"nr", "n/r", "unknown", "not reported"} else s


def _norm(v):
    return " ".join((_text(v) or "").casefold().split())


def _arm_aliases(topology):
    out = {}
    for i, arm in enumerate(topology.arms, 1):
        aid = f"{topology.arms[0].source_id if False else ''}"  # never used; IDs supplied by caller
        labels = [arm.name, arm.source_label, *arm.aliases]
        out[i] = {_norm(x) for x in labels if _norm(x)}
    return out


def _split_name(name, record):
    """Split only explicit lexical markers; ambiguous wording is untouched."""
    original = _text(name)
    if not original:
        return {}
    result = {}
    m = _STAT.search(original)
    if m and record.get("value_kind") is None and record.get("statistic_type") is None:
        result["value_kind"] = m.group(1)
    t = _TIME.search(original)
    if t and not _text(record.get("timepoint")) and not _text(record.get("outcome_observation_timepoint_raw")):
        result["timepoint"] = t.group(0).strip()
    u = _UNIT.search(original)
    if u and not _text(record.get("unit")):
        result["unit"] = u.group(1).strip()
    cleaned = original
    removable = (
        m.group(0) if m and "value_kind" in result else "",
        t.group(0) if t and "timepoint" in result else "",
        u.group(0) if u and "unit" in result else "",
    )
    for value in removable:
        if value:
            cleaned = re.sub(re.escape(value), "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -,:;()")
    if cleaned and cleaned.casefold() != original.casefold() and len(cleaned) >= 3:
        result["outcome_name"] = cleaned
    return result


def normalize_outcome_sources(article_id: str, topology, records):
    """Return normalized copies and a report; input objects are never mutated."""
    topology = TrialTopology.model_validate(topology.model_dump() if isinstance(topology, TrialTopology) else topology)
    data = deepcopy(records)
    if isinstance(data, dict):
        data = data.get("outcomes", data.get("records", []))
    if not isinstance(data, list):
        raise ValueError("records must be a list or outcomes wrapper")
    # IDs are deterministic from article/study convention; source labels remain the authority.
    arm_aliases = _arm_aliases(topology)
    arm_ids = {i: f"{article_id}-S1-A{i:02d}" for i in arm_aliases}
    warnings = []
    normalized = []
    for idx, row in enumerate(data):
        if not isinstance(row, dict):
            warnings.append({"index": idx, "type": "OTHER", "message": "non-object record"})
            continue
        out = deepcopy(row)
        out["_pr41_original"] = deepcopy(row)
        name = row.get("outcome_name", row.get("name"))
        split = _split_name(name, row)
        for field, value in split.items():
            # Derived source semantics are written to their dedicated field.
            # The original record remains under _pr41_original.
            out[field] = value
        # Avoid duplicating an already independent instrument in outcome_name.
        instrument = _text(row.get("measurement_instrument", row.get("instrument")))
        if instrument and _norm(out.get("outcome_name")) == _norm(instrument):
            out["outcome_name"] = name
        # Exact source-arm binding only.
        arms = out.get("arm", out.get("arms", [])) or []
        if isinstance(arms, dict):
            arms = [arms]
        for arm in arms:
            labels = [arm.get(k) for k in ("arm_id", "arm_label", "label") if _text(arm.get(k))]
            matches = set()
            for label in labels:
                for i, aliases in arm_aliases.items():
                    if _norm(label) in aliases:
                        matches.add(i)
            if len(matches) == 1:
                arm["source_arm_id"] = arm_ids[next(iter(matches))]
                arm["source_arm_binding_status"] = "RESOLVED"
            else:
                arm["source_arm_id"] = None
                arm["source_arm_binding_status"] = "UNRESOLVED"
                warnings.append({"index": idx, "type": "ARM_BINDING", "message": f"non-unique source arm labels: {labels}"})
        out["arm"] = arms
        # Comparator mappings are accepted only when explicitly present in source.
        comparisons = out.get("comparisons")
        if comparisons is None:
            comparisons = [out.get("comparison")] if isinstance(out.get("comparison"), dict) else []
        for comp in comparisons:
            if not isinstance(comp, dict):
                continue
            labels = comp.get("arm_labels") or comp.get("arm_ids")
            if labels and len(labels) >= 2:
                mapped = []
                for label in labels:
                    found = [arm_ids[i] for i, aliases in arm_aliases.items() if _norm(label) in aliases]
                    if len(found) != 1:
                        mapped = []
                        break
                    mapped.append(found[0])
                if len(mapped) == len(labels):
                    comp["source_arm_ids"] = mapped
                else:
                    comp["source_arm_ids"] = None
                    warnings.append({"index": idx, "type": "COMPARISON_SCOPE", "message": "comparison labels not uniquely bindable"})
            elif labels:
                warnings.append({"index": idx, "type": "COMPARISON_SCOPE", "message": "comparison labels incomplete"})
        # P1/P2/P3 mapping is only copied when explicitly supplied by source.
        explicit_p = row.get("p_comparisons") or row.get("p_value_comparisons")
        if explicit_p is not None:
            out["p_value_comparisons"] = deepcopy(explicit_p)
        elif row.get("p_value_cells"):
            out.setdefault("p_value_comparisons", None)
            warnings.append({"index": idx, "type": "COMPARISON_SCOPE", "message": "P cells have no explicit participant mapping"})
        normalized.append(out)
    return normalized, {"article_id": article_id, "record_count": len(normalized), "warnings": warnings}
