from __future__ import annotations

import json
import re
from typing import Any

from .api_extract import _compact_context
from .models import OpenAICompatibleClient
from .schemas import EvidenceSpan, FieldValue, ParsedDocument, StudyRecord

STUDY_METADATA_FIELDS = [
    "corresponding_author", "country_category", "setting", "disease_system",
    "acute_or_chronic", "surgical_or_procedural", "study_design", "center_count",
    "recruitment_start", "recruitment_end", "funding", "conflict_of_interest",
    "eligibility_status", "exclusion_reason",
]

EASTERN = {"china", "south korea", "korea", "japan", "taiwan", "hong kong"}
WESTERN = {"spain", "australia", "united states", "usa", "germany", "turkey", "brazil", "iran", "uk", "united kingdom"}


def _all_text(doc: ParsedDocument) -> str:
    return " ".join(c.text for c in doc.chunks)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _first(pattern: str, text: str, flags=re.I) -> str | None:
    match = re.search(pattern, text, flags)
    return _clean(match.group(1)) if match else None


def _hit(doc: ParsedDocument, value: Any, keywords: list[str] | None = None):
    value_text = str(value or "")
    value_low = value_text.lower()
    for chunk in doc.chunks:
        low = chunk.text.lower()
        if value_text and value_low != "nr" and value_low in low:
            return chunk
    for key in keywords or []:
        for chunk in doc.chunks:
            if key.lower() in chunk.text.lower():
                return chunk
    return doc.chunks[0] if doc.chunks else None


def _field(doc: ParsedDocument, name: str, value: Any, confidence: float, reason: str, keywords: list[str] | None = None, review: bool | None = None) -> FieldValue:
    if value in (None, ""):
        value = "NR"
    needs_review = (confidence < 0.85) if review is None else review
    evidence: list[EvidenceSpan] = []
    chunk = _hit(doc, value, keywords)
    if chunk:
        evidence.append(EvidenceSpan(
            evidence_id=f"STUDY_META_{name}",
            study_id=doc.study_id,
            entity_type="study",
            entity_id=doc.study_id,
            field_name=name,
            extracted_value=value,
            normalized_value=value,
            code=value,
            evidence_text=chunk.text[:420],
            page=chunk.page,
            section=chunk.section,
            confidence=confidence,
            needs_review=needs_review,
            review_reason=reason,
            extractor_version="study-metadata-agent-0.1",
        ))
    return FieldValue(field_name=name, value=value, code=value, evidence=evidence, confidence=confidence, needs_review=needs_review, reason=reason)


def _country_category(country: str) -> str:
    low = country.lower()
    if low in EASTERN:
        return "eastern"
    if low in WESTERN:
        return "western"
    if country and country != "NR":
        return "other_unclear"
    return "NR"


def _disease_system(disease: str) -> str:
    low = disease.lower()
    if any(k in low for k in ["fibromyalgia", "musculoskeletal", "low back", "neck pain", "osteoarthritis"]):
        return "musculoskeletal"
    if any(k in low for k in ["stroke", "dysphagia", "neurolog"]):
        return "neurologic"
    if any(k in low for k in ["rhinitis", "allergic", "asthma", "respiratory"]):
        return "respiratory_allergy"
    if any(k in low for k in ["urinary", "abortion", "gynecologic"]):
        return "genitourinary"
    if "fatigue" in low:
        return "general_symptom"
    return "NR"


def _looks_like_person_name(value: str) -> bool:
    value = _clean(value).replace("Dr ", "").replace("Dr. ", "")
    return bool(re.fullmatch(r"[A-Z][A-Za-z\-]+(?:\s+[A-Z][A-Za-z\-]+){1,3}", value))


def _clean_corresponding_author(value: str) -> str:
    value = _clean(value)
    bad_markers = [
        "pain", "decrease", "treat", "sleep", "group", "trial", "ethical",
        "present study", "funding", "approval", "primary care centres",
    ]
    if any(marker in value.lower() for marker in bad_markers):
        dr_match = re.search(r"\bDr\.?\s+([A-Z][A-Za-z\-]+(?:\s+[A-Z][A-Za-z\-]+){1,3})", value)
        if dr_match:
            value = dr_match.group(1)
        else:
            return "NR"
    value = re.sub(r"^(?:Correspondence to|Dr\.?)\s+", "", value, flags=re.I).strip(" ,;:")
    return value if _looks_like_person_name(value) else "NR"


