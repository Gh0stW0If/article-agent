"""Structural candidates, pair judgments, conservative one-to-one resolution.

No result value, SD, sample size, estimate, CI or P value participates in identity.
PR5B MATCHED edges are reserved before any fallback.
"""
from collections import Counter

from ..comparators import compare_values
from ..entity_matcher import GROUPS, entities, match_entities
from .models import HybridEntityMatchResult
from .semantic_judge import entity_request, field_representation, field_request


def _identity_projection(graph, obj, fields, *, evidence_fields=()):
    result = {}
    for name in fields:
        field = getattr(obj, name)
        # Status/conflict candidates are not adjudicated by the identity judge.
        result[name] = (
            field_representation(graph, field, identity_only=name not in evidence_fields)
            if field.status == "PRESENT" else {"value": None, "raw_value": None, "evidence": []}
        )
    return result


def result_identity(kind, g, p, registry, semantic, judge):
    """True/False/None = same/different/unknown. Never compares outcome values."""
    ids, decisions = [], []
    prefix = kind[0].lower() + kind[1:]

    def field_same(name):
        a, b = getattr(g, name), getattr(p, name)
        if a.status == b.status == "PRESENT":
            spec = registry[prefix + "." + name]
            if compare_values(a.value, b.value, spec).matched:
                return True
            # Result identity has only value text, never complete table evidence.
            item = judge.judge(field_request(
                semantic[spec.field_id],
                {"value": a.value, "raw_value": None, "evidence": []},
                {"value": b.value, "raw_value": None, "evidence": []}, identity=True))
            ids.append(item.judgment_id)
            if item.status != "SUCCESS":
                return None
            return item.result["grade"] in {"EXACT", "EQUIVALENT"}
        if name == "analysis_set" and (
            a.status in {"UNRESOLVED", "INSUFFICIENT_CONTEXT"}
            or b.status in {"UNRESOLVED", "INSUFFICIENT_CONTEXT"}
        ):
            # A missing analysis set does not block an otherwise unique candidate.
            # Multiple viable ITT/PP candidates still form an ambiguous component.
            return True
        if a.status == b.status and a.status in {"NOT_REPORTED", "NOT_APPLICABLE"}:
            return True
        return None

    structured = all(getattr(obj, f).status == "PRESENT"
                     for obj in (g, p) for f in ("timepoint_value", "timepoint_unit"))
    if structured:
        decisions.append(all(compare_values(getattr(g, f).value, getattr(p, f).value,
                                            registry[prefix + "." + f]).matched
                             for f in ("timepoint_value", "timepoint_unit")))
    else:
        decisions.append(field_same("timepoint"))
    # Stop on an incompatible timepoint, without unnecessary LLM requests.
    if decisions[-1] is False:
        return False, ids
    for name in ("analysis_set", "value_kind" if kind == "ArmResult" else "effect_measure"):
        decision = field_same(name)
        decisions.append(decision)
        if decision is False:
            return False, ids
    return (None if None in decisions else True), ids


