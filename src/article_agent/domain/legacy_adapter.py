"""Opt-in, one-way projection; never reads Gold or mutates extraction inputs."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Callable

from pydantic import BaseModel

from .models import (
    Arm, ArmResult, Article, ArticleExtraction, CanonicalField, Comparison,
    ComparisonResult, Evidence, EvidenceTarget, FieldStatus, Intervention,
    Outcome, Study, merge_field_observation,
)


MISSING = {"", "NR", "NOT REPORTED", "NONE", "NULL", "UNKNOWN"}
TIMEPOINT_UNITS = {1: "day", 2: "month", 3: "year", 4: "week", 5: "hour"}
FREQUENCY_UNITS = {1: "day", 2: "week", 3: "hour"}
DURATION_UNITS = {1: "day", 2: "week"}
BLINDING = {1: "YES", 2: "NO"}
PRIMARY_ANALYSIS = {1: "ITT_OR_MITT", 2: "AVAILABLE_CASE", 3: "PER_PROTOCOL"}
MISSING_DATA = dict(enumerate([
    "COMPLETE_CASE", "ALL_AVAILABLE", "MEAN_IMPUTATION", "LOCF", "REGRESSION",
    "MULTIPLE_IMPUTATION", "MAXIMUM_LIKELIHOOD", "WEIGHTING", "COMBINATION",
    "MIXED_EFFECT_MODEL", "OTHER", "NO_MISSING_DATA",
], start=1))


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    raise TypeError("legacy bundle must be a Pydantic model or mapping")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _text(value: Any) -> str | None:
    if value is None or str(value).strip().upper() in MISSING | {"NA", "N/A"}:
        return None
    return str(value).strip()


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a clinical number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite clinical number")
    return number


def _integer(value: Any) -> int:
    number = _number(value)
    if not number.is_integer():
        raise ValueError("non-integral count")
    return int(number)


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def _code(mapping: dict[int, Any]) -> Callable[[Any], Any]:
    def convert(value: Any) -> Any:
        return mapping.get(_integer(value))
    return convert


def _id(prefix: str, *parts: Any) -> str:
    # Exact source identity: punctuation/non-Latin labels cannot collide through slugging.
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:20]}"


def _observation(raw: Any, evidence_ids: list[str], convert: Callable = lambda x: x) -> CanonicalField:
    raw_text = raw if isinstance(raw, str) else (json.dumps(raw, ensure_ascii=False) if raw is not None else None)
    marker = str(raw).strip().upper()
    status = FieldStatus.UNRESOLVED
    value = None
    if marker in {"NA", "N/A", "NOT APPLICABLE"}:
        status = FieldStatus.NOT_APPLICABLE
    elif raw is not None and marker not in MISSING and raw != []:
        try:
            value = convert(raw)
            if value is not None:
                status = FieldStatus.PRESENT
        except (ValueError, TypeError, OverflowError):
            status = FieldStatus.REVIEW_REQUIRED
    return CanonicalField(status=status, value=value, raw_value=raw_text, evidence_ids=evidence_ids)


class _Context:
    """Field-specific quotes plus an optional shared row quote; no module-wide evidence borrowing."""

    def __init__(self, data: dict, source: str, pool: dict[str, Evidence]):
        self.data, self.source, self.pool = data, source, pool
        self.evidence_by_field: dict[str, list[str]] = {}
        self.shared: list[str] = []
        quotes = list(data.get("evidence") or [])
        if _text(data.get("source_evidence")):
            quotes.append({"quote": data["source_evidence"], "source": "table" if _text(data.get("table_id")) else "markdown"})
        for quote_value in quotes:
            quote = _dict(quote_value)
            if not _text(quote.get("quote")):
                continue
            key = str(quote.get("field_id") or "")
            eid = _id("evidence", source, quote, data.get("table_id"), data.get("row_id"))
            support = quote.get("support_type") or "direct"
            source_name = str(quote.get("source") or "other").lower()
            source_type = {"crossref": "bibliographic", "markdown": "markdown", "table": "table",
                           "figure": "figure", "bibliographic": "bibliographic"}.get(source_name, "other")
            # Invalid derived evidence is rejected rather than relabeled as direct.
            pool[eid] = Evidence(
                evidence_id=eid, field_paths=[key] if key else [], quote=str(quote["quote"]),
                source_type=source_type,
                source_id=source, page=quote.get("page"), section=quote.get("section"),
                table_id=_text(data.get("table_id")), row_id=_text(data.get("row_id")),
                support_type=support, derivation=quote.get("derivation"), legacy_fields=quote,
            )
            if key:
                self.evidence_by_field.setdefault(key, []).append(eid)
            else:
                self.shared.append(eid)

    def field(self, key: str, convert: Callable = lambda x: x, *, evidence_keys: tuple[str, ...] = ()) -> CanonicalField:
        ids = list(self.shared)
        for evidence_key in (key, *evidence_keys):
            # Accept short legacy names and explicit module-qualified names, not suffix guesses.
            ids += self.evidence_by_field.get(evidence_key, [])
        return _observation(self.data.get(key), _unique(ids), convert)

    def child(self, data: dict, key: str) -> "_Context":
        child = _Context(data, f"{self.source}:{key}", self.pool)
        child.shared = _unique(child.shared + self.shared)
        return child


def _merge_entity(existing: BaseModel, incoming: BaseModel) -> BaseModel:
    updates = {
        key: merge_field_observation(getattr(existing, key), value)
        for key, value in incoming if isinstance(value, CanonicalField)
    }
    # Keep complete, distinct source projections for audit, including raw spellings.
    sources = deepcopy(existing.legacy_fields.get("observations", [existing.legacy_fields]))
    if incoming.legacy_fields not in sources:
        sources.append(deepcopy(incoming.legacy_fields))
    updates["legacy_fields"] = {"observations": sources}
    return type(existing).model_validate({**existing.model_dump(), **updates})


def legacy_bundle_to_canonical(bundle: BaseModel | Mapping[str, Any]) -> ArticleExtraction:
    data = _dict(bundle)
    article_id = _text(data.get("article_id"))
    if not article_id:
        raise ValueError("legacy bundle has no article_id")
    sid = f"{article_id}:study-1"
    pool: dict[str, Evidence] = {}
    contexts = {
        key: _Context(_dict(data.get(key) or {}), f"{article_id}:legacy:{key}", pool)
        for key in ("metadata", "acupuncture", "risk_of_bias", "consort_flow")
    }
    meta, acu, risk, flow = (contexts[key] for key in ("metadata", "acupuncture", "risk_of_bias", "consort_flow"))
    article = Article(
        article_id=article_id, title=meta.field("title", str), doi=meta.field("doi", str),
        publication_year=meta.field("publication_year", _integer), journal=meta.field("journal", str),
        language=meta.field("language", str), authors=meta.field("first_author", _strings),
        correspondence=meta.field("author_contact", _strings), legacy_fields=meta.data,
    )
    interventions: list[Intervention] = []
    intervention_by_role: dict[str, str] = {}
    for role in ("intervention", "control"):
        if not _text(meta.data.get(role)):
            continue
        iid = f"{sid}:{role}"
        protocol = {}
        if role == "intervention":
            protocol = {
                "frequency_raw": acu.field("treatment_frequency_raw", str),
                "frequency_value": acu.field("treatment_frequency_value", _number),
                "frequency_unit": acu.field("treatment_frequency_unit", _code(FREQUENCY_UNITS)),
                "duration_raw": acu.field("treatment_duration_raw", str),
                "duration_value": acu.field("treatment_duration_value", _number),
                "duration_unit": acu.field("treatment_duration_unit", _code(DURATION_UNITS)),
                "total_sessions": acu.field("total_sessions", _integer),
            }
        interventions.append(Intervention(
            intervention_id=iid, study_id=sid, name=meta.field(role, str),
            **protocol, legacy_fields={"metadata_name": meta.data.get(role), "protocol": acu.data},
        ))
        intervention_by_role[role] = iid

    arms: dict[str, Arm] = {}
    aliases: dict[str, str] = {}

    def ensure_arm(context: _Context, alias: str | None, label_key: str, role_raw: Any = None,
                   count_keys: dict[str, str] | None = None, label_context: _Context | None = None) -> str:
        label = (label_context or context).field(label_key, str)
        role = _observation(role_raw, label.evidence_ids, str)
        counts = {key: context.field(source, _integer) for key, source in (count_keys or {}).items()}
        aid = aliases.get(alias or "")
        if not aid and label.status == FieldStatus.PRESENT:
            matching = [key for key, arm in arms.items() if arm.label.status == FieldStatus.PRESENT
                        and arm.label.value.casefold() == label.value.casefold()]
            if len(matching) == 1:
                aid = matching[0]
        if not aid:
            aid = _id("arm", sid, alias or label.value or context.source)
        incoming = Arm(arm_id=aid, study_id=sid, label=label, role=role,
                       **counts, legacy_fields=context.data)
        if role.value in intervention_by_role:
            incoming.intervention_ids = [intervention_by_role[role.value]]
        if aid in arms:
            linked = _unique(arms[aid].intervention_ids + incoming.intervention_ids)
            arms[aid] = _merge_entity(arms[aid], incoming)
            arms[aid].intervention_ids = linked
        else:
            arms[aid] = incoming
        if alias:
            aliases[alias] = aid
        return aid

    defaults: dict[str, str] = {}
    for role in ("intervention", "control"):
        count_key = f"randomized_sample_{role}_raw"
        if _text(meta.data.get(role)) or risk.data.get(count_key) is not None:
            defaults[role] = ensure_arm(risk, role, role, role,
                                       {"randomized_n": count_key}, meta)
    for index, raw in enumerate(flow.data.get("arms") or []):
        context = flow.child(_dict(raw), f"arms:{index}")
        ensure_arm(context, f"flow:{index}", "arm_name", count_keys={
            key: key for key in ("randomized_n", "received_n", "analyzed_n", "dropout_n")
        })

    rows: list[_Context] = []
    row_arm_ids: dict[tuple[int, int], str] = {}
    for index, raw in enumerate((data.get("outcomes") or {}).get("outcomes") or []):
        row = _Context(_dict(raw), f"{article_id}:legacy:outcomes:{index}", pool)
        rows.append(row)
        for arm_index, arm_raw in enumerate(row.data.get("arm") or []):
            arm = row.child(_dict(arm_raw), f"arm:{arm_index}")
            row_arm_ids[index, arm_index] = ensure_arm(
                arm, _text(arm.data.get("arm_id")), "arm_label", arm.data.get("role"),
                # OutcomeArm.n belongs to this result, not the randomized population.
            )

    outcomes: dict[tuple, Outcome] = {}
    arm_results: list[ArmResult] = []
    comparisons: dict[tuple, Comparison] = {}
    comparison_results: list[ComparisonResult] = []
    warnings = list(data.get("cross_check_issues") or [])
    for index, row in enumerate(rows):
        name = row.field("outcome_name", str)
        instrument = row.field("measurement_instrument", str)
        key = ((name.value or f"unresolved:{index}").casefold(), (instrument.value or "").casefold())
        oid = _id("outcome", sid, key)
        incoming = Outcome(outcome_id=oid, study_id=sid, name=name, instrument=instrument,
                           role=row.field("record_role", str), legacy_fields=row.data)
        outcomes[key] = _merge_entity(outcomes[key], incoming) if key in outcomes else incoming
        shared = {
            "outcome_id": oid,
            "timepoint": row.field("outcome_observation_timepoint_raw", str),
            "timepoint_value": row.field("outcome_observation_timepoint_value", _number),
            "timepoint_unit": row.field("outcome_observation_timepoint_unit", _code(TIMEPOINT_UNITS)),
            "analysis_set": merge_field_observation(row.field("analysis_set", str), row.field("analysis_population", str)),
            "derived": bool(row.data.get("derived", False)),
            "derivation": _text(row.data.get("derivation")),
        }
        result_arms = []
        for arm_index, raw in enumerate(row.data.get("arm") or []):
            result_arms.append((row_arm_ids[index, arm_index], row.child(_dict(raw), f"arm:{arm_index}")))
        if not result_arms:
            for role, aid in defaults.items():
                keys = {"value": f"{role}_estimate", "lower": f"{role}_variance_lower",
                        "upper": f"{role}_variance_upper", "n": f"{role}_n"}
                if any(row.data.get(source) is not None for source in keys.values()):
                    child = row.child({key: row.data.get(source) for key, source in keys.items()}, role)
                    child.evidence_by_field = {key: row.evidence_by_field.get(source, []) for key, source in keys.items()}
                    result_arms.append((aid, child))
        for arm_index, (aid, arm) in enumerate(result_arms):
            arm_results.append(ArmResult(
                arm_result_id=_id("arm-result", article_id, index, arm_index), arm_id=aid, **shared,
                value=merge_field_observation(arm.field("value", _number), arm.field("estimate", _number)),
                standard_deviation=arm.field("sd", _number), change_from_baseline=arm.field("change", _number),
                dispersion_lower=arm.field("lower", _number), dispersion_upper=arm.field("upper", _number),
                n=arm.field("n", _integer), event_count=arm.field("event_count", _integer),
                denominator=arm.field("denominator", _integer), raw_value=arm.field("raw_value", str),
                value_kind=arm.field("value_kind", str), source_table_id=_text(row.data.get("table_id")),
                source_row_id=_text(row.data.get("row_id")), legacy_fields={"arm": arm.data, "row": row.data},
            ))

        comp = row.child(_dict(row.data.get("comparison") or {}), "comparison")
        relation = comp.field("relation", str)
        measures = ("outcome_between_group_estimate", "outcome_between_group_lower", "outcome_between_group_upper", "outcome_p_value")
        has_result = any(row.data.get(key) is not None for key in measures) or _text(row.data.get("between_group_measure")) or _text(row.data.get("effect_size_name"))
        if relation.status != FieldStatus.PRESENT and not has_result:
            continue
        def resolve(alias: Any) -> str | None:
            if not _text(alias):
                return None
            if str(alias) not in aliases:
                warnings.append(f"{row.source}: unresolved comparison arm reference {alias}")
            return aliases.get(str(alias))
        active = resolve(comp.data.get("intervention_arm_id"))
        controls = [resolve(alias) for alias in comp.data.get("comparator_arm_ids") or []]
        controls.append(resolve(comp.data.get("control_arm_id")))
        # Only an explicit two-arm relation supports legacy role-based references.
        if relation.value == "intervention_vs_control":
            if not _text(comp.data.get("intervention_arm_id")):
                active = defaults.get("intervention")
            if not comp.data.get("comparator_arm_ids") and not _text(comp.data.get("control_arm_id")):
                controls.append(defaults.get("control"))
        controls = _unique([aid for aid in controls if aid])
        comp_key = (relation.value, active, tuple(controls), comp.data.get("contrast"))
        cid = _id("comparison", sid, comp_key)
        incoming_comp = Comparison(
            comparison_id=cid, study_id=sid, relation=relation,
            arm_ids=_unique(([active] if active else []) + controls),
            intervention_arm_id=active, comparator_arm_ids=controls,
            contrast=comp.field("contrast", str), legacy_fields=comp.data,
        )
        comparisons[comp_key] = _merge_entity(comparisons[comp_key], incoming_comp) if comp_key in comparisons else incoming_comp
        if has_result:
            comparison_results.append(ComparisonResult(
                comparison_result_id=_id("comparison-result", article_id, index), comparison_id=cid, **shared,
                effect_measure=merge_field_observation(row.field("between_group_measure", str), row.field("effect_size_name", str)),
                estimate=row.field("outcome_between_group_estimate", _number),
                confidence_interval_lower=row.field("outcome_between_group_lower", _number),
                confidence_interval_upper=row.field("outcome_between_group_upper", _number),
                p_value=row.field("outcome_p_value", _number), p_value_comparator=row.field("outcome_p_value_comparator", str),
                raw_value=row.field("source_values", lambda values: " | ".join(map(str, values))), legacy_fields=row.data,
            ))

    study = Study(
        study_id=sid, article_id=article_id, design=meta.field("design", str),
        condition=meta.field("disease_name", str), countries=meta.field("country", _strings),
        centre_count=meta.field("centre_count", _integer),
        randomized_n=merge_field_observation(risk.field("total_randomized", _integer), flow.field("randomized_n", _integer)),
        random_sequence_method=risk.field("random_sequence_method", str),
        random_sequence_code=risk.field("random_sequence_class", _code({i: i for i in range(1, 10) if i != 8})),
        allocation_concealment=risk.field("allocation_concealment", str),
        allocation_concealment_code=risk.field("allocation_concealment_class", _code({i: i for i in range(1, 7) if i != 5})),
        participant_blinding=risk.field("participant_blinding", _code(BLINDING)),
        practitioner_blinding=risk.field("practitioner_blinding", _code(BLINDING)),
        outcome_assessor_blinding=risk.field("outcome_assessor_blinding", _code(BLINDING)),
        statistician_blinding=risk.field("statistician_blinding", _code(BLINDING)),
        primary_analysis_set=risk.field("primary_analysis", _code(PRIMARY_ANALYSIS)),
        missing_data_method=risk.field("missing_data_method", _code(MISSING_DATA)),
        arm_ids=list(arms), intervention_ids=[item.intervention_id for item in interventions],
        outcome_ids=[item.outcome_id for item in outcomes.values()],
        legacy_fields={"risk_of_bias": risk.data, "consort_flow": flow.data},
    )
    entities = [article, study, *interventions, *arms.values(), *outcomes.values(), *arm_results,
                *comparisons.values(), *comparison_results]
    id_fields = {Article: "article_id", Study: "study_id", Arm: "arm_id", Intervention: "intervention_id",
                 Outcome: "outcome_id", ArmResult: "arm_result_id", Comparison: "comparison_id",
                 ComparisonResult: "comparison_result_id"}
    for entity in entities:
        for field_id, value in entity:
            if not isinstance(value, CanonicalField):
                continue
            for eid in _unique(value.evidence_ids + [eid for candidate in value.conflict_candidates for eid in candidate.evidence_ids]):
                target = EvidenceTarget(entity_type=type(entity).__name__, entity_id=getattr(entity, id_fields[type(entity)]), field_id=field_id)
                if target not in pool[eid].targets:
                    pool[eid].targets.append(target)
    return ArticleExtraction(
        article=article, studies=[study], interventions=interventions, arms=list(arms.values()),
        outcomes=list(outcomes.values()), arm_results=arm_results, comparisons=list(comparisons.values()),
        comparison_results=comparison_results, evidence=list(pool.values()),
        source_format="legacy_extraction_bundle", source_record_id=article_id,
        parser_backend=_text(data.get("parser_backend")), adapter_warnings=_unique(warnings),
    )


def canonical_json(bundle: BaseModel | Mapping[str, Any], *, indent: int = 2) -> str:
    return legacy_bundle_to_canonical(bundle).model_dump_json(indent=indent)