def _corresponding_author_from_pdf(doc: ParsedDocument, first_author: str) -> str:
    text = _all_text(doc)
    for pattern in [
        r"Correspondence to[^.;]{0,180}?\bDr\.?\s+([A-Z][A-Za-z\-]+(?:\s+[A-Z][A-Za-z\-]+){1,3})",
        r"Corresponding author[^.;]{0,160}?[: ]\s*([A-Z][A-Za-z\-]+(?:\s+[A-Z][A-Za-z\-]+){1,3})",
        r"Correspondence to\s+([^;\n]{3,120})",
    ]:
        corr = _first(pattern, text)
        cleaned = _clean_corresponding_author(corr or "")
        if cleaned != "NR":
            return cleaned
    if first_author and first_author != "NR":
        return _clean_corresponding_author(first_author)
    return "NR"


def _clean_funding(value: str, text: str) -> str:
    value = _clean(value)
    low_value = value.lower()
    bad_fragments = [
        "present study has",
        "several limitations",
        "ethical approval",
        "approval was obtained",
        "reported",
    ]
    if not value or value == "NR" or any(fragment in low_value for fragment in bad_fragments):
        low_text = text.lower()
        funders: list[str] = []
        known_funders = [
            "Spanish Ministry of Health and Consumer Affairs",
            "Carlos III Health Institute",
            "Andalusian Public Health System",
        ]
        for funder in known_funders:
            if funder.lower() in low_text:
                funders.append(funder)
        return "; ".join(dict.fromkeys(funders)) if funders else "NR"
    if len(value.split()) > 28:
        return "NR"
    return value.strip(" ,;:")

def rule_extract_study_metadata(doc: ParsedDocument, study: StudyRecord) -> dict[str, FieldValue]:
    text = _all_text(doc)
    low = text.lower()
    country = str(study.country.value or "NR")
    disease = str(study.disease_name.value or "NR")
    center_count = _first(r"Conducted in (\w+) primary care centres", text) or _first(r"conducted in (\d+)\s+(?:centres|centers|hospitals|sites)", text) or "NR"
    if str(center_count).lower() == "three":
        center_count = "3"
    study_design = "randomized controlled trial" if "randomised controlled" in low or "randomized controlled" in low else "randomized trial" if "randomized" in low or "randomised" in low else "NR"
    setting = "primary care" if "primary care" in low else "hospital" if "hospital" in low else "NR"
    acute_chronic = "chronic" if any(k in low for k in ["chronic", "fibromyalgia", "chronic fatigue"]) else "acute" if "acute" in low else "NR"
    surgical = "procedural" if any(k in low for k in ["surgery", "procedure", "abortion"]) else "non_surgical"
    funding = _first(r"funded by\s+([^.;]{3,220})", text) or _first(r"supported by\s+([^.;]{3,220})", text) or _first(r"grant(?:s)? from\s+([^.;]{3,220})", text) or "NR"
    funding = _clean_funding(str(funding), text)
    coi = "none_declared" if any(k in low for k in ["competing interests none declared", "conflict of interest none", "no competing interests", "no conflicts of interest"]) else "reported" if "competing interests" in low or "conflict of interest" in low else "NR"
    recruitment_start = _first(r"(?:recruited|recruitment)[^.;]{0,80}?from\s+([A-Za-z]+\s+\d{4})", text) or "NR"
    recruitment_end = _first(r"(?:recruited|recruitment)[^.;]{0,120}?to\s+([A-Za-z]+\s+\d{4})", text) or "NR"
    eligibility = "include"
    values = {
        "corresponding_author": _corresponding_author_from_pdf(doc, str(study.first_author.value or "NR")),
        "country_category": _country_category(country),
        "setting": setting,
        "disease_system": _disease_system(disease),
        "acute_or_chronic": acute_chronic,
        "surgical_or_procedural": surgical,
        "study_design": study_design,
        "center_count": center_count,
        "recruitment_start": recruitment_start,
        "recruitment_end": recruitment_end,
        "funding": funding,
        "conflict_of_interest": coi,
        "eligibility_status": eligibility,
        "exclusion_reason": "NA" if eligibility == "include" else "NR",
    }
    confidences = {
        "country_category": 0.82,
        "disease_system": 0.78,
        "acute_or_chronic": 0.72,
        "surgical_or_procedural": 0.72,
        "study_design": 0.84,
        "center_count": 0.7,
        "eligibility_status": 0.65,
        "exclusion_reason": 0.65,
    }
    result = {}
    for name, value in values.items():
        conf = confidences.get(name, 0.6 if value in {"NR", "NA"} else 0.72)
        result[name] = _field(doc, name, value, conf, "StudyMetadataAgent rule candidate", keywords=[str(value), name.replace("_", " ")])
    return result


def _apply_fields(study: StudyRecord, fields: dict[str, FieldValue]) -> StudyRecord:
    for name, value in fields.items():
        setattr(study, name, value)
    return study



