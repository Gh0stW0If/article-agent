"""Deterministic linking over identity-only types. No graph or numerical result input."""
import ast
from itertools import product
import re

from .models import CandidateDecision, Compatibility, ResultIdentityProjection, ResultLinkAudit, ResultLinking
from .normalizers import compare_qualifier, compare_timepoints


def _compat(status, reason):
    return Compatibility(status=status, reason=reason)


def link_outcomes(predicted, reference, prior_matches, study_mapping):
    """Group production aliases first; compare canonical concepts only afterwards."""
    previous = [m for m in prior_matches if m.entity_type == "Outcome"]
    locked = [m.model_dump(mode="json") for m in previous if m.match_status == "MATCHED"]
    mappings = {m["prediction_entity_id"]: m["gold_entity_id"] for m in locked}
    locked_g = set(mappings.values())
    projection = {p.outcome_id: p for p in predicted.projections}
    gold = {p.outcome_id: p for p in reference.projections}
    group_mapping, blocked_groups = {}, set()
    for group, members in predicted.groups.items():
        targets = {mappings[oid] for oid in members if oid in mappings}
        if len(targets) == 1:
            group_mapping[group] = reference.canonical_ids[next(iter(targets))]
        elif len(targets) > 1:
            # Do not overturn established distinct identities by grouping aliases.
            blocked_groups.add(group)
    edges = {gid: [] for gid in gold if gid not in locked_g}
    for gid in edges:
        g = gold[gid]
        for group in predicted.groups:
            if group in group_mapping or group in blocked_groups:
                continue
            p = projection[group]
            if p.identity_blockers or g.identity_blockers:
                continue
            if study_mapping.get(p.study_id) != g.study_id:
                continue
            if not p.canonical_concept or p.canonical_concept != g.canonical_concept:
                continue
            if any(x and y and x != y for x, y in ((g.instrument, p.instrument), (g.unit, p.unit), (g.definition, p.definition))):
                continue
            edges[gid].append(group)
    reverse = {group: [gid for gid in edges if group in edges[gid]] for group in predicted.groups}
    matches = locked[:]
    used = set(group_mapping) | blocked_groups
    for gid, candidates in edges.items():
        if len(candidates) == 1 and len(reverse[candidates[0]]) == 1:
            group = candidates[0]
            group_mapping[group] = reference.canonical_ids[gid]
            used.add(group)
            matches.append({"entity_type": "Outcome", "gold_entity_id": gid,
                "prediction_entity_id": group, "match_status": "MATCHED",
                "match_method": "CANONICAL_OUTCOME_IDENTITY",
                "identity_key": {"prediction_aliases": predicted.groups[group]}})
        else:
            status = "SPLIT" if len(candidates) > 1 else "MERGED" if candidates else "MISSING"
            matches.append({"entity_type": "Outcome", "gold_entity_id": gid, "match_status": status,
                "diagnostic": f"Canonical prediction candidates={candidates}; no forced selection"})
    for group in predicted.groups:
        if group not in used:
            matches.append({"entity_type": "Outcome", "prediction_entity_id": group,
                "match_status": "SPLIT" if reverse[group] else "EXTRA",
                "diagnostic": f"Canonical Gold candidates={reverse[group]}",
                "identity_key": {"prediction_aliases": predicted.groups[group]}})
    return matches, group_mapping


