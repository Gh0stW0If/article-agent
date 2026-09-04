from __future__ import annotations

import json
import re
from typing import Any

from .api_extract import _compact_context
from .extract import all_text, first_match
from .models import OpenAICompatibleClient
from .schemas import ArmRecord, ParsedDocument, StudyRecord


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _int_or_nr(value: Any) -> int | str:
    if value in (None, "", "NR"):
        return "NR"
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else "NR"


def _has_usual_pharmacological(text: str) -> bool:
    low = text.lower()
    return "pharmacological treatment" in low or "usual care" in low or "standard care" in low


def _category_for_arm(name: str, components: str) -> str:
    low = f"{name} {components}".lower()
    if "sham" in low:
        return "sham_acupuncture"
    if "electroacupuncture" in low:
        return "electroacupuncture"
    if "acupuncture" in low:
        return "acupuncture"
    if "usual" in low or "standard" in low or "pharmacological" in low:
        return "usual_care"
    if "wait" in low:
        return "waiting_list"
    return "NR"


def _is_acupuncture_arm(name: str, components: str) -> bool:
    low = f"{name} {components}".lower()
    return "acupuncture" in low and "sham" not in low


def _normalize_components(value: str, text: str) -> str:
    value = _clean(value)
    if value in ("", "NR"):
        return "NR"
    if _has_usual_pharmacological(text) and "pharmacological treatment" not in value.lower():
        value = f"{value} + usual pharmacological treatment"
    return value


def _extract_group_names(text: str, study: StudyRecord) -> tuple[str, str]:
    intervention = _clean(study.intervention_name.value)
    control = _clean(study.control_name.value)
    m = re.search(
        r"actual intervention group\s*\(([^)]*acupuncture[^)]*)\).*?sham intervention(?: group)?\s*\(([^)]*sham acupuncture[^)]*)\)",
        text,
        flags=re.I | re.S,
    )
    if m:
        intervention = m.group(1)
        control = m.group(2)
    else:
        m = re.search(r"(?:individualised|individualized) acupuncture[^.]{0,80}?\bIA\b", text, flags=re.I)
        if m:
            intervention = "individualised acupuncture"
        m = re.search(r"sham acupuncture[^.]{0,80}?\bSA\b", text, flags=re.I)
        if m:
            control = "sham acupuncture"
    return _normalize_components(intervention, text), _normalize_components(control, text)


def _extract_arm_samples(text: str) -> dict[str, Any]:
    total_randomized = _int_or_nr(
        first_match(r"(?:of|the)\s+(\d{2,4})\s+participants\s+(?:included|randomised|randomized)", text)
        or first_match(r"(\d{2,4})\s+participants\s+(?:included|randomised|randomized)", text)
        or first_match(r"A total of\s+(\d{2,4})\s+participants", text)
    )
    ia_started = "NR"
    sa_started = "NR"
    m = re.search(r"study comprised\s+(\d{1,4})\s+participants\s+in\s+the\s+IA\s+group[^.;]{0,260}?\b(\d{1,4})\s+in\s+the\s+SA\s+group", text, flags=re.I | re.S)
    if m:
        ia_started, sa_started = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d{1,4})\s+participants\s+in\s+the\s+IA\s+group[^.;]{0,260}?\b(\d{1,4})\s+in\s+the\s+SA\s+group", text, flags=re.I | re.S)
        if m:
            ia_started, sa_started = int(m.group(1)), int(m.group(2))

    per_arm_randomized: int | str = "NR"
    if isinstance(total_randomized, int):
        per_arm_randomized = total_randomized // 2 if total_randomized % 2 == 0 else "NR"

    intervention_dropout: int | str = "NR"
    control_dropout: int | str = "NR"
    if isinstance(per_arm_randomized, int) and isinstance(ia_started, int):
        intervention_dropout = max(per_arm_randomized - ia_started, 0)
    if isinstance(per_arm_randomized, int) and isinstance(sa_started, int):
        control_dropout = max(per_arm_randomized - sa_started, 0)

    dropout_reason = "NR"
    m = re.search(r"Two withdrew before the start of treatment,\s*one due to ([^.;]+) and the other due to ([^.;]+)", text, flags=re.I)
    if m:
        dropout_reason = f"before treatment: {m.group(1).strip()}; {m.group(2).strip()}"

    return {
        "total_randomized": total_randomized,
        "per_arm_randomized": per_arm_randomized,
        "ia_started": ia_started,
        "sa_started": sa_started,
        "intervention_dropout": intervention_dropout,
        "control_dropout": control_dropout,
        "dropout_reason": dropout_reason,
    }


def rule_extract_arms(doc: ParsedDocument, study: StudyRecord) -> list[ArmRecord]:
    text = all_text(doc)
    intervention, control = _extract_group_names(text, study)
    samples = _extract_arm_samples(text)
    usual = "usual pharmacological treatment prescribed by GP" if "pharmacological treatment" in text.lower() else "NR"
    intervention_arm = ArmRecord(
        study_id=study.study_id,
        arm_id=f"{study.study_id}_A1",
        arm_name="individualised acupuncture (IA)" if "individualised acupuncture" in intervention.lower() else intervention,
        arm_role="intervention",
        intervention_category=_category_for_arm("intervention", intervention),
        intervention_components=intervention,
        sample_randomized=samples["per_arm_randomized"],
        sample_started=samples["ia_started"],
        sample_analyzed_primary=samples["ia_started"],
        dropout_n=samples["intervention_dropout"],
        dropout_reason=samples["dropout_reason"] if samples["intervention_dropout"] not in (0, "0", "NR") else "NR",
        usual_care_components=usual,
        is_acupuncture_arm=True,
        notes="ArmExtractionAgent rule candidate; review sample fields against CONSORT flow diagram",
    )
    control_arm = ArmRecord(
        study_id=study.study_id,
        arm_id=f"{study.study_id}_C1",
        arm_name="sham acupuncture (SA)" if "sham acupuncture" in control.lower() else control,
        arm_role="control",
        intervention_category=_category_for_arm("control", control),
        intervention_components=control,
        sample_randomized=samples["per_arm_randomized"],
        sample_started=samples["sa_started"],
        sample_analyzed_primary=samples["sa_started"],
        dropout_n=samples["control_dropout"],
        dropout_reason="NR",
        usual_care_components=usual,
        is_acupuncture_arm=False,
        notes="ArmExtractionAgent rule candidate; review sample fields against CONSORT flow diagram",
    )
    return [intervention_arm, control_arm]

