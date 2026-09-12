"""Source-side pure functions. These APIs do not receive Gold or cross-side mappings."""
from itertools import combinations
import re

from .models import (
    NormalizationEvent, OutcomeIdentityProjection, OutcomeNormalization, RawIdentityField,
    ResultIdentityProjection, SourceIdentityContext,
)
from .normalizers import normalize_analysis, normalize_statistic, normalize_text, normalize_timepoint
from .source_context import source_blocks_for_result


def raw_identity(field):
    return RawIdentityField(status=field.status.value, value=field.value,
                            raw_value=field.raw_value, evidence_ids=list(field.evidence_ids))


def _present(field):
    return field.value if field.status == "PRESENT" else None


def _wrapper(name):
    text = normalize_text(name)
    text = re.sub(r"^the\s+", "", text)
    m = re.match(r"^(number|count|rate|percentage|proportion)\s+of\s+(.+)", text)
    kind = None
    if m:
        kind = "event_count" if m[1] in {"number", "count"} else "percentage" if m[1] == "percentage" else "proportion"
        text = m[2]
    text = re.sub(r"\s*\(\s*n\s*[,/]\s*%\s*\)\s*\*?$", "", text)
    if kind:
        text = re.sub(r"\s+(patients|participants)$", "", text)
        text = re.sub(r"^(?:patients|participants)\s+(?:reaching|with|achieving)\s+", "", text)
    return text.strip(), kind


def canonicalize_source_outcomes(graph, source_context=None):
    """Group only within one source graph, never by similarity to a Gold label."""
    context = source_context or SourceIdentityContext()
    evidence = {e.evidence_id: e for e in graph.evidence}
    row_context = {(r.table_id, r.row_id): r for r in context.rows}
    projections = []
    for outcome in sorted(graph.outcomes, key=lambda o: o.outcome_id):
        name = _present(outcome.name)
        concept, wrapper = _wrapper(name) if name else (None, None)
        linked = [evidence[eid] for eid in outcome.name.evidence_ids]
        blocks = sorted({f"{e.table_id}|{e.row_id}" for e in linked if e.table_id and e.row_id})
        rows = [row_context[(e.table_id, e.row_id)] for e in linked if (e.table_id, e.row_id) in row_context]
        events = []
        source_concepts = set()
        for row in rows:
            row_concept, row_wrapper = _wrapper(row.row_label)
            # A source row's explicit count wrapper can explain a shortened source name.
            base_label = normalize_text(name)
            source_short = re.sub(r"^(?:the\s+)?(?:number|count|rate|percentage|proportion)\s+of\s+", "", normalize_text(row.row_label))
            source_short = re.sub(r"\s*\(\s*n\s*[,/]\s*%\s*\)\s*\*?$", "", source_short).strip()
            if row.construct_label and wrapper:
                source_concepts.add(normalize_text(row.construct_label))
            elif row_wrapper and (base_label == source_short or concept == row_concept):
                source_concepts.add(row_concept)
                wrapper = wrapper or row_wrapper
        if len(source_concepts) == 1:
            concept = next(iter(source_concepts))
            events.append(NormalizationEvent(field="outcome", rule="OUTCOME_STATISTIC_WRAPPER_SEPARATED",
                explanation="Explicit source row separates construct from statistical presentation.",
                source_refs=sorted({x for r in rows for x in r.source_refs})))
        elif wrapper:
            # Without explicit row context, only remove a syntactically explicit wrapper
            # backed by the field's own source wording. This alone never authorizes merge.
            if not any(normalize_text(name) in normalize_text(e.quote) for e in linked):
                concept, wrapper = normalize_text(name), None
            else:
                events.append(NormalizationEvent(field="outcome", rule="OUTCOME_STATISTIC_WRAPPER_SEPARATED",
                    explanation="Literal source-backed statistic wrapper; no synonym expansion.",
                    source_refs=[e.evidence_id for e in linked]))
        definitions = {r.measurement_definition for r in rows if r.measurement_definition}
        definition = next(iter(definitions)) if len(definitions) == 1 else None
        blockers = [field.upper() + "_SOURCE_UNCERTAINTY" for field in ("name", "instrument", "unit")
                    if getattr(outcome, field).status in {"SOURCE_CONFLICT", "REVIEW_REQUIRED"}]
        if len(definitions) > 1 or len(source_concepts) > 1:
            blockers.append("OUTCOME_SOURCE_DEFINITION_CONFLICT")
        projections.append(OutcomeIdentityProjection(
            outcome_id=outcome.outcome_id, study_id=outcome.study_id, raw_name=raw_identity(outcome.name),
            canonical_concept=concept, statistic_wrapper=wrapper,
            instrument=normalize_text(_present(outcome.instrument)) or None,
            unit=normalize_text(_present(outcome.unit)) or None, definition=definition,
            source_blocks=blocks, normalization_events=events, identity_blockers=blockers))
    allowed, decisions = set(), []
    for a, b in combinations(projections, 2):
        if a.study_id != b.study_id or not a.canonical_concept or a.canonical_concept != b.canonical_concept:
            continue
        shared = sorted(set(a.source_blocks) & set(b.source_blocks))
        contradictory = any(x is not None and y is not None and x != y
                            for x, y in ((a.instrument, b.instrument), (a.unit, b.unit), (a.definition, b.definition)))
        uncertain = bool(a.identity_blockers or b.identity_blockers)
        merge = bool(shared) and not contradictory and not uncertain and bool(a.statistic_wrapper or b.statistic_wrapper)
        if merge:
            allowed.add(frozenset((a.outcome_id, b.outcome_id)))
        decisions.append({"outcome_ids": [a.outcome_id, b.outcome_id], "merge": merge,
                          "reason": "OUTCOME_SHARED_SOURCE_STATISTIC_WRAPPER" if merge else
                          "OUTCOME_MEASUREMENT_CONTRADICTION" if contradictory else
                          "OUTCOME_SOURCE_UNCERTAINTY" if uncertain else "OUTCOME_NO_SHARED_SOURCE_BLOCK",
                          "shared_source_blocks": shared})
    # Complete-link grouping avoids transitive A~B~C merges without A~C evidence.
    groups = {}
    for p in projections:
        key = next((k for k, ids in groups.items() if all(
            frozenset((p.outcome_id, existing)) in allowed for existing in ids)), p.outcome_id)
        groups.setdefault(key, []).append(p.outcome_id)
    ids = {item: key for key, members in groups.items() for item in members}
    return OutcomeNormalization(projections=projections, canonical_ids=ids, groups=groups, decisions=decisions)