def candidate_compatibility(g, p, parent_mapping, outcome_mapping):
    if not isinstance(g, ResultIdentityProjection) or not isinstance(p, ResultIdentityProjection):
        raise TypeError("Result linker accepts identity-only projections")
    dimensions = {"entity_type": _compat(
        "EXACT" if (g.entity_type, g.parent_type) == (p.entity_type, p.parent_type) else "CONTRADICTORY",
        "ENTITY_TYPE_EXACT" if (g.entity_type, g.parent_type) == (p.entity_type, p.parent_type) else "ENTITY_TYPE_CONTRADICTION")}
    mapped_parent = parent_mapping.get((p.parent_type, p.parent_id))
    dimensions["parent"] = _compat(
        "UNKNOWN" if mapped_parent is None else "EXACT" if mapped_parent == g.parent_id else "CONTRADICTORY",
        "MISSING_REQUIRED_PARENT" if mapped_parent is None else "PARENT_EXACT" if mapped_parent == g.parent_id else "PARENT_CONTRADICTION")
    mapped_outcome = outcome_mapping.get(p.canonical_outcome_id)
    dimensions["outcome"] = _compat(
        "UNKNOWN" if mapped_outcome is None else "EXACT" if mapped_outcome == g.canonical_outcome_id else "CONTRADICTORY",
        "MISSING_OUTCOME" if mapped_outcome is None else
        "OUTCOME_CANONICAL_EQUIVALENT" if mapped_outcome == g.canonical_outcome_id else "OUTCOME_CONTRADICTION")
    dimensions["timepoint"] = compare_timepoints(g.canonical_timepoint, p.canonical_timepoint)
    dimensions["analysis_set"] = compare_qualifier(g.canonical_analysis_set, p.canonical_analysis_set, "ANALYSIS_SET")
    dimensions["statistic_kind"] = compare_qualifier(g.canonical_statistic_kind, p.canonical_statistic_kind, "STATISTIC_KIND")
    dimensions["derived"] = _compat("EXACT" if g.derived == p.derived else "CONTRADICTORY",
                                   "DERIVED_EXACT" if g.derived == p.derived else "DERIVED_CONTRADICTION")
    viable = (mapped_parent == g.parent_id and mapped_outcome == g.canonical_outcome_id
              and all(v.status != "CONTRADICTORY" for v in dimensions.values()))
    missing = {"NOT_REPORTED", "NOT_APPLICABLE", "UNRESOLVED", "INSUFFICIENT_CONTEXT"}
    time_safe = dimensions["timepoint"].status in {"EXACT", "COMPATIBLE"} or all(
        x.raw_timepoint.status in missing and x.canonical_timepoint.kind == "unknown"
        and x.raw_timepoint_value.status != "PRESENT" for x in (g, p))
    statistic_safe = dimensions["statistic_kind"].status != "UNKNOWN" or any(
        x.raw_statistic_kind.status in missing for x in (g, p))
    # An explicit "other" is not silently promoted to a reported mean.
    if any(x.raw_statistic_kind.status == "PRESENT" and x.canonical_statistic_kind == "other" for x in (g, p)):
        statistic_safe = False
    safe = (viable and mapped_parent == g.parent_id and mapped_outcome == g.canonical_outcome_id
            and time_safe and statistic_safe and not g.identity_blockers and not p.identity_blockers)
    return CandidateDecision(entity_type=g.entity_type, gold_id=g.entity_id, prediction_id=p.entity_id,
                             dimensions=dimensions, viable=viable, safe=safe)


def _prior(prior, kind, entity_id, side):
    name, other = ("gold_entity_id", "prediction_entity_id") if side == "Gold" else ("prediction_entity_id", "gold_entity_id")
    row = next((m for m in prior if m.entity_type == kind and getattr(m, name) == entity_id), None)
    if not row:
        return "MISSING" if side == "Gold" else "EXTRA", []
    if getattr(row, other):
        return row.match_status, [getattr(row, other)]
    label = "prediction" if side == "Gold" else "Gold"
    found = re.search(label + r" candidates=(\[[^\]]*\])", row.diagnostic or "")
    return row.match_status, sorted(ast.literal_eval(found[1])) if found else []


def _remaining_reasons(candidates, viable, side, own, parent_mapping, outcome_mapping):
    if viable:
        if len(viable) > 1:
            return ["MULTIPLE_SAFE_CANDIDATES"]
        row = viable[0]
        if row.safe:
            return ["MULTIPLE_SAFE_CANDIDATES"]
        if row.dimensions["parent"].status == "UNKNOWN":
            return ["MISSING_PARENT"]
        if row.dimensions["outcome"].status == "UNKNOWN":
            return ["OUTCOME_AMBIGUOUS"]
        if own.identity_blockers:
            return list(own.identity_blockers)
        if row.dimensions["timepoint"].status == "UNKNOWN":
            return ["TIMEPOINT_AMBIGUOUS"]
        if row.dimensions["statistic_kind"].status == "UNKNOWN":
            return ["STATISTIC_KIND_AMBIGUOUS"]
        return ["ANALYSIS_SET_AMBIGUOUS"]
    rows = candidates
    if side == "Prediction" and (own.parent_type, own.parent_id) not in parent_mapping:
        return ["MISSING_PARENT"]
    if side == "Prediction" and own.canonical_outcome_id not in outcome_mapping:
        return ["OUTCOME_AMBIGUOUS"]
    for dimension, reason in (
        ("parent", "MISSING_RESULT_IN_PREDICTION" if side == "Gold" else "NO_CANDIDATE"),
        ("outcome", "MISSING_RESULT_IN_PREDICTION" if side == "Gold" else "OUTCOME_CONTRADICTION"),
        ("timepoint", "TIMEPOINT_CONTRADICTION"),
        ("analysis_set", "ANALYSIS_SET_CONTRADICTION"),
        ("statistic_kind", "STATISTIC_KIND_CONTRADICTION"),
        ("derived", "DERIVED_CONTRADICTION"),
    ):
        # Unknown parent/outcome links are not candidates for another mapped concept.
        # Otherwise an unrelated unresolved Outcome can hide a genuinely missing row
        # and incorrectly blame that row's statistic/timepoint.
        narrowed = [c for c in rows if (
            c.dimensions[dimension].status == "EXACT" if dimension in {"parent", "outcome"}
            else c.dimensions[dimension].status != "CONTRADICTORY")]
        if not narrowed:
            return [reason]
        rows = narrowed
    return ["IDENTITY_QUALIFIER_AMBIGUOUS"]