def _normalize_api_component_for_role(role: str, value: Any, text: str) -> str:
    low = str(value or "").lower()
    if role == "intervention" and "acupuncture" in low:
        base = "individualised acupuncture" if "individual" in low else "acupuncture"
        return _normalize_components(base, text)
    if role in {"control", "sham", "usual_care", "waitlist"} and ("sham" in low or "simulated" in low):
        return _normalize_components("sham acupuncture", text)
    return _normalize_components(str(value or "NR"), text)
def _valid_arm_value(field: str, value: Any) -> bool:
    if value in (None, ""):
        return False
    if field in {"sample_randomized", "sample_started", "sample_analyzed_primary", "dropout_n"}:
        return _int_or_nr(value) != "NR" or str(value).upper() == "NR"
    if field == "arm_role":
        return str(value).lower() in {"intervention", "control", "sham", "usual_care", "waitlist"}
    return len(str(value)) <= 240


def _api_refine_arms(doc: ParsedDocument, arms: list[ArmRecord], client: OpenAICompatibleClient | None = None) -> tuple[list[ArmRecord], dict[str, Any]]:
    client = client or OpenAICompatibleClient()
    prompt = {
        "task": "Refine 02_Arms for a clinical trial extraction template. Use only supplied PDF text. Return JSON with an 'arms' list. Do not invent values; use NR when not reported.",
        "fields": [
            "arm_id", "arm_name", "arm_role", "intervention_category", "intervention_components",
            "sample_randomized", "sample_started", "sample_analyzed_primary", "dropout_n", "dropout_reason",
            "usual_care_components", "is_acupuncture_arm", "notes",
        ],
        "current_rule_candidates": [a.model_dump() for a in arms],
        "requirements": [
            "Preserve exactly two arms unless the text clearly reports more arms.",
            "Include co-interventions, such as usual pharmacological treatment, in intervention_components or usual_care_components.",
            "Distinguish randomized sample from started/baseline sample when withdrawals occurred before treatment.",
            "Keep values concise and evidence-grounded.",
        ],
        "pdf_text": _compact_context(doc, max_chars=15000),
    }
    data = client.chat_json([
        {"role": "system", "content": "You are a careful clinical trial arm extraction subagent. Return JSON only."},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ])
    returned = data.get("arms", []) if isinstance(data, dict) else []
    if not isinstance(returned, list) or not returned:
        return arms, {"arms_api_status": "api_used_empty", "arms_backend": client.backend_name}

    by_role = {a.arm_role: a for a in arms}
    for item in returned[:4]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("arm_role") or "").lower()
        target = by_role.get("intervention") if role == "intervention" else by_role.get("control") if role in {"control", "sham", "usual_care", "waitlist"} else None
        if target is None:
            continue
        for field, value in item.items():
            if not hasattr(target, field) or not _valid_arm_value(field, value):
                continue
            if field in {"sample_randomized", "sample_started", "sample_analyzed_primary", "dropout_n"}:
                value = _int_or_nr(value)
            if field == "dropout_n" and target.dropout_n not in (None, "", "NR") and value != target.dropout_n:
                continue
            if field == "intervention_components":
                value = _normalize_api_component_for_role(role, value, all_text(doc))
            setattr(target, field, value)
    return arms, {"arms_api_status": "api_used", "arms_backend": client.backend_name, "arms_returned": len(returned)}

def _restore_deterministic_sample_flow(arms: list[ArmRecord], deterministic: list[ArmRecord]) -> list[ArmRecord]:
    by_role = {a.arm_role: a for a in deterministic}
    for arm in arms:
        source = by_role.get(arm.arm_role)
        if not source:
            continue
        arm.sample_randomized = source.sample_randomized
        arm.sample_started = source.sample_started
        arm.dropout_n = source.dropout_n
        if source.dropout_n not in (None, "", "NR", 0, "0"):
            arm.dropout_reason = source.dropout_reason
        elif arm.dropout_n in (0, "0"):
            arm.dropout_reason = "NR"
    return arms
def extract_arms(doc: ParsedDocument, study: StudyRecord, use_api: bool) -> tuple[list[ArmRecord], dict[str, Any]]:
    arms = rule_extract_arms(doc, study)
    deterministic_sample_flow = [a.model_copy(deep=True) for a in arms]
    info: dict[str, Any] = {"arms_agent": "rules", "arms_count": len(arms)}
    if use_api:
        try:
            arms, api_info = _api_refine_arms(doc, arms)
            arms = _restore_deterministic_sample_flow(arms, deterministic_sample_flow)
            info.update(api_info)
            info["arms_agent"] = "rules+api"
        except Exception as exc:
            info.update({"arms_api_status": "api_error", "arms_api_error": str(exc)})
    return arms, info