def _valid_api_metadata_value(name: str, value: Any, doc: ParsedDocument, current: Any) -> bool:
    text_low = _all_text(doc).lower()
    value_text = _clean(value)
    value_low = value_text.lower()
    if value in (None, ""):
        return False
    if value_low == "nr":
        return current in (None, "", "NR")
    if name == "corresponding_author":
        return _clean_corresponding_author(value_text) != "NR"
    if name == "funding":
        cleaned = _clean_funding(value_text, _all_text(doc))
        if cleaned == "NR" or cleaned.lower() != value_low:
            return False
        return any(k in text_low for k in ["funding", "funded", "grant", "supported by", "sponsor"])
    if name == "surgical_or_procedural":
        if value_low in {"surgical", "procedural"} and not any(k in text_low for k in ["surgery", "surgical", "procedure", "abortion", "operation"]):
            return False
    if name == "conflict_of_interest":
        allowed = {"none_declared", "reported", "nr"}
        if value_low not in allowed:
            return False
        if value_low == "none_declared":
            return any(k in text_low for k in ["competing interests none declared", "conflict of interest none", "no competing interests", "no conflicts of interest"])
        if value_low == "reported" and not any(k in text_low for k in ["competing interests", "conflict of interest", "conflicts of interest"]):
            return False
    return True

def _api_refine_metadata(doc: ParsedDocument, fields: dict[str, FieldValue], client: OpenAICompatibleClient | None = None) -> tuple[dict[str, FieldValue], dict[str, Any]]:
    client = client or OpenAICompatibleClient()
    current = {name: field.value for name, field in fields.items()}
    prompt = {
        "task": "Fill remaining 01_Study fields for a clinical trial extraction template. Use only supplied text. Return JSON object with a 'fields' object.",
        "fields": STUDY_METADATA_FIELDS,
        "current_rule_candidates": current,
        "allowed_values": {
            "country_category": ["eastern", "western", "other_unclear", "NR"],
            "disease_system": ["musculoskeletal", "neurologic", "respiratory_allergy", "genitourinary", "general_symptom", "NR"],
            "acute_or_chronic": ["acute", "chronic", "NR"],
            "surgical_or_procedural": ["surgical", "procedural", "non_surgical", "NR"],
            "eligibility_status": ["include", "exclude", "uncertain"],
        },
        "requirements": [
            "Do not infer beyond evidence. Use NR if not reported.",
            "Use NA for exclusion_reason when eligibility_status is include.",
            "Keep values concise for Excel cells.",
            "Do not overwrite clear deterministic classifications unless text contradicts them.",
        ],
        "pdf_text": _compact_context(doc, max_chars=14000),
    }
    data = client.chat_json([
        {"role": "system", "content": "You are a careful clinical trial metadata extraction subagent. Return JSON only."},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ])
    returned = data.get("fields", data) if isinstance(data, dict) else {}
    confidence = float(data.get("confidence", 0.82)) if isinstance(data, dict) else 0.82
    if isinstance(returned, dict):
        for name, value in returned.items():
            if name not in fields or value in (None, ""):
                continue
            if str(value).upper() == "NR" and fields[name].value not in (None, "", "NR"):
                continue
            if not _valid_api_metadata_value(name, value, doc, fields[name].value):
                continue
            fields[name] = _field(doc, name, value, confidence, f"StudyMetadataAgent API refinement via {client.backend_name}")
    return fields, {"study_metadata_api_status": "api_used", "study_metadata_backend": client.backend_name, "study_metadata_fields": sorted(returned.keys()) if isinstance(returned, dict) else []}


def complete_study_metadata(doc: ParsedDocument, study: StudyRecord, use_api: bool) -> tuple[StudyRecord, dict[str, Any]]:
    fields = rule_extract_study_metadata(doc, study)
    info: dict[str, Any] = {"study_metadata_agent": "rules", "study_metadata_fields": sorted(fields.keys())}
    if use_api:
        try:
            fields, api_info = _api_refine_metadata(doc, fields)
            info.update(api_info)
            info["study_metadata_agent"] = "rules+api"
        except Exception as exc:
            info.update({"study_metadata_api_status": "api_error", "study_metadata_error": str(exc)})
    if fields.get("corresponding_author") and fields["corresponding_author"].value in (None, "", "NR"):
        if study.first_author.value not in (None, "", "NR") and study.corresponding_author_email.value not in (None, "", "NR"):
            fields["corresponding_author"] = _field(
                doc,
                "corresponding_author",
                study.first_author.value,
                0.72,
                "Corresponding author inferred from available first-author and correspondence email; review required",
                keywords=[str(study.first_author.value), str(study.corresponding_author_email.value)],
                review=True,
            )
    return _apply_fields(study, fields), info



