"""Offline mapping of reported source records onto a frozen PR3 arm graph.

No extraction, table parsing, API calls, gold or evaluator dependencies.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re

from .domain.models import (
    ArticleExtraction, ArmResult, CanonicalField, Comparison, ComparisonResult,
    Evidence, EvidenceTarget, Outcome, merge_field_observation,
)
from .trial_topology_agent import TrialTopology


def text(value):
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    return None if value.casefold() in {"", "nr", "n/r", "not reported", "unknown", "unresolved", "none", "null"} else value


def key(value):
    return " ".join((text(value) or "").casefold().split())


def outcome_name_key(value):
    """Limited grammatical normalization, not fuzzy clinical synonym matching."""
    name = re.sub(r"^(?:the )?number of\s+", "", key(value))
    match = re.fullmatch(r"frequency of (.+)", name)
    return f"{match[1]} frequency" if match else name


OUTCOME_FIELDS = {
    "name": ("outcome_name", "name"), "instrument": ("measurement_instrument", "instrument"),
    "role": ("outcome_role", "role", "record_role"), "direction": ("direction",),
    "unit": ("unit",), "scale_min": ("scale_min",), "scale_max": ("scale_max",),
}
TIME_FIELDS = {
    "timepoint": ("timepoint", "outcome_observation_timepoint_raw"),
    "timepoint_value": ("timepoint_value", "outcome_observation_timepoint_value"),
    "timepoint_unit": ("timepoint_unit", "outcome_observation_timepoint_unit"),
    "analysis_set": ("analysis_set", "analysis_population"),
}
ARM_FIELDS = {
    "value_kind": ("value_kind", "statistic_type"), "value": ("value", "estimate"),
    "standard_deviation": ("standard_deviation", "sd"),
    "change_from_baseline": ("change_from_baseline", "change"),
    "dispersion_lower": ("dispersion_lower", "lower"), "dispersion_upper": ("dispersion_upper", "upper"),
    "n": ("n",), "event_count": ("event_count",), "denominator": ("denominator",),
    "raw_value": ("raw_value",),
}
COMPARISON_FIELDS = {
    "effect_measure": ("effect_measure", "between_group_measure", "effect_size_name"),
    "estimate": ("estimate", "outcome_between_group_estimate"),
    "confidence_interval_lower": ("confidence_interval_lower", "outcome_between_group_lower"),
    "confidence_interval_upper": ("confidence_interval_upper", "outcome_between_group_upper"),
    "p_value": ("p_value", "outcome_p_value"),
    "p_value_comparator": ("p_value_comparator", "outcome_p_value_comparator"),
    "raw_value": ("raw_value",),
}
NUMERIC = {"scale_min", "scale_max", "timepoint_value", "value", "standard_deviation",
    "change_from_baseline", "dispersion_lower", "dispersion_upper", "n", "event_count",
    "denominator", "estimate", "confidence_interval_lower", "confidence_interval_upper", "p_value"}


def first(data, names):
    return next((data[n] for n in names if text(data.get(n)) is not None), None)


def canonicalize_outcomes(article_id, topology, arm_graph, source_outcomes) -> ArticleExtraction:
    """Pure replay: preserve every source record, reject uncertain arm bindings.

    source_outcomes is a list, an {outcomes: [...]} module, or an ExtractionBundle.
    The input arm_graph must not already contain outcomes/results/comparisons.
    Stable IDs follow first source appearance; result identity excludes source IDs
    only when timepoint is known. Replaying identical ordered inputs is identical.
    """
    topology = TrialTopology.model_validate(topology.model_dump() if isinstance(topology, TrialTopology) else topology)
    graph = ArticleExtraction.model_validate(arm_graph.model_dump() if isinstance(arm_graph, ArticleExtraction) else arm_graph)
    if graph.article.article_id != article_id or len(graph.studies) != 1:
        raise ValueError("article_id and single frozen study must match")
    sid = graph.studies[0].study_id
    if [a.arm_id for a in graph.arms] != [f"{sid}-A{i:02d}" for i in range(1, topology.number_of_arms + 1)]:
        raise ValueError("arm graph does not match frozen topology IDs/order")
    if [key(a.label.value) for a in graph.arms] != [key(a.name) for a in topology.arms]:
        raise ValueError("arm graph labels do not match frozen topology")
    if graph.outcomes or graph.arm_results or graph.comparisons or graph.comparison_results:
        raise ValueError("expected an arm-only graph; replay from the original PR3 artifact")
    data = source_outcomes.model_dump() if hasattr(source_outcomes, "model_dump") else deepcopy(source_outcomes)
    if isinstance(data, dict):
        if data.get("article_id") and data["article_id"] != article_id:
            raise ValueError("source article_id mismatch")
        data = data.get("outcomes", data)
        if isinstance(data, dict):
            data = data.get("outcomes")
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("expected raw source outcome records, not postprocessed/gold payloads")
    graph.article.legacy_fields["pr4_source_outcomes"] = deepcopy(data)
    aliases = {}
    for arm, frozen in zip(graph.arms, topology.arms, strict=True):
        for label in [arm.arm_id, arm.label.value, frozen.name, frozen.source_label, *frozen.aliases]:
            if key(label):
                aliases.setdefault(key(label), set()).add(arm.arm_id)

    def warn(index, reason):
        message = f"PR4 source[{index}]: {reason}; raw source retained"
        if message not in graph.adapter_warnings:
            graph.adapter_warnings.append(message)

    def bind(label):
        found = aliases.get(key(label), set())
        return next(iter(found)) if len(found) == 1 else None

    def bind_arm(arm):
        supplied = [arm[n] for n in ("arm_id", "arm_label", "label") if text(arm.get(n))]
        bound = {bind(label) for label in supplied}
        return next(iter(bound)) if len(bound) == 1 and None not in bound else None

    evidence_counter = 0
    existing_eids = {e.evidence_id for e in graph.evidence}

    def put(entity, entity_type, eid, field, value, row, source, index, source_field=None):
        nonlocal evidence_counter
        if text(value) is None:
            return
        raw = str(value)
        if field in {"name", "instrument"} and getattr(entity, field).value is not None:
            # Identity has already been resolved; spelling variants are not clinical conflicts.
            value = getattr(entity, field).value
        try:
            if field in NUMERIC:
                if isinstance(value, bool):
                    raise ValueError("boolean is not a numeric result")
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError("non-finite value")
                if field in {"n", "event_count", "denominator"}:
                    if value < 0 or not value.is_integer():
                        raise ValueError("invalid count")
                    value = int(value)
            else:
                value = str(value)
        except (TypeError, ValueError):
            warn(index, f"invalid {entity_type}.{field}: {raw}")
            return
        quotes = []
        for context in (source, row) if source is not row else (row,):
            for e in context.get("evidence", []) or []:
                if isinstance(e, dict) and text(e.get("quote")) and e.get("field_id") in (None, "", field, source_field):
                    quotes.append(e)
            if text(context.get("source_evidence")):
                quotes.append({"quote": context["source_evidence"]})
        if not quotes:
            warn(index, f"no evidence for {entity_type}.{field}")
            return
        ids = []
        seen = set()
        for quote in quotes:
            if quote["quote"] in seen:
                continue
            seen.add(quote["quote"])
            evidence_counter += 1
            evidence_id = f"{sid}-O-E{evidence_counter:05d}"
            while evidence_id in existing_eids:
                evidence_counter += 1
                evidence_id = f"{sid}-O-E{evidence_counter:05d}"
            existing_eids.add(evidence_id)
            derived = getattr(entity, "derived", False)
            graph.evidence.append(Evidence(evidence_id=evidence_id,
                targets=[EvidenceTarget(entity_type=entity_type, entity_id=eid, field_id=field)],
                quote=quote["quote"], source_type="table" if row.get("source_cells") else "markdown",
                source_id=str(row.get("source_id") or row.get("row_id") or f"{article_id}:outcome:{index}"),
                table_id=text(row.get("table_id")), row_id=text(row.get("row_id")),
                support_type="derived" if derived else "direct", derivation=getattr(entity, "derivation", None)))
            ids.append(evidence_id)
        incoming = CanonicalField(status="PRESENT", value=value, raw_value=raw, evidence_ids=ids)
        setattr(entity, field, merge_field_observation(getattr(entity, field), incoming))

    def fill(entity, etype, eid, fields, row, source, index):
        for field, names in fields.items():
            for name in names:
                if text(source.get(name)) is not None:
                    value = source[name]
                    if field == "p_value" and isinstance(value, str):
                        match = re.fullmatch(r"\s*(?:[pP]\s*)?([<>=≤≥])?\s*(\d*\.?\d+(?:[eE][-+]?\d+)?)\s*", value)
                        if match:
                            value = match[2]
                            if match[1]:
                                put(entity, etype, eid, "p_value_comparator", match[1], row, source, index, name)
                    put(entity, etype, eid, field, value, row, source, index, name)

    def timing(row, detail):
        merged = dict(row)
        for field, names in TIME_FIELDS.items():
            own = first(detail, names)
            if own is not None:
                for name in names:
                    merged.pop(name, None)
                merged[field] = own
        return merged

    def result_key(oid, target, row, detail, kind, index):
        context = timing(row, detail)
        t = tuple(key(first(context, names)) for names in TIME_FIELDS.values())
        time_identity = ("raw", t[0]) if t[0] else (("numeric", t[1], t[2]) if t[1] and t[2] else None)
        # Unknown timepoints from different rows must not create false conflicts.
        unknown_scope = None if time_identity else (row.get("table_id"), row.get("row_id") or index)
        return (oid, target, time_identity, t[3], key(kind), unknown_scope, detail.get("derived", row.get("derived", False)),
                detail.get("derivation", row.get("derivation")))

    def derivation(row, detail, index):
        derived = detail.get("derived", row.get("derived", False))
        formula = text(detail.get("derivation", row.get("derivation")))
        marked_derived = any(e.get("support_type") == "derived" for context in (row, detail)
            for e in (context.get("evidence") or []) if isinstance(e, dict))
        if not isinstance(derived, bool) or (derived and not formula) or (not derived and (formula or marked_derived)):
            warn(index, "invalid derived flag or missing derivation")
            return None
        return {"derived": derived, "derivation": formula if derived else None}

    # Resolve missing instruments only if the same lexical outcome has one known instrument.
    instruments = {}
    for row in data:
        name = outcome_name_key(first(row, OUTCOME_FIELDS["name"]))
        instr = key(first(row, OUTCOME_FIELDS["instrument"]))
        if instr:
            instruments.setdefault(name, set()).add(instr)
    outcomes, arm_results, comparisons, comparison_results = {}, {}, {}, {}
    for index, row in enumerate(data):
        if row.get("article_id") and row["article_id"] != article_id:
            warn(index, "source record article_id mismatch")
            continue
        name = outcome_name_key(first(row, OUTCOME_FIELDS["name"]))
        if not name:
            warn(index, "missing outcome identity")
            continue
        instr = key(first(row, OUTCOME_FIELDS["instrument"]))
        known = instruments.get(name, set())
        if not instr and len(known) == 1:
            instr = next(iter(known))
        elif not instr and len(known) > 1:
            warn(index, "ambiguous outcome instrument; kept separate")
        identity = (name, instr)
        if identity not in outcomes:
            outcomes[identity] = Outcome(outcome_id=f"{sid}-O{len(outcomes)+1:02d}", study_id=sid)
        outcome = outcomes[identity]
        oid = outcome.outcome_id
        fill(outcome, "Outcome", oid, OUTCOME_FIELDS, row, row, index)
        arms = row.get("arm", row.get("arms", [])) or []
        if isinstance(arms, dict):
            arms = [arms]
        for arm in arms:
            if not isinstance(arm, dict):
                warn(index, "invalid arm observation shape")
                continue
            aid = bind_arm(arm)
            if not aid:
                warn(index, f"unknown/ambiguous arm binding {arm.get('arm_label', arm.get('label', arm.get('arm_id')))}")
                continue
            support = derivation(row, arm, index)
            if support is None:
                continue
            kind = first(arm, ARM_FIELDS["value_kind"]) or first(row, ARM_FIELDS["value_kind"])
            ident = result_key(oid, aid, row, arm, kind, index)
            if ident not in arm_results:
                arm_results[ident] = ArmResult(arm_result_id=f"{sid}-AR{len(arm_results)+1:03d}",
                    outcome_id=oid, arm_id=aid, source_table_id=text(row.get("table_id")),
                    source_row_id=text(row.get("row_id")), **support)
            result = arm_results[ident]
            rid = result.arm_result_id
            fill(result, "ArmResult", rid, TIME_FIELDS, row, timing(row, arm), index)
            fill(result, "ArmResult", rid, ARM_FIELDS, row, arm, index)
            if first(arm, ARM_FIELDS["value_kind"]) is None:
                fill(result, "ArmResult", rid, {"value_kind": ARM_FIELDS["value_kind"]}, row, row, index)
            # Copy an already-parsed cell's raw string only with a unique arm match.
            if not text(arm.get("raw_value")):
                cells = [c for c in (row.get("source_cells") or []) if isinstance(c, dict) and bind(c.get("arm_label")) == aid]
                if len(cells) == 1:
                    put(result, "ArmResult", rid, "raw_value", cells[0].get("raw_value"), row, row, index)
            result.legacy_fields.setdefault("source_observations", []).append({"source_index": index, "arm": deepcopy(arm),
                "table_id": row.get("table_id"), "row_id": row.get("row_id")})

        explicit = row.get("comparisons")
        if explicit is None:
            explicit = [row.get("comparison") or {}]
            contrast = text(explicit[0].get("contrast"))
            if contrast and ";" in contrast:
                parts = [part.strip() for part in contrast.split(";")]
                pairs = [re.split(r"\s+vs\.?\s+", part, flags=re.I) for part in parts]
                if all(len(pair) == 2 and all(bind(label) for label in pair) for pair in pairs):
                    explicit = [{"contrast": part, "arm_labels": pair} for part, pair in zip(parts, pairs)]
                    warn(index, "multiple explicit pairs: unscoped row-level statistics not copied to each pair")
        if isinstance(explicit, dict):
            explicit = [explicit]
        if not isinstance(explicit, list):
            warn(index, "invalid comparison source shape")
            continue
        for comparison in explicit:
            if not isinstance(comparison, dict):
                warn(index, "invalid comparison source")
                continue
            labels = comparison.get("arm_ids") or comparison.get("arm_labels") or []
            if not labels and text(comparison.get("intervention_arm_id")):
                labels = [comparison["intervention_arm_id"], *(comparison.get("comparator_arm_ids") or [])]
                if text(comparison.get("control_arm_id")):
                    labels.append(comparison["control_arm_id"])
            contrast = text(comparison.get("contrast"))
            if not labels and contrast:
                # Only a single complete explicit pair: never split an ambiguous pooled P.
                pair = re.split(r"\s+vs\.?\s+", contrast, flags=re.I)
                if len(pair) == 2 and ";" not in contrast:
                    labels = pair
            bound = [bind(label) for label in labels]
            if len(bound) < 2 or None in bound or len(set(bound)) != len(bound):
                if contrast or any(first(row, names) is not None for names in COMPARISON_FIELDS.values()) or row.get("p_value_cells") or labels:
                    warn(index, "comparison participants not uniquely explicit; P/effect retained without assignment")
                continue
            if not (contrast or text(comparison.get("relation"))):
                warn(index, "arm list alone does not establish a reported comparison")
                continue
            if not any(text(context.get("source_evidence")) or any(text(e.get("quote")) for e in (context.get("evidence") or []) if isinstance(e, dict))
                       for context in (row, comparison)):
                warn(index, "comparison lacks source evidence")
                continue
            ckey = tuple(bound)
            if ckey not in comparisons:
                comparisons[ckey] = Comparison(comparison_id=f"{sid}-C{len(comparisons)+1:02d}", study_id=sid, arm_ids=bound)
            comp = comparisons[ckey]
            cid = comp.comparison_id
            fill(comp, "Comparison", cid, {"relation": ("relation",), "contrast": ("contrast",)}, row, comparison, index)
            # Multiple reported comparisons must carry their own statistics.
            values = {**row, **comparison} if len(explicit) == 1 else comparison
            support = derivation(row, values, index)
            if support is None:
                continue
            ident = result_key(oid, cid, row, values, first(values, COMPARISON_FIELDS["effect_measure"]), index)
            if ident not in comparison_results:
                comparison_results[ident] = ComparisonResult(comparison_result_id=f"{sid}-CR{len(comparison_results)+1:03d}",
                    outcome_id=oid, comparison_id=cid, **support)
            result = comparison_results[ident]
            rid = result.comparison_result_id
            fill(result, "ComparisonResult", rid, TIME_FIELDS, row, timing(row, values), index)
            fill(result, "ComparisonResult", rid, COMPARISON_FIELDS, row, values, index)
            if not text(values.get("raw_value")) and len(explicit) == 1 and row.get("source_values"):
                put(result, "ComparisonResult", rid, "raw_value", json.dumps(row["source_values"], ensure_ascii=False), row, row, index)
            result.legacy_fields.setdefault("source_observations", []).append({"source_index": index,
                "table_id": row.get("table_id"), "row_id": row.get("row_id"), "comparison": deepcopy(comparison)})

    # Assemble once so intermediate graph references cannot trigger partial validation.
    payload = graph.model_dump()
    payload.update(outcomes=[x.model_dump() for x in outcomes.values()],
        arm_results=[x.model_dump() for x in arm_results.values()],
        comparisons=[x.model_dump() for x in comparisons.values()],
        comparison_results=[x.model_dump() for x in comparison_results.values()])
    payload["studies"][0]["outcome_ids"] = [x.outcome_id for x in outcomes.values()]
    return ArticleExtraction.model_validate(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline PR4 source-record canonicalization (no API)")
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--arm-graph", type=Path, required=True)
    parser.add_argument("--source-outcomes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    graph = canonicalize_outcomes(args.article_id, load(args.topology), load(args.arm_graph), load(args.source_outcomes))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({"outcomes": len(graph.outcomes), "arm_results": len(graph.arm_results),
        "comparisons": len(graph.comparisons), "comparison_results": len(graph.comparison_results),
        "warnings": len(graph.adapter_warnings)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
