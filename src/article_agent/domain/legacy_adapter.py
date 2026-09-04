"""One-way adapter from the legacy ExtractionBundle to canonical entities."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from .models import (
    Arm,
    ArmResult,
    Article,
    ArticleExtraction,
    Comparison,
    ComparisonResult,
    Evidence,
    Intervention,
    Outcome,
    Study,
)


MISSING_MARKERS = {"", "NR", "NA", "N/A", "NOT REPORTED", "NONE", "NULL"}
TIMEPOINT_UNITS = {1: "day", 2: "month", 3: "year", 4: "week", 5: "hour"}
FREQUENCY_UNITS = {1: "day", 2: "week", 3: "hour"}
DURATION_UNITS = {1: "day", 2: "week"}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    raise TypeError("legacy bundle must be a Pydantic model or mapping")


def _reported(value: Any) -> bool:
    return value is not None and str(value).strip().upper() not in MISSING_MARKERS


def _text(value: Any) -> str | None:
    return str(value).strip() if _reported(value) else None


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stable_id(prefix: str, *parts: Any) -> str:
    normalized = "\x1f".join(re.sub(r"\s+", " ", str(part or "").strip()).casefold() for part in parts)
    return f"{prefix}:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _outcome_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    allowed = {
        "primary", "secondary", "safety", "subgroup", "sensitivity",
        "baseline", "administrative", "other",
    }
    return role if role in allowed else "unknown"


def _arm_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    return role if role in {"intervention", "control", "comparator", "other"} else "unknown"


def _comparison_relation(value: Any) -> str:
    relation = str(value or "").strip().lower()
    allowed = {
        "intervention_vs_control", "arm_vs_arm", "multi_arm", "within_arm",
        "overall", "not_applicable", "other",
    }
    return relation if relation in allowed else "unknown"


def _p_comparator(value: Any) -> str:
    comparator = str(value or "").strip()
    return comparator if comparator in {"=", "<", "<=", ">", ">="} else "unknown"


def _value_kind(timepoint_raw: Any, arm_data: Mapping[str, Any]) -> str:
    text = str(timepoint_raw or "").casefold()
    if "baseline" in text:
        return "baseline"
    if "change" in text or arm_data.get("change") is not None:
        return "change"
    if arm_data.get("event_count") is not None:
        return "event"
    if _reported(timepoint_raw):
        return "endpoint"
    return "unknown"


class _EvidencePool:
    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def add_many(
        self,
        items: Any,
        *,
        source_id: str,
        table_id: str | None = None,
        row_id: str | None = None,
    ) -> list[str]:
        evidence_ids: list[str] = []
        for raw in items or []:
            item = _as_dict(raw) if isinstance(raw, BaseModel) else dict(raw)
            quote = _text(item.get("quote"))
            if not quote:
                continue
            source = str(item.get("source") or "other").lower()
            source_type = {
                "crossref": "bibliographic",
                "markdown": "markdown",
                "table": "table",
                "figure": "figure",
            }.get(source, "other")
            support_type = "derived" if str(item.get("support_type") or "").lower() == "derived" else "direct"
            derivation = _text(item.get("derivation"))
            if support_type == "derived" and not derivation:
                support_type = "direct"
            evidence_id = _stable_id(
                "evidence", source_id, item.get("field_id"), quote, item.get("page"), table_id, row_id
            )
            if evidence_id not in self._items:
                self._items[evidence_id] = Evidence(
                    evidence_id=evidence_id,
                    field_paths=[str(item["field_id"])] if _reported(item.get("field_id")) else [],
                    quote=quote,
                    source_type=source_type,
                    source_id=source_id,
                    page=_int(item.get("page")),
                    table_id=_text(table_id),
                    row_id=_text(row_id),
                    support_type=support_type,
                    derivation=derivation,
                    legacy_fields=item,
                )
            evidence_ids.append(evidence_id)
        return _unique(evidence_ids)

    def add_source_text(
        self,
        quote: Any,
        *,
        source_id: str,
        table_id: Any,
        row_id: Any,
    ) -> list[str]:
        text = _text(quote)
        if not text:
            return []
        source_type = "table" if _reported(table_id) else "markdown"
        evidence_id = _stable_id("evidence", source_id, text, table_id, row_id)
        if evidence_id not in self._items:
            self._items[evidence_id] = Evidence(
                evidence_id=evidence_id,
                quote=text,
                source_type=source_type,
                source_id=source_id,
                table_id=_text(table_id),
                row_id=_text(row_id),
            )
        return [evidence_id]

    @property
    def values(self) -> list[Evidence]:
        return list(self._items.values())


def legacy_bundle_to_canonical(bundle: BaseModel | Mapping[str, Any]) -> ArticleExtraction:
    """Project a legacy bundle into the canonical graph without mutating it.

    The adapter never reads Gold and never fills a missing clinical value from
    another row.  Any lossy or ambiguous projection is retained under
    ``legacy_fields`` and surfaced in ``adapter_warnings``.
    """

    data = _as_dict(bundle)
    article_id = _text(data.get("article_id"))
    if not article_id:
        raise ValueError("legacy bundle has no article_id")
    metadata = dict(data.get("metadata") or {})
    acupuncture = dict(data.get("acupuncture") or {})
    risk = dict(data.get("risk_of_bias") or {})
    outcome_rows = list((data.get("outcomes") or {}).get("outcomes") or [])
    flow = dict(data.get("consort_flow") or {})
    warnings = list(data.get("cross_check_issues") or [])
    pool = _EvidencePool()

    metadata_evidence = pool.add_many(metadata.get("evidence"), source_id="legacy:metadata")
    acupuncture_evidence = pool.add_many(acupuncture.get("evidence"), source_id="legacy:acupuncture")
    risk_evidence = pool.add_many(risk.get("evidence"), source_id="legacy:risk_of_bias")
    flow_evidence = pool.add_many(flow.get("evidence"), source_id="legacy:consort_flow")

    article = Article(
        article_id=article_id,
        title=_text(metadata.get("title")),
        publication_year=_int(metadata.get("publication_year")),
        journal=_text(metadata.get("journal")),
        language=_text(metadata.get("language")),
        authors=[value for value in [_text(metadata.get("first_author"))] if value],
        correspondence=[value for value in [_text(metadata.get("author_contact"))] if value],
        evidence_ids=metadata_evidence,
        legacy_fields={key: value for key, value in metadata.items() if key != "evidence"},
    )
    study_id = f"{article_id}:study-1"

    interventions: list[Intervention] = []
    intervention_name = _text(metadata.get("intervention"))
    control_name = _text(metadata.get("control"))
    active_intervention_id: str | None = None
    control_intervention_id: str | None = None
    if intervention_name:
        active_intervention_id = f"{study_id}:intervention-1"
        interventions.append(
            Intervention(
                intervention_id=active_intervention_id,
                study_id=study_id,
                name=intervention_name,
                kind="acupuncture_family",
                frequency_raw=_text(acupuncture.get("treatment_frequency_raw")),
                frequency_value=_float(acupuncture.get("treatment_frequency_value")),
                frequency_unit=FREQUENCY_UNITS.get(_int(acupuncture.get("treatment_frequency_unit"))),
                duration_raw=_text(acupuncture.get("treatment_duration_raw")),
                duration_value=_float(acupuncture.get("treatment_duration_value")),
                duration_unit=DURATION_UNITS.get(_int(acupuncture.get("treatment_duration_unit"))),
                total_sessions=_int(acupuncture.get("total_sessions")),
                evidence_ids=_unique(metadata_evidence + acupuncture_evidence),
                legacy_fields={key: value for key, value in acupuncture.items() if key != "evidence"},
            )
        )
    if control_name:
        control_intervention_id = f"{study_id}:intervention-control-1"
        interventions.append(
            Intervention(
                intervention_id=control_intervention_id,
                study_id=study_id,
                name=control_name,
                evidence_ids=metadata_evidence,
                legacy_fields={
                    "control_type_transformed": acupuncture.get("control_type_transformed"),
                    "control_type_components": acupuncture.get("control_type_components", []),
                },
            )
        )

    arms_by_id: dict[str, Arm] = {}
    legacy_arm_aliases: dict[str, str] = {}

    def ensure_arm(
        *,
        legacy_id: Any = None,
        label: Any = None,
        role: Any = None,
        randomized_n: Any = None,
        received_n: Any = None,
        analyzed_n: Any = None,
        dropout_n: Any = None,
        evidence_ids: list[str] | None = None,
        legacy_fields: dict[str, Any] | None = None,
    ) -> str:
        canonical_role = _arm_role(role)
        reported_legacy_id = _text(legacy_id)
        reported_label = _text(label)
        if reported_legacy_id and reported_legacy_id in legacy_arm_aliases:
            return legacy_arm_aliases[reported_legacy_id]
        for existing_id, existing in arms_by_id.items():
            same_label = (
                reported_label is not None
                and existing.label is not None
                and reported_label.casefold() == existing.label.casefold()
            )
            if not same_label:
                continue
            updates = {
                "randomized_n": existing.randomized_n if existing.randomized_n is not None else _int(randomized_n),
                "received_n": existing.received_n if existing.received_n is not None else _int(received_n),
                "analyzed_n": existing.analyzed_n if existing.analyzed_n is not None else _int(analyzed_n),
                "dropout_n": existing.dropout_n if existing.dropout_n is not None else _int(dropout_n),
                "evidence_ids": _unique(existing.evidence_ids + (evidence_ids or [])),
            }
            arms_by_id[existing_id] = existing.model_copy(update=updates)
            if reported_legacy_id:
                legacy_arm_aliases[reported_legacy_id] = existing_id
            return existing_id
        identity = reported_legacy_id or reported_label or canonical_role
        arm_id = f"{study_id}:arm:{re.sub(r'[^a-z0-9]+', '-', identity.casefold()).strip('-')}" if identity else _stable_id("arm", study_id, len(arms_by_id))
        if arm_id in arms_by_id:
            arm = arms_by_id[arm_id]
            if reported_label and arm.label and reported_label != arm.label:
                warnings.append(f"legacy arm {reported_legacy_id or arm_id} has conflicting labels")
            return arm_id
        linked_interventions = []
        if canonical_role == "intervention" and active_intervention_id:
            linked_interventions.append(active_intervention_id)
        if canonical_role in {"control", "comparator"} and control_intervention_id:
            linked_interventions.append(control_intervention_id)
        arms_by_id[arm_id] = Arm(
            arm_id=arm_id,
            study_id=study_id,
            label=reported_label,
            role=canonical_role,
            intervention_ids=linked_interventions,
            randomized_n=_int(randomized_n),
            received_n=_int(received_n),
            analyzed_n=_int(analyzed_n),
            dropout_n=_int(dropout_n),
            evidence_ids=_unique(evidence_ids or []),
            legacy_fields=legacy_fields or {},
        )
        if reported_legacy_id:
            legacy_arm_aliases[reported_legacy_id] = arm_id
        return arm_id

    intervention_n = risk.get("randomized_sample_intervention_raw")
    control_n = risk.get("randomized_sample_control_raw")
    default_intervention_arm_id: str | None = None
    default_control_arm_id: str | None = None
    if intervention_name or intervention_n is not None:
        default_intervention_arm_id = ensure_arm(
            legacy_id="intervention",
            label=intervention_name,
            role="intervention",
            randomized_n=intervention_n,
            evidence_ids=_unique(metadata_evidence + risk_evidence + flow_evidence),
        )
    if control_name or control_n is not None:
        default_control_arm_id = ensure_arm(
            legacy_id="control",
            label=control_name,
            role="control",
            randomized_n=control_n,
            evidence_ids=_unique(metadata_evidence + risk_evidence + flow_evidence),
        )

    for flow_index, flow_arm_value in enumerate(flow.get("arms") or []):
        flow_arm = dict(flow_arm_value)
        ensure_arm(
            legacy_id=f"flow-{flow_index + 1}",
            label=flow_arm.get("arm_name"),
            randomized_n=flow_arm.get("randomized_n"),
            received_n=flow_arm.get("received_n"),
            analyzed_n=flow_arm.get("analyzed_n"),
            dropout_n=flow_arm.get("dropout_n"),
            evidence_ids=flow_evidence,
            legacy_fields=flow_arm,
        )

    for row_index, row_value in enumerate(outcome_rows):
        row = _as_dict(row_value) if isinstance(row_value, BaseModel) else dict(row_value)
        row_evidence = pool.add_many(
            row.get("evidence"),
            source_id=f"legacy:outcomes:{row_index}",
            table_id=_text(row.get("table_id")),
            row_id=_text(row.get("row_id")),
        )
        row_evidence += pool.add_source_text(
            row.get("source_evidence"),
            source_id=f"legacy:outcomes:{row_index}:source",
            table_id=row.get("table_id"),
            row_id=row.get("row_id"),
        )
        for arm_value in row.get("arm") or []:
            arm = dict(arm_value)
            ensure_arm(
                legacy_id=arm.get("arm_id"),
                label=arm.get("arm_label"),
                role=arm.get("role"),
                randomized_n=arm.get("n"),
                evidence_ids=row_evidence,
                legacy_fields=arm,
            )

    outcomes_by_key: dict[tuple[str, str], Outcome] = {}
    arm_results: list[ArmResult] = []
    comparisons_by_key: dict[tuple[Any, ...], Comparison] = {}
    comparison_results: list[ComparisonResult] = []

    for row_index, row_value in enumerate(outcome_rows):
        row = _as_dict(row_value) if isinstance(row_value, BaseModel) else dict(row_value)
        name = _text(row.get("outcome_name")) or "Unspecified outcome"
        instrument = _text(row.get("measurement_instrument"))
        outcome_key = (name.casefold(), (instrument or "").casefold())
        table_id = _text(row.get("table_id"))
        row_id = _text(row.get("row_id"))
        row_evidence = pool.add_many(
            row.get("evidence"),
            source_id=f"legacy:outcomes:{row_index}",
            table_id=table_id,
            row_id=row_id,
        )
        row_evidence += pool.add_source_text(
            row.get("source_evidence"),
            source_id=f"legacy:outcomes:{row_index}:source",
            table_id=table_id,
            row_id=row_id,
        )
        row_evidence = _unique(row_evidence)
        if outcome_key not in outcomes_by_key:
            outcome_id = _stable_id("outcome", study_id, *outcome_key)
            outcomes_by_key[outcome_key] = Outcome(
                outcome_id=outcome_id,
                study_id=study_id,
                name=name,
                instrument=instrument,
                role=_outcome_role(row.get("record_role")),
                evidence_ids=row_evidence,
                legacy_fields={
                    "statistic_type": row.get("statistic_type"),
                    "record_role": row.get("record_role"),
                },
            )
        else:
            existing = outcomes_by_key[outcome_key]
            outcomes_by_key[outcome_key] = existing.model_copy(
                update={"evidence_ids": _unique(existing.evidence_ids + row_evidence)}
            )
        outcome_id = outcomes_by_key[outcome_key].outcome_id

        nested_arms = list(row.get("arm") or [])
        if nested_arms:
            for arm_index, arm_value in enumerate(nested_arms):
                arm = dict(arm_value)
                legacy_arm_id = _text(arm.get("arm_id"))
                arm_id = legacy_arm_aliases.get(legacy_arm_id or "") or ensure_arm(
                    legacy_id=legacy_arm_id,
                    label=arm.get("arm_label"),
                    role=arm.get("role"),
                    randomized_n=arm.get("n"),
                    evidence_ids=row_evidence,
                    legacy_fields=arm,
                )
                arm_results.append(
                    ArmResult(
                        arm_result_id=_stable_id("arm-result", article_id, row_index, arm_index, arm_id),
                        outcome_id=outcome_id,
                        arm_id=arm_id,
                        timepoint_raw=_text(row.get("outcome_observation_timepoint_raw")),
                        timepoint_value=_float(row.get("outcome_observation_timepoint_value")),
                        timepoint_unit=TIMEPOINT_UNITS.get(_int(row.get("outcome_observation_timepoint_unit"))),
                        analysis_set=_text(row.get("analysis_set")) or _text(row.get("analysis_population")),
                        value_kind=_value_kind(row.get("outcome_observation_timepoint_raw"), arm),
                        value=_float(arm.get("value")) if arm.get("value") is not None else _float(arm.get("estimate")),
                        standard_deviation=_float(arm.get("sd")),
                        change_from_baseline=_float(arm.get("change")),
                        dispersion_lower=_float(arm.get("lower")),
                        dispersion_upper=_float(arm.get("upper")),
                        n=_int(arm.get("n")),
                        event_count=_int(arm.get("event_count")),
                        source_table_id=table_id,
                        source_row_id=row_id,
                        evidence_ids=row_evidence,
                        derived=bool(row.get("derived", False)),
                        derivation=_text(row.get("derivation")),
                        legacy_fields=arm,
                    )
                )
        else:
            scalar_arms = [
                (
                    default_intervention_arm_id,
                    "intervention",
                    row.get("intervention_estimate"),
                    row.get("intervention_variance_lower"),
                    row.get("intervention_variance_upper"),
                    row.get("intervention_n"),
                ),
                (
                    default_control_arm_id,
                    "control",
                    row.get("control_estimate"),
                    row.get("control_variance_lower"),
                    row.get("control_variance_upper"),
                    row.get("control_n"),
                ),
            ]
            for arm_id, role, value, lower, upper, n in scalar_arms:
                if arm_id and any(item is not None for item in (value, lower, upper, n)):
                    legacy_fields = {
                        "role": role,
                        "estimate": value,
                        "variance_lower": lower,
                        "variance_upper": upper,
                        "n": n,
                    }
                    arm_results.append(
                        ArmResult(
                            arm_result_id=_stable_id("arm-result", article_id, row_index, role),
                            outcome_id=outcome_id,
                            arm_id=arm_id,
                            timepoint_raw=_text(row.get("outcome_observation_timepoint_raw")),
                            timepoint_value=_float(row.get("outcome_observation_timepoint_value")),
                            timepoint_unit=TIMEPOINT_UNITS.get(_int(row.get("outcome_observation_timepoint_unit"))),
                            analysis_set=_text(row.get("analysis_set")) or _text(row.get("analysis_population")),
                            value_kind=_value_kind(row.get("outcome_observation_timepoint_raw"), legacy_fields),
                            value=_float(value),
                            dispersion_lower=_float(lower),
                            dispersion_upper=_float(upper),
                            n=_int(n),
                            source_table_id=table_id,
                            source_row_id=row_id,
                            evidence_ids=row_evidence,
                            derived=bool(row.get("derived", False)),
                            derivation=_text(row.get("derivation")),
                            legacy_fields=legacy_fields,
                        )
                    )

        comparison_data = dict(row.get("comparison") or {})
        relation = _comparison_relation(comparison_data.get("relation"))
        intervention_alias = _text(comparison_data.get("intervention_arm_id"))
        control_alias = _text(comparison_data.get("control_arm_id"))
        intervention_arm_id = legacy_arm_aliases.get(intervention_alias or "") or default_intervention_arm_id
        comparator_arm_ids = [
            legacy_arm_aliases.get(str(item), str(item))
            for item in comparison_data.get("comparator_arm_ids") or []
            if _reported(item)
        ]
        if control_alias:
            mapped_control = legacy_arm_aliases.get(control_alias) or default_control_arm_id
            if mapped_control:
                comparator_arm_ids.append(mapped_control)
        elif default_control_arm_id and relation == "intervention_vs_control":
            comparator_arm_ids.append(default_control_arm_id)
        comparator_arm_ids = _unique([item for item in comparator_arm_ids if item in arms_by_id])
        comparison_arm_ids = _unique(
            [item for item in [intervention_arm_id, *comparator_arm_ids] if item in arms_by_id]
        )
        has_comparison_result = any(
            row.get(field) is not None
            for field in (
                "outcome_between_group_estimate",
                "outcome_between_group_lower",
                "outcome_between_group_upper",
                "outcome_p_value",
            )
        ) or _reported(row.get("between_group_measure")) or _reported(row.get("effect_size_name"))
        if relation != "unknown" or has_comparison_result:
            comparison_key = (
                relation,
                tuple(comparison_arm_ids),
                _text(comparison_data.get("contrast")),
            )
            if comparison_key not in comparisons_by_key:
                comparison_id = _stable_id(
                    "comparison", study_id, len(comparisons_by_key), *comparison_key
                )
                comparisons_by_key[comparison_key] = Comparison(
                    comparison_id=comparison_id,
                    study_id=study_id,
                    relation=relation,
                    arm_ids=comparison_arm_ids,
                    intervention_arm_id=intervention_arm_id if intervention_arm_id in arms_by_id else None,
                    comparator_arm_ids=comparator_arm_ids,
                    contrast=_text(comparison_data.get("contrast")),
                    evidence_ids=row_evidence,
                    legacy_fields=comparison_data,
                )
            comparison = comparisons_by_key[comparison_key]
            if has_comparison_result:
                raw_values = row.get("source_values") or []
                comparison_results.append(
                    ComparisonResult(
                        comparison_result_id=_stable_id("comparison-result", article_id, row_index, comparison.comparison_id),
                        comparison_id=comparison.comparison_id,
                        outcome_id=outcome_id,
                        timepoint_raw=_text(row.get("outcome_observation_timepoint_raw")),
                        timepoint_value=_float(row.get("outcome_observation_timepoint_value")),
                        timepoint_unit=TIMEPOINT_UNITS.get(_int(row.get("outcome_observation_timepoint_unit"))),
                        analysis_set=_text(row.get("analysis_set")) or _text(row.get("analysis_population")),
                        effect_measure=_text(row.get("between_group_measure")) or _text(row.get("effect_size_name")),
                        estimate=_float(row.get("outcome_between_group_estimate")),
                        confidence_interval_lower=_float(row.get("outcome_between_group_lower")),
                        confidence_interval_upper=_float(row.get("outcome_between_group_upper")),
                        p_value=_float(row.get("outcome_p_value")),
                        p_value_comparator=_p_comparator(row.get("outcome_p_value_comparator")),
                        raw_value=" | ".join(str(item) for item in raw_values) if raw_values else None,
                        evidence_ids=row_evidence,
                        derived=bool(row.get("derived", False)),
                        derivation=_text(row.get("derivation")),
                        legacy_fields={
                            key: row.get(key)
                            for key in (
                                "between_group_measure", "effect_size_name",
                                "outcome_between_group_estimate", "outcome_between_group_lower",
                                "outcome_between_group_upper", "outcome_p_value",
                                "outcome_p_value_comparator", "p_value_cells",
                            )
                        },
                    )
                )

    outcomes = list(outcomes_by_key.values())
    analysis_sets = _unique(
        [
            value
            for row in outcome_rows
            for value in (_text(row.get("analysis_set")), _text(row.get("analysis_population")))
            if value
        ]
    )
    total_randomized = _int(risk.get("total_randomized")) or _int(flow.get("randomized_n"))
    study = Study(
        study_id=study_id,
        article_id=article_id,
        condition=_text(metadata.get("disease_name")),
        countries=[value for value in [_text(metadata.get("country"))] if value],
        randomized_n=total_randomized,
        analysis_sets=analysis_sets,
        arm_ids=list(arms_by_id),
        intervention_ids=[item.intervention_id for item in interventions],
        outcome_ids=[item.outcome_id for item in outcomes],
        evidence_ids=_unique(metadata_evidence + risk_evidence + flow_evidence),
        legacy_fields={key: value for key, value in risk.items() if key != "evidence"},
    )

    return ArticleExtraction(
        source_format="legacy_extraction_bundle",
        source_record_id=article_id,
        parser_backend=_text(data.get("parser_backend")),
        article=article,
        studies=[study],
        interventions=interventions,
        arms=list(arms_by_id.values()),
        outcomes=outcomes,
        arm_results=arm_results,
        comparisons=list(comparisons_by_key.values()),
        comparison_results=comparison_results,
        evidence=pool.values,
        adapter_warnings=_unique([str(item) for item in warnings if _reported(item)]),
    )


def canonical_json(bundle: BaseModel | Mapping[str, Any], *, indent: int = 2) -> str:
    """Convenience serializer used by migrations and command-line tooling."""

    canonical = legacy_bundle_to_canonical(bundle)
    return json.dumps(canonical.model_dump(mode="json"), ensure_ascii=False, indent=indent)
