from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import ArmRecord, EvidenceSpan, FieldValue, RunState


EVALUATION_HEADERS = [
    "study_id",
    "sheet_name",
    "entity_id",
    "field_name",
    "priority",
    "agent_value",
    "gold_value",
    "agent_code",
    "gold_code",
    "score",
    "error_type",
    "evidence_score",
    "is_critical_error",
    "reviewer",
    "review_time_sec",
    "notes",
]

FOOTER_PATTERNS = [
    "downloaded from",
    "group.bmj.com",
    "published by",
    "copyright",
    "all rights reserved",
    "for personal use only",
]

P0_FIELDS = {
    ("01_Study", "eligibility_status"),
    ("01_Study", "disease_name"),
    ("01_Study", "study_design"),
    ("01_Study", "randomized_n"),
    ("01_Study", "primary_outcome"),
    ("02_Arms", "arm_name"),
    ("02_Arms", "arm_role"),
    ("02_Arms", "intervention_category"),
    ("02_Arms", "sample_randomized"),
    ("03_Comparisons", "intervention_arm_id"),
    ("03_Comparisons", "control_arm_id"),
    ("03_Comparisons", "comparison_type_code"),
    ("04_Methods", "random_sequence_code"),
    ("04_Methods", "allocation_concealment_code"),
    ("04_Methods", "participant_blinding_code"),
    ("04_Methods", "outcome_assessor_blinding_code"),
    ("06_Outcomes", "outcome_name"),
    ("06_Outcomes", "is_primary_outcome"),
    ("06_Outcomes", "primary_timepoint_value"),
    ("07_Results", "intervention_n"),
    ("07_Results", "control_n"),
    ("07_Results", "between_group_effect"),
    ("07_Results", "p_value"),
}

P1_FIELDS = {
    ("01_Study", "country"),
    ("01_Study", "setting"),
    ("01_Study", "center_count"),
    ("01_Study", "funding"),
    ("01_Study", "conflict_of_interest"),
    ("02_Arms", "sample_started"),
    ("02_Arms", "sample_analyzed_primary"),
    ("02_Arms", "dropout_n"),
    ("02_Arms", "usual_care_components"),
    ("04_Methods", "primary_analysis_set"),
    ("04_Methods", "missing_data_method"),
    ("05_Acupuncture", "acupuncture_modality"),
    ("05_Acupuncture", "stimulation_type"),
    ("05_Acupuncture", "point_selection_scheme"),
    ("05_Acupuncture", "acupoints_common"),
    ("05_Acupuncture", "frequency_per_week"),
    ("05_Acupuncture", "treatment_duration_weeks"),
    ("05_Acupuncture", "total_sessions"),
    ("05_Acupuncture", "retention_time_min"),
    ("05_Acupuncture", "deqi_reported"),
    ("05_Acupuncture", "practitioner_qualification"),
}


@dataclass(frozen=True)
class SchemaCheck:
    rule_id: str
    passed: bool
    severity: str
    message: str


def field_priority(sheet_name: str, field_name: str) -> str:
    key = (sheet_name, field_name)
    if key in P0_FIELDS:
        return "P0"
    if key in P1_FIELDS:
        return "P1"
    return "P2"


def is_nr(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().upper() in {"", "NR", "NA", "N/A", "NONE"}


def evidence_has_footer_error(text: str) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in FOOTER_PATTERNS)


def _numeric(value: Any) -> float | None:
    if is_nr(value):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _field_evidence_score(field: FieldValue) -> float | str:
    if is_nr(field.value):
        return "manual"
    if not field.evidence:
        return 0.0
    best = 0.0
    for ev in field.evidence:
        if evidence_has_footer_error(ev.evidence_text):
            best = max(best, 0.0)
            continue
        if len(ev.evidence_text.strip()) < 20:
            best = max(best, 0.5)
            continue
        best = max(best, 1.0)
    return best