def project_results(graph, source_context=None, outcomes=None):
    """Read identity fields and explicit source coordinates only, never result statistics."""
    context = source_context or SourceIdentityContext()
    outcomes = outcomes or canonicalize_source_outcomes(graph, context)
    rows = {(r.table_id, r.row_id): r for r in context.rows}
    projections = []
    for kind, items in (("ArmResult", graph.arm_results), ("ComparisonResult", graph.comparison_results)):
        for result in sorted(items, key=lambda x: x.arm_result_id if kind == "ArmResult" else x.comparison_result_id):
            statistic_field = result.value_kind if kind == "ArmResult" else result.effect_measure
            pairs = source_blocks_for_result(result)
            context_rows = [rows[pair] for pair in pairs if pair in rows] if kind == "ArmResult" else []
            statistic, se, blockers = normalize_statistic(_present(statistic_field), context_rows)
            timepoint, te = normalize_timepoint(_present(result.timepoint),
                _present(result.timepoint_value), _present(result.timepoint_unit))
            analysis, ae = normalize_analysis(_present(result.analysis_set))
            for name, field in (("TIMEPOINT", result.timepoint), ("TIMEPOINT_VALUE", result.timepoint_value),
                                ("TIMEPOINT_UNIT", result.timepoint_unit), ("ANALYSIS_SET", result.analysis_set),
                                ("STATISTIC_KIND", statistic_field)):
                if field.status in {"SOURCE_CONFLICT", "REVIEW_REQUIRED"}:
                    blockers.append(name + "_SOURCE_UNCERTAINTY")
            projections.append(ResultIdentityProjection(
                entity_type=kind,
                entity_id=result.arm_result_id if kind == "ArmResult" else result.comparison_result_id,
                parent_type="Arm" if kind == "ArmResult" else "Comparison",
                parent_id=result.arm_id if kind == "ArmResult" else result.comparison_id,
                raw_outcome_id=result.outcome_id, canonical_outcome_id=outcomes.canonical_ids[result.outcome_id],
                raw_timepoint=raw_identity(result.timepoint),
                raw_timepoint_value=raw_identity(result.timepoint_value),
                raw_timepoint_unit=raw_identity(result.timepoint_unit),
                canonical_timepoint=timepoint,
                raw_analysis_set=raw_identity(result.analysis_set), canonical_analysis_set=analysis,
                raw_statistic_kind=raw_identity(statistic_field), canonical_statistic_kind=statistic,
                derived=result.derived, source_refs=[f"{a}|{b}" for a, b in pairs],
                normalization_events=te + ae + se, identity_blockers=blockers + timepoint.blockers))
    return projections