def link_results(predicted, reference, parent_mapping, outcome_mapping, prior_matches=()):
    """Only accepts projections: observed clinical values cannot enter this API."""
    matches, audit, decisions = [], [], []
    for kind in ("ArmResult", "ComparisonResult"):
        gs = {g.entity_id: g for g in reference if g.entity_type == kind}
        ps = {p.entity_id: p for p in predicted if p.entity_type == kind}
        rows = [candidate_compatibility(g, p, parent_mapping, outcome_mapping)
                for g, p in product(gs.values(), ps.values())]
        decisions.extend(rows)
        # Viable but unsafe competitors still block unique safe candidates.
        edges = {gid: [c for c in rows if c.gold_id == gid and c.viable] for gid in gs}
        reverse = {pid: [c for c in rows if c.prediction_id == pid and c.viable] for pid in ps}
        selected = {gid: es[0].prediction_id for gid, es in edges.items()
                    if len(es) == 1 and es[0].safe and len(reverse[es[0].prediction_id]) == 1}
        inverse = {p: g for g, p in selected.items()}
        for side, objects in (("Gold", gs), ("Prediction", ps)):
            for eid, projection in objects.items():
                cs = [c for c in rows if (c.gold_id if side == "Gold" else c.prediction_id) == eid]
                viable = [c for c in cs if c.viable]
                other = selected.get(eid) if side == "Gold" else inverse.get(eid)
                old_status, old_candidates = _prior(prior_matches, kind, eid, side)
                if other:
                    pair = {"gold_id": eid if side == "Gold" else other, "prediction_id": other if side == "Gold" else eid}
                    chosen = next(c for c in cs if c.gold_id == pair["gold_id"] and c.prediction_id == pair["prediction_id"])
                    reasons = [v.reason for v in chosen.dimensions.values()]
                    if projection.normalization_events:
                        reasons += [x.rule for x in projection.normalization_events]
                    reasons.append("UNIQUE_SAFE_RESULT_LINK")
                    status = "MATCHED"
                    if side == "Gold":
                        matches.append({"entity_type": kind, "gold_entity_id": eid, "prediction_entity_id": other,
                            "match_status": status, "match_method": "DETERMINISTIC_CANONICAL_RESULT",
                            "identity_key": {"reasons": reasons}})
                else:
                    pair = None
                    status = "AMBIGUOUS" if viable else "MISSING" if side == "Gold" else "EXTRA"
                    reasons = _remaining_reasons(cs, viable, side, projection, parent_mapping, outcome_mapping)
                    if side == "Gold" and projection.canonical_outcome_id not in outcome_mapping.values():
                        prior_outcome = next((m for m in prior_matches if m.entity_type == "Outcome"
                                              and m.gold_entity_id == projection.raw_outcome_id), None)
                        reasons = ["OUTCOME_AMBIGUOUS" if prior_outcome and prior_outcome.match_status in
                                   {"SPLIT", "MERGED", "AMBIGUOUS"} else "MISSING_OUTCOME"]
                    matches.append({"entity_type": kind,
                        "gold_entity_id" if side == "Gold" else "prediction_entity_id": eid,
                        "match_status": status, "diagnostic": "; ".join(reasons)})
                audit.append(ResultLinkAudit(entity_type=kind, side=side, entity_id=eid,
                    before_status=old_status, after_status=status, before_candidates=old_candidates,
                    after_candidates=sorted(c.prediction_id if side == "Gold" else c.gold_id for c in viable),
                    selected_pair=pair, reason_codes=sorted(set(reasons)), candidate_decisions=cs))
    return ResultLinking(matches=matches, candidates=decisions, audit=audit)