def _study_field_rows(state: RunState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for study in state.studies:
        for field_name, field in study:
            if not isinstance(field, FieldValue):
                continue
            evidence_score = _field_evidence_score(field)
            error_type = ""
            critical = False
            if evidence_score == 0.0:
                error_type = "evidence_footer_or_missing"
                critical = field_priority("01_Study", field_name) == "P0" or field_name == "title"
            rows.append({
                "study_id": study.study_id,
                "sheet_name": "01_Study",
                "entity_id": study.study_id,
                "field_name": field_name,
                "priority": field_priority("01_Study", field_name),
                "agent_value": field.value,
                "gold_value": "",
                "agent_code": field.code,
                "gold_code": "",
                "score": "",
                "error_type": error_type,
                "evidence_score": evidence_score,
                "is_critical_error": critical,
                "reviewer": "",
                "review_time_sec": "",
                "notes": "Fill score manually against gold: 0, 0.5, or 1.",
            })
    return rows


def _model_rows(study_id: str, sheet_name: str, entity_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, value in data.items():
        if field_name == "study_id":
            continue
        rows.append({
            "study_id": study_id,
            "sheet_name": sheet_name,
            "entity_id": entity_id,
            "field_name": field_name,
            "priority": field_priority(sheet_name, field_name),
            "agent_value": value,
            "gold_value": "",
            "agent_code": "",
            "gold_code": "",
            "score": "",
            "error_type": "",
            "evidence_score": "manual",
            "is_critical_error": False,
            "reviewer": "",
            "review_time_sec": "",
            "notes": "Manual gold scoring required.",
        })
    return rows


def build_evaluation_rows(state: RunState) -> list[dict[str, Any]]:
    rows = _study_field_rows(state)
    for arm in state.arms:
        rows.extend(_model_rows(arm.study_id, "02_Arms", arm.arm_id, arm.model_dump()))
    for comp in state.comparisons:
        rows.extend(_model_rows(comp.study_id, "03_Comparisons", comp.comparison_id, comp.model_dump()))
    for method in state.methods:
        rows.extend(_model_rows(str(method.get("study_id", "")), "04_Methods", str(method.get("study_id", "")), method))
    for acu in state.acupuncture:
        entity_id = str(acu.get("arm_id") or acu.get("study_id", ""))
        rows.extend(_model_rows(str(acu.get("study_id", "")), "05_Acupuncture", entity_id, acu))
    for outcome in state.outcomes:
        rows.extend(_model_rows(outcome.study_id, "06_Outcomes", outcome.outcome_id, outcome.model_dump()))
    return rows


def run_schema_checks(state: RunState) -> list[SchemaCheck]:
    checks: list[SchemaCheck] = []
    arm_ids = {arm.arm_id for arm in state.arms}
    outcome_ids = {outcome.outcome_id for outcome in state.outcomes}

    for comp in state.comparisons:
        checks.append(SchemaCheck(
            "comparison_intervention_arm_exists",
            comp.intervention_arm_id in arm_ids,
            "error",
            f"{comp.comparison_id}.intervention_arm_id -> {comp.intervention_arm_id}",
        ))
        checks.append(SchemaCheck(
            "comparison_control_arm_exists",
            comp.control_arm_id in arm_ids,
            "error",
            f"{comp.comparison_id}.control_arm_id -> {comp.control_arm_id}",
        ))

    for study in state.studies:
        total = _numeric(study.randomized_n.value)
        group_values = [_numeric(arm.sample_randomized) for arm in state.arms if arm.study_id == study.study_id]
        group_values = [v for v in group_values if v is not None]
        if total is not None and group_values:
            checks.append(SchemaCheck(
                "sample_randomized_sum_matches_total",
                abs(sum(group_values) - total) <= 1,
                "error",
                f"{study.study_id}: arms sum={sum(group_values):g}, total={total:g}",
            ))
        else:
            checks.append(SchemaCheck(
                "sample_randomized_sum_matches_total",
                True,
                "info",
                f"{study.study_id}: skipped because total or arm counts are NR.",
            ))

    for acu in state.acupuncture:
        frequency = _numeric(acu.get("frequency_per_week"))
        duration = _numeric(acu.get("treatment_duration_weeks"))
        total_sessions = _numeric(acu.get("total_sessions"))
        if frequency is not None and duration is not None and total_sessions is not None:
            checks.append(SchemaCheck(
                "frequency_duration_matches_total_sessions",
                abs(frequency * duration - total_sessions) <= 2,
                "warning",
                f"{acu.get('study_id')}: {frequency:g} x {duration:g} vs {total_sessions:g}",
            ))

    arm_by_id: dict[str, ArmRecord] = {arm.arm_id: arm for arm in state.arms}
    for comp in state.comparisons:
        control = arm_by_id.get(comp.control_arm_id)
        if control and str(comp.comparison_type_label).lower() in {"sham", "placebo", "sham/placebo"}:
            checks.append(SchemaCheck(
                "sham_comparison_control_not_usual_care_alone",
                "usual care" not in str(control.intervention_category).lower() or "sham" in str(control.intervention_category).lower(),
                "error",
                f"{comp.comparison_id}: control category={control.intervention_category}",
            ))

    has_primary_outcome = any(str(out.is_primary_outcome).lower() == "true" for out in state.outcomes)
    checks.append(SchemaCheck(
        "primary_outcome_has_result_record",
        not has_primary_outcome,
        "error",
        "07_Results is not implemented yet; primary outcome result row is absent.",
    ))

    footer_errors = [ev.evidence_id for ev in state.evidence if evidence_has_footer_error(ev.evidence_text)]
    checks.append(SchemaCheck(
        "evidence_not_footer_or_header",
        len(footer_errors) == 0,
        "error",
        f"footer/header-like evidence rows: {', '.join(footer_errors[:5]) if footer_errors else 'none'}",
    ))

    dangling_outcome_refs = [out.outcome_id for out in state.outcomes if out.outcome_id not in outcome_ids]
    checks.append(SchemaCheck(
        "outcome_ids_unique_and_available",
        len(dangling_outcome_refs) == 0,
        "error",
        "Outcome IDs are available for result linking.",
    ))
    return checks


def compute_evaluation_summary(state: RunState, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows if rows is not None else build_evaluation_rows(state)
    checks = run_schema_checks(state)
    scoring_rows = [row for row in rows if row["priority"] in {"P0", "P1", "P2"}]
    priority_counts = {
        priority: sum(1 for row in scoring_rows if row["priority"] == priority)
        for priority in ["P0", "P1", "P2"]
    }
    evidence_scores = [
        row["evidence_score"]
        for row in scoring_rows
        if isinstance(row.get("evidence_score"), (int, float))
    ]
    supported = sum(1 for score in evidence_scores if score >= 1)
    high_conf = [ev for ev in state.evidence if ev.confidence >= 0.8]
    high_conf_footer = [ev for ev in high_conf if evidence_has_footer_error(ev.evidence_text)]
    checks_for_rate = [check for check in checks if check.severity in {"error", "warning"}]
    passed_checks = sum(1 for check in checks_for_rate if check.passed)
    review_items = len(state.review)
    filled_fields = sum(1 for row in scoring_rows if not is_nr(row.get("agent_value")))

    return {
        "metric_design": {
            "categories": ["field_accuracy", "evidence_reliability", "structural_consistency", "manual_review_cost"],
            "field_scores": "Manual gold scoring uses 0 / 0.5 / 1 per row in the Evaluation sheet.",
            "agent_score_formula": "0.35*P0_F1 + 0.20*P1_F1 + 0.15*evidence_support_rate + 0.10*numeric_unit_accuracy + 0.10*schema_pass_rate + 0.10*manual_review_efficiency",
        },
        "automatic_metrics": {
            "evaluation_rows": len(rows),
            "priority_counts": priority_counts,
            "filled_field_count": filled_fields,
            "evidence_support_proxy": supported / len(evidence_scores) if evidence_scores else None,
            "footer_header_evidence_errors": len([ev for ev in state.evidence if evidence_has_footer_error(ev.evidence_text)]),
            "high_confidence_footer_error_rate": len(high_conf_footer) / len(high_conf) if high_conf else None,
            "schema_pass_rate": passed_checks / len(checks_for_rate) if checks_for_rate else 1.0,
            "needs_review_n": review_items,
            "review_items_per_article": review_items / len(state.studies) if state.studies else 0,
        },
        "schema_checks": [check.__dict__ for check in checks],
        "manual_metrics_required": [
            "P0/P1/P2 accuracy and F1",
            "field recall",
            "non-NR precision",
            "wrong NR rate",
            "hallucination rate",
            "evidence support rate from reviewer scoring",
            "review_time_min",
            "fields_corrected_n",
            "critical_errors_n",
            "high_confidence_wrong_n",
            "article_pass",
        ],
        "article_pass_rule": {
            "requirements": [
                "P0 field accuracy >= 95%",
                "no critical error",
                "primary outcome, comparison, and primary result have verifiable evidence",
                "schema pass = 100%",
            ],
            "critical_errors": [
                "wrong inclusion/exclusion decision",
                "wrong disease",
                "wrong study design",
                "intervention/control reversal",
                "wrong primary outcome or primary timepoint",
                "seriously wrong sample size",
                "wrong main result direction",
                "title or evidence taken from footer/header",
            ],
        },
    }


def write_evaluation_summary(path: Path, state: RunState, rows: list[dict[str, Any]] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = compute_evaluation_summary(state, rows)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
