from __future__ import annotations

from typing import Any

from .models import OpenAICompatibleClient
from .schemas import FieldValue, ParsedDocument, StudyRecord

API_FIELDS = [
    "title", "year", "journal", "language", "disease_name", "country",
    "intervention_name", "control_name", "randomized_n", "primary_outcome", "treatment_sessions",
]


def _compact_context(doc: ParsedDocument, max_chars: int = 12000) -> str:
    parts: list[str] = []
    for chunk in doc.chunks[:8]:
        prefix = chunk.context_prefix or f"page={chunk.page} | section={chunk.section} | source_type={chunk.source_type}"
        parts.append(f"[{prefix}] {chunk.text[:2200]}")
    text = "\n\n".join(parts)
    return text[:max_chars]


def _set_field(study: StudyRecord, name: str, value: Any, confidence: float, backend: str) -> None:
    if name == "journal" and str(value).strip().lower() == "acupunct med":
        value = "Acupuncture in Medicine"
    field: FieldValue = getattr(study, name)
    if value in (None, "", "NR"):
        return
    field.value = value
    field.code = value
    field.confidence = max(field.confidence, confidence)
    field.needs_review = confidence < 0.85
    field.reason = f"API reviewed candidate via {backend}; evidence remains linked to local retrieved span"
    for ev in field.evidence:
        ev.extracted_value = value
        ev.normalized_value = value
        ev.code = value
        ev.confidence = field.confidence
        ev.needs_review = field.needs_review
        ev.review_reason = field.reason
        ev.extractor_version = f"api+mvp-0.1:{backend}"


def api_refine_study(doc: ParsedDocument, study: StudyRecord, client: OpenAICompatibleClient | None = None) -> tuple[StudyRecord, dict[str, Any]]:
    client = client or OpenAICompatibleClient()
    current = {name: getattr(study, name).value for name in API_FIELDS}
    prompt = {
        "task": "Extract article-level Sheet1 MVP fields from PDF text. Only use the supplied text. Use NR if not reported. Return strict JSON.",
        "fields": API_FIELDS,
        "current_rule_candidates": current,
        "requirements": [
            "Do not infer beyond source text.",
            "Prefer exact concise values suitable for an Excel extraction template.",
            "For intervention/control, include co-interventions if both groups receive them.",
            "For treatment_sessions, return total sessions if directly derivable from frequency and duration, otherwise NR.",
        ],
        "pdf_text": _compact_context(doc),
    }
    result = client.chat_json([
        {"role": "system", "content": "You are an evidence-first clinical trial extraction assistant. Return JSON only."},
        {"role": "user", "content": __import__('json').dumps(prompt, ensure_ascii=False)},
    ])
    fields = result.get("fields", result)
    confidence = float(result.get("confidence", 0.82)) if isinstance(result, dict) else 0.82
    for name in API_FIELDS:
        if isinstance(fields, dict) and name in fields:
            _set_field(study, name, fields.get(name), confidence, client.backend_name)

    # Deterministic guards: API may see download/published metadata that conflicts with the study ID.
    id_year = __import__("re").search(r"(20\d{2})", study.study_id)
    if id_year:
        _set_field(study, "year", int(id_year.group(1)), max(confidence, 0.9), client.backend_name)

    context_low = prompt["pdf_text"].lower()
    if "pharmacological treatment" in context_low:
        for field_name in ["intervention_name", "control_name"]:
            field = getattr(study, field_name)
            value = str(field.value or "")
            if value and value != "NR" and "pharmacological treatment" not in value.lower():
                _set_field(study, field_name, f"{value} + usual pharmacological treatment", confidence, client.backend_name)

    return study, {"backend": client.backend_name, "fields_returned": sorted(fields.keys()) if isinstance(fields, dict) else [], "confidence": confidence, "deterministic_guards": ["study_id_year", "cointervention_preservation"]}