def match_entities_hybrid(prediction, gold, registry, semantic, judge, deterministic=None):
    deterministic = deterministic if deterministic is not None else match_entities(prediction, gold)[0]
    mappings = {kind: {} for kind in GROUPS}
    results = []
    specs = {f.field_id: f for f in registry.fields}
    semantic_specs = semantic.by_id()

    def arm_context(graph, iid, predicted):
        arm_ids = [a.arm_id for a in graph.arms if iid in a.intervention_ids]
        if predicted:
            if any(a not in mappings["Arm"] for a in arm_ids):
                return None
            arm_ids = [mappings["Arm"][a] for a in arm_ids]
        return tuple(sorted(arm_ids))

    for kind in GROUPS:
        locked = [m for m in deterministic if m.entity_type == kind and m.match_status == "MATCHED"]
        for m in locked:
            mappings[kind][m.prediction_entity_id] = m.gold_entity_id
            results.append(HybridEntityMatchResult(**m.model_dump()))
        locked_g = {m.gold_entity_id for m in locked}
        locked_p = {m.prediction_entity_id for m in locked}
        gs = {k: v for k, v in entities(gold.truth, kind).items() if k not in locked_g}
        ps = {k: v for k, v in entities(prediction, kind).items() if k not in locked_p}
        if kind in {"Article", "Study", "Arm"}:
            # Frozen Arm identity and PR5B's safe exact-ID/alias behavior are retained.
            results.extend(HybridEntityMatchResult(**m.model_dump()) for m in deterministic
                           if m.entity_type == kind and m.match_status != "MATCHED")
            continue
        edges = {gid: {} for gid in gs}
        uncertain = {gid: {} for gid in gs}
        g_context, p_context = {}, {}
        if kind == "Intervention":
            g_context = {gid: (g.study_id, arm_context(gold.truth, gid, False)) for gid, g in gs.items()}
            p_context = {pid: (mappings["Study"].get(p.study_id), arm_context(prediction, pid, True))
                         for pid, p in ps.items()}
        elif kind == "Comparison":
            g_context = {gid: (g.study_id, tuple(g.arm_ids)) for gid, g in gs.items()}
            p_context = {pid: (mappings["Study"].get(p.study_id),
                              tuple(mappings["Arm"].get(a) for a in p.arm_ids)) for pid, p in ps.items()}
        gc, pc = Counter(g_context.values()), Counter(p_context.values())
        for gid, g in gs.items():
            for pid, p in ps.items():
                method, decision, ids = None, False, []
                if kind in {"Intervention", "Outcome", "Comparison"}:
                    if mappings["Study"].get(p.study_id) != g.study_id:
                        continue
                    if kind == "Intervention":
                        ctx = g_context[gid]
                        if ctx == p_context[pid] and ctx[1] and gc[ctx] == pc[ctx] == 1:
                            method, decision = "STRUCTURAL_CONTEXT", True
                        else:
                            fields = ("name", "kind", "description", "components")
                            gr = _identity_projection(gold.truth, g, fields)
                            pr = _identity_projection(prediction, p, fields)
                            gr["linked_arm_context"], pr["linked_arm_context"] = ctx[1], p_context[pid][1]
                    elif kind == "Comparison":
                        ctx = g_context[gid]
                        if ctx != p_context[pid] or None in ctx[1]:
                            continue
                        if gc[ctx] == pc[ctx] == 1:
                            method, decision = "STRUCTURAL_CONTEXT", True
                        else:
                            fields = ("relation", "contrast")
                            gr = _identity_projection(gold.truth, g, fields)
                            pr = _identity_projection(prediction, p, fields)
                            gr["ordered_arms"], pr["ordered_arms"] = ctx[1], ctx[1]
                    else:
                        fields = ("name", "instrument", "unit", "role", "direction")
                        gr = _identity_projection(gold.truth, g, fields, evidence_fields=("name", "instrument"))
                        pr = _identity_projection(prediction, p, fields, evidence_fields=("name", "instrument"))
                    if method is None:
                        item = judge.judge(entity_request(kind, gr, pr))
                        ids = [item.judgment_id]
                        decision = None if item.status != "SUCCESS" else {
                            "SAME": True, "DIFFERENT": False, "AMBIGUOUS": None
                        }[item.result["decision"]]
                        method = "SEMANTIC_IDENTITY"
                else:
                    if g.derived != p.derived or mappings["Outcome"].get(p.outcome_id) != g.outcome_id:
                        continue
                    parent, attr = ("Arm", "arm_id") if kind == "ArmResult" else ("Comparison", "comparison_id")
                    if mappings[parent].get(getattr(p, attr)) != getattr(g, attr):
                        continue
                    decision, ids = result_identity(kind, g, p, specs, semantic_specs, judge)
                    method = "SEMANTIC_RESULT_IDENTITY" if ids else "STRUCTURAL_RESULT_IDENTITY"
                if decision is True:
                    edges[gid][pid] = (method, ids)
                elif decision is None:
                    uncertain[gid][pid] = (method, ids)

        # Uncertain competitors block selection, but never become accepted edges.
        possible = {gid: {**edges[gid], **uncertain[gid]} for gid in gs}
        reverse = {pid: {gid for gid in gs if pid in possible[gid]} for pid in ps}
        visited_g, visited_p = set(), set()
        for start in gs:
            if start in visited_g:
                continue
            cg, cp, pending = set(), set(), [start]
            while pending:
                gid = pending.pop()
                if gid in cg:
                    continue
                cg.add(gid)
                for pid in possible[gid]:
                    cp.add(pid)
                    pending.extend(sorted(reverse[pid] - cg))
            visited_g |= cg
            visited_p |= cp
            uncertain_component = any(pid in uncertain[gid] for gid in cg for pid in cp)
            ids = sorted({j for gid in cg for pid in cp for j in possible[gid].get(pid, ("", []))[1]})
            if len(cg) == len(cp) == 1 and not uncertain_component:
                gid, pid = next(iter(cg)), next(iter(cp))
                method, _ = edges[gid][pid]
                mappings[kind][pid] = gid
                results.append(HybridEntityMatchResult(entity_type=kind, gold_entity_id=gid,
                    prediction_entity_id=pid, match_status="MATCHED", match_method=method,
                    semantic_judgment_ids=ids))
                continue
            status = "MISSING" if not cp else "AMBIGUOUS"
            if kind == "Outcome" and cp and not uncertain_component:
                if len(cg) == 1:
                    status = "SPLIT"
                elif len(cp) == 1:
                    status = "MERGED"
            diagnostic = (f"Gold candidates={sorted(cg)}; prediction candidates={sorted(cp)}; "
                          f"uncertain_edges={uncertain_component}; no best-candidate selection")
            results.extend(HybridEntityMatchResult(entity_type=kind, gold_entity_id=gid,
                match_status=status, diagnostic=diagnostic, semantic_judgment_ids=ids) for gid in sorted(cg))
            results.extend(HybridEntityMatchResult(entity_type=kind, prediction_entity_id=pid,
                match_status=status, diagnostic=diagnostic, semantic_judgment_ids=ids) for pid in sorted(cp))
        results.extend(HybridEntityMatchResult(entity_type=kind, prediction_entity_id=pid,
            match_status="EXTRA", diagnostic="No accepted identity edge; no inferred parent binding")
            for pid in sorted(set(ps) - visited_p))
    return results
