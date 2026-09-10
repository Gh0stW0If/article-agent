"""Dependency-ordered candidate graphs; ambiguous components are never scored."""
import json
from .models import EntityMatchResult
from .normalization import normalize

GROUPS = {
    "Article": ("article", "article_id"), "Study": ("studies", "study_id"),
    "Arm": ("arms", "arm_id"), "Intervention": ("interventions", "intervention_id"),
    "Outcome": ("outcomes", "outcome_id"), "Comparison": ("comparisons", "comparison_id"),
    "ArmResult": ("arm_results", "arm_result_id"),
    "ComparisonResult": ("comparison_results", "comparison_result_id"),
}


def entities(graph, kind):
    collection, id_field = GROUPS[kind]
    items = [graph.article] if kind == "Article" else getattr(graph, collection)
    return {getattr(item, id_field): item for item in sorted(items, key=lambda x: getattr(x, id_field))}


def field_key(field):
    if field.status == "PRESENT":
        return ("PRESENT", normalize(field.value) if isinstance(field.value, str) else field.value)
    # Missing instrument/analysis set is comparable only as the same explicit state.
    return (field.status.value, None)


def time_key(item):
    if item.timepoint.status == "PRESENT":
        return field_key(item.timepoint)
    if item.timepoint_value.status == item.timepoint_unit.status == "PRESENT":
        return (item.timepoint_value.value, normalize(item.timepoint_unit.value))
    return field_key(item.timepoint)


def match_entities(prediction, gold):
    truth = gold.truth
    mappings = {kind: {} for kind in GROUPS}  # prediction ID -> Gold ID
    matches, failures = [], []

    def alias_match(kind, gid, name, gfield, pfield):
        if gfield.status == pfield.status == "PRESENT" and field_key(gfield) == field_key(pfield):
            return "SEMANTIC_IDENTITY"
        if pfield.status == "PRESENT":
            for alias in gold.entity_aliases:
                if alias.entity_type == kind and alias.entity_id == gid:
                    if normalize(pfield.value) in [normalize(v) for v in alias.accepted_values.get(name, [])]:
                        return "GOLD_ALIAS"
        return None

    def context(graph, iid, predicted):
        ids = [a.arm_id for a in graph.arms if iid in a.intervention_ids]
        if predicted:
            if any(a not in mappings["Arm"] for a in ids):
                return None
            ids = [mappings["Arm"][a] for a in ids]
        return tuple(sorted(ids))

    def key(kind, obj, predicted):
        def mapped(parent, value):
            return mappings[parent].get(value) if predicted else value
        if kind == "Comparison":
            arms = tuple(mapped("Arm", a) for a in obj.arm_ids)
            if not arms or None in arms:
                return None, "COMPARATOR_SCOPE_UNRESOLVED"
            return (mapped("Study", obj.study_id), arms, field_key(obj.relation), field_key(obj.contrast)), None
        outcome = mapped("Outcome", obj.outcome_id)
        if kind == "ArmResult":
            parent = mapped("Arm", obj.arm_id)
            if parent is None:
                return None, "ARM_BINDING_UNRESOLVED"
            tail = field_key(obj.value_kind)
        else:
            parent = mapped("Comparison", obj.comparison_id)
            if parent is None:
                return None, "COMPARATOR_SCOPE_UNRESOLVED"
            tail = field_key(obj.effect_measure)
        if outcome is None:
            return None, "ENTITY_MISSING"
        return (parent, outcome, time_key(obj), field_key(obj.analysis_set), tail, obj.derived), None

    for kind in GROUPS:
        gs, ps = entities(truth, kind), entities(prediction, kind)
        edges = {gid: {} for gid in gs}
        blocked = {}
        identity_keys = {}
        for pid, p in ps.items():
            if kind in {"Comparison", "ArmResult", "ComparisonResult"}:
                pk, reason = key(kind, p, True)
                identity_keys[pid] = pk
                if reason:
                    blocked[pid] = reason
                    continue
            for gid, g in gs.items():
                method = None
                if kind in {"Article", "Study"}:
                    if gid == pid and (kind == "Article" or mappings["Article"].get(p.article_id) == g.article_id):
                        method = "EXACT_ID"
                elif kind in {"Arm", "Outcome", "Intervention"}:
                    if mappings["Study"].get(p.study_id) != g.study_id:
                        continue
                    if kind == "Arm":
                        # Reserve exact IDs before considering label fallback.
                        if pid in gs:
                            method = "EXACT_ID" if pid == gid else None
                        elif gid not in ps:
                            method = alias_match(kind, gid, "label", g.label, p.label)
                    elif kind == "Outcome":
                        if field_key(g.instrument) == field_key(p.instrument):
                            method = alias_match(kind, gid, "name", g.name, p.name)
                    elif context(prediction, pid, True) == context(truth, gid, False):
                        method = alias_match(kind, gid, "name", g.name, p.name)
                else:
                    gk, _ = key(kind, g, False)
                    if pk is not None and pk == gk:
                        method = "COMPOSITE_IDENTITY"
                if method:
                    edges[gid][pid] = method

        reverse = {pid: {gid for gid in gs if pid in edges[gid]} for pid in ps}
        visited_g, visited_p = set(), set()
        for gid in gs:
            if gid in visited_g:
                continue
            cg, cp, pending = set(), set(), [gid]
            while pending:
                current = pending.pop()
                if current in cg:
                    continue
                cg.add(current)
                for pid in edges[current]:
                    cp.add(pid)
                    pending.extend(reverse[pid] - cg)
            visited_g |= cg
            visited_p |= cp
            if len(cg) == len(cp) == 1:
                g_id, p_id = next(iter(cg)), next(iter(cp))
                mappings[kind][p_id] = g_id
                matches.append(EntityMatchResult(entity_type=kind, gold_entity_id=g_id,
                    prediction_entity_id=p_id, match_status="MATCHED", match_method=edges[g_id][p_id],
                    identity_key={"composite": json.loads(json.dumps(identity_keys.get(p_id)))}))
                continue
            status = "MISSING" if not cp else "AMBIGUOUS"
            classification = "ENTITY_MISSING" if not cp else "ENTITY_AMBIGUOUS"
            if kind == "Outcome" and cp:
                if len(cg) == 1:
                    status, classification = "SPLIT", "OUTCOME_IDENTITY_SPLIT"
                elif len(cp) == 1:
                    status, classification = "MERGED", "OUTCOME_IDENTITY_MERGE"
            diagnostic = f"Gold candidates={sorted(cg)}; prediction candidates={sorted(cp)}"
            for g_id in sorted(cg):
                matches.append(EntityMatchResult(entity_type=kind,gold_entity_id=g_id,
                    match_status=status,diagnostic=diagnostic))
            for p_id in sorted(cp):
                matches.append(EntityMatchResult(entity_type=kind,prediction_entity_id=p_id,
                    match_status=status,diagnostic=diagnostic))
            failures.append({"entity_type":kind,"gold_entity_ids":sorted(cg),
                "prediction_entity_ids":sorted(cp),"classification":classification,"diagnostic":diagnostic})
        for pid in sorted(set(ps) - visited_p):
            classification = blocked.get(pid, "ENTITY_EXTRA")
            diagnostic = "Parent identity unmatched; no inferred binding" if pid in blocked else None
            matches.append(EntityMatchResult(entity_type=kind,prediction_entity_id=pid,
                match_status="EXTRA",diagnostic=diagnostic))
            failures.append({"entity_type":kind,"gold_entity_ids":[],"prediction_entity_ids":[pid],
                "classification":classification,"diagnostic":diagnostic})
    return matches, failures
