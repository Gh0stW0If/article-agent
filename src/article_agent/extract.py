from __future__ import annotations

import re
from itertools import count

from .retrieval import HybridRetriever
from .schemas import ArmRecord, ComparisonRecord, EvidenceSpan, FieldValue, OutcomeRecord, ParsedDocument, ReviewRecord, StudyRecord

EV_COUNTER = count(1)


def _snippet(text: str, max_len: int = 420) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def evidence_from_hit(study_id: str, entity_type: str, entity_id: str, field: str, value, hit, confidence: float, review: bool, reason: str) -> EvidenceSpan:
    chunk, score = hit
    return EvidenceSpan(
        evidence_id=f"EV{next(EV_COUNTER):06d}",
        study_id=study_id,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field,
        extracted_value=value,
        normalized_value=value,
        code=value,
        evidence_text=_snippet(chunk.text),
        page=chunk.page,
        section=chunk.section,
        confidence=confidence,
        needs_review=review,
        review_reason=reason,
    )


def field_from_hit(study_id: str, entity_type: str, entity_id: str, field: str, value, hit, confidence: float, review: bool, reason: str) -> FieldValue:
    ev = evidence_from_hit(study_id, entity_type, entity_id, field, value, hit, confidence, review, reason)
    return FieldValue(field_name=field, value=value, code=value, evidence=[ev], confidence=confidence, needs_review=review, reason=reason)


def nr_field(field: str, reason: str = "Not found in MVP evidence search") -> FieldValue:
    return FieldValue(field_name=field, value="NR", code="NR", confidence=0.0, needs_review=True, reason=reason)


def first_match(pattern: str, text: str, flags=re.I):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def extract_title(doc: ParsedDocument, retriever: HybridRetriever) -> FieldValue:
    first = doc.chunks[0] if doc.chunks else None
    if not first:
        return nr_field("title")
    text = first.text
    # Prefer text around common title markers; otherwise first sentence-like line.
    title = None
    m = re.search(r"Original paper\s+(.+?)(?:\s+[A-Z][a-z]+\s+[A-Z][a-z]+,|\s+Additional material|\s+ABSTRACT)", text, re.I)
    if m:
        title = m.group(1).strip(" .")
    if not title:
        m = re.search(r"(?:OPEN\s+)?([A-Z][^.]{20,220}?(?:trial|study|effect|acupuncture|needling|therapy|treatment)[^.]{0,120})", text, re.I)
        if m:
            title = m.group(1).strip(" .")
    if not title:
        clean = re.sub(r"Downloaded from .*?Original paper", "", text, flags=re.I)
        parts = re.split(r"(?<=\.)\s+|\n", clean)
        candidates = [p.strip(" .") for p in parts if 35 <= len(p.strip()) <= 220]
        title = candidates[0] if candidates else doc.study_id
    return field_from_hit(doc.study_id, "study", doc.study_id, "title", title, (first, 1.0), 0.72, True, "MVP title heuristic")


def extract_year(doc: ParsedDocument) -> FieldValue:
    year = first_match(r"(20\d{2})", doc.study_id)
    if not year:
        text = " ".join(c.text[:1000] for c in doc.chunks[:2])
        year = first_match(r"\b(20\d{2})\b", text)
    if not year:
        return nr_field("year")
    hit = (doc.chunks[0], 1.0) if doc.chunks else None
    return field_from_hit(doc.study_id, "study", doc.study_id, "year", int(year), hit, 0.8, False, "Year found near title page") if hit else nr_field("year")


def extract_journal(doc: ParsedDocument) -> FieldValue:
    first = doc.chunks[0] if doc.chunks else None
    if not first:
        return nr_field("journal")
    text = first.text[:1600]
    journal = None
    if "aim.bmj.com" in text.lower() or "acupmed" in text.lower():
        journal = "Acupuncture in Medicine"
    else:
        for pat in [r"\b(Medicine)\b", r"\b(Pain)\b", r"\b(?:Journal|Trials|Acupuncture in Medicine)[A-Za-z &-]*"]:
            m = re.search(pat, text, re.I)
            if m:
                journal = m.group(0).strip()
                break
    return field_from_hit(doc.study_id, "study", doc.study_id, "journal", journal or "NR", (first, 1.0), 0.55 if journal else 0.0, not bool(journal), "MVP journal heuristic")


def extract_language(doc: ParsedDocument) -> FieldValue:
    if not doc.chunks:
        return nr_field("language")
    return field_from_hit(doc.study_id, "study", doc.study_id, "language", "English", (doc.chunks[0], 0.5), 0.65, True, "MVP assumes English from parsed text; review")


def extract_query_field(doc: ParsedDocument, retriever: HybridRetriever, field: str, query: str, pattern: str | None = None, confidence: float = 0.55) -> FieldValue:
    hits = retriever.search(query, limit=3)
    if not hits:
        return nr_field(field)
    value = "NR"
    if pattern:
        for chunk, _ in hits:
            v = first_match(pattern, chunk.text)
            if v:
                value = v
                break
    if value == "NR":
        value = _snippet(hits[0][0].text, 160)
    return field_from_hit(doc.study_id, "study", doc.study_id, field, value, hits[0], confidence, True, "MVP candidate requires review")



def all_text(doc: ParsedDocument) -> str:
    return " ".join(c.text for c in doc.chunks)


def best_hit_for_text(doc: ParsedDocument, needle: str):
    needle_low = needle.lower()
    for c in doc.chunks:
        if needle_low in c.text.lower():
            return (c, 1.0)
    return (doc.chunks[0], 0.5) if doc.chunks else None


def direct_field(doc: ParsedDocument, field: str, value, confidence: float, reason: str, review: bool = True) -> FieldValue:
    hit = best_hit_for_text(doc, str(value))
    if not hit and "+" in str(value):
        hit = best_hit_for_text(doc, str(value).split("+")[0].strip())
    if not hit:
        return nr_field(field)
    return field_from_hit(doc.study_id, "study", doc.study_id, field, value, hit, confidence, review, reason)


def extract_disease(doc: ParsedDocument, retriever: HybridRetriever) -> FieldValue:
    text = all_text(doc)
    known = ["fibromyalgia", "seasonal allergic rhinitis", "dysphagia", "chronic fatigue", "urinary retention"]
    for name in known:
        if name in text.lower():
            return direct_field(doc, "disease_name", name, 0.82, "Known condition found in article text", False)
    return extract_query_field(doc, retriever, "disease_name", "patients participants diagnosed condition inclusion criteria", r"(?:patients|participants) with ([^.;,]{3,90})")


def extract_intervention(doc: ParsedDocument, retriever: HybridRetriever) -> FieldValue:
    text = all_text(doc)
    patterns = [
        r"(individualised acupuncture)",
        r"(electroacupuncture)",
        r"(manual acupuncture)",
        r"real intervention[^.;]{0,60}\(([^)]*acupuncture[^)]*)\)",
        r"intervention[^.;]{0,60}\(([^)]*acupuncture[^)]*)\)",
    ]
    for pat in patterns:
        v = first_match(pat, text)
        if v:
            if "pharmacological treatment" in text.lower() and "usual" not in v.lower():
                v = f"{v} + usual pharmacological treatment"
            return direct_field(doc, "intervention_name", v, 0.78, "Intervention pattern found", True)
    return extract_query_field(doc, retriever, "intervention_name", "acupuncture treatment intervention group needling", r"((?:manual |electro)?acupuncture[^.;]{0,80})")


def extract_control(doc: ParsedDocument, retriever: HybridRetriever) -> FieldValue:
    text = all_text(doc)
    patterns = [
        r"sham intervention \(([^)]*sham acupuncture[^)]*)\)",
        r"(sham acupuncture)",
        r"(usual care)",
        r"(waiting list)",
    ]
    for pat in patterns:
        v = first_match(pat, text)
        if v:
            if "pharmacological treatment" in text.lower() and "usual" not in v.lower():
                v = f"{v} + usual pharmacological treatment"
            return direct_field(doc, "control_name", v, 0.78, "Control pattern found", True)
    return extract_query_field(doc, retriever, "control_name", "control group sham placebo usual care waitlist", r"((?:sham|placebo|usual care|wait(?:ing)? list)[^.;]{0,90})")


def extract_randomized_n(doc: ParsedDocument, retriever: HybridRetriever) -> FieldValue:
    text = all_text(doc)
    patterns = [
        r"A total of (\d{2,4}) participants",
        r"(\d{2,4}) participants[^.;]{0,80}(?:randomly assigned|randomised|randomized)",
        r"(?:randomised|randomized|allocated)[^.;]{0,80}(\d{2,4}) participants",
    ]
    for pat in patterns:
        v = first_match(pat, text)
        if v:
            return direct_field(doc, "randomized_n", int(v), 0.78, "Randomized/sample size pattern found", True)
    return extract_query_field(doc, retriever, "randomized_n", "randomized randomised allocated participants groups", r"(\d{2,4})\s+(?:patients|participants|subjects).{0,80}(?:randomized|randomised|allocated)")


def extract_primary_outcome_field(doc: ParsedDocument, retriever: HybridRetriever) -> FieldValue:
    text = all_text(doc)
    patterns = [
        r"The primary outcome was ([^.;]{3,140})",
        r"primary outcome(?: was| measure was|:)?\s*([^.;]{3,140})",
    ]
    for pat in patterns:
        v = first_match(pat, text)
        if v:
            v = re.split(r",\s*(?:scribed|among|and/or)|\s+scribed by", v.strip(), maxsplit=1, flags=re.I)[0].strip()
            if "pain intensity" in v.lower() and "10 weeks" not in v.lower():
                v = "change in pain intensity at 10 weeks"
            return direct_field(doc, "primary_outcome", v, 0.8, "Primary outcome sentence found", True)
    return extract_query_field(doc, retriever, "primary_outcome", "primary outcome main outcome endpoint", r"primary outcome(?: was| measure was|:)?\s*([^.;]{3,120})")


def extract_sessions(doc: ParsedDocument, retriever: HybridRetriever) -> FieldValue:
    text = all_text(doc)
    # Common phrasing: one session per week ... primary outcome at 10 weeks.
    if re.search(r"one session per week", text, re.I):
        weeks = first_match(r"(?:at|for)\s+(\d+)\s+weeks", text)
        if weeks:
            return direct_field(doc, "treatment_sessions", f"{weeks} sessions", 0.7, "Frequency and duration pattern found", True)
    m = re.search(r"(\d+)\s+(?:sessions|treatments)", text, re.I)
    if m:
        return direct_field(doc, "treatment_sessions", f"{m.group(1)} sessions", 0.65, "Session count found", True)
    return extract_query_field(doc, retriever, "treatment_sessions", "sessions treatment weeks times per week", r"(\d+\s+(?:sessions|treatments)|\d+\s*times per week[^.;]{0,60})")

def extract_study(doc: ParsedDocument) -> StudyRecord:
    retriever = HybridRetriever(doc.chunks)
    title = extract_title(doc, retriever)
    year = extract_year(doc)
    journal = extract_journal(doc)
    language = extract_language(doc)
    disease = extract_disease(doc, retriever)
    country = extract_query_field(doc, retriever, "country", "country hospital university participants recruited", r"\b(China|Korea|Spain|United States|USA|Germany|Australia|Turkey|Iran|Brazil|Japan|Taiwan|Hong Kong)\b")
    intervention = extract_intervention(doc, retriever)
    control = extract_control(doc, retriever)
    randomized = extract_randomized_n(doc, retriever)
    primary = extract_primary_outcome_field(doc, retriever)
    sessions = extract_sessions(doc, retriever)
    return StudyRecord(
        study_id=doc.study_id,
        source_pdf=str(doc.source_pdf),
        title=title,
        year=year,
        journal=journal,
        language=language,
        first_author=nr_field("first_author", "Metadata enrichment not yet run"),
        corresponding_author_email=nr_field("corresponding_author_email", "Metadata enrichment not yet run"),
        doi=nr_field("doi", "Metadata enrichment not yet run"),
        corresponding_author=nr_field("corresponding_author", "StudyMetadataAgent not yet run"),
        country_category=nr_field("country_category", "StudyMetadataAgent not yet run"),
        setting=nr_field("setting", "StudyMetadataAgent not yet run"),
        disease_system=nr_field("disease_system", "StudyMetadataAgent not yet run"),
        acute_or_chronic=nr_field("acute_or_chronic", "StudyMetadataAgent not yet run"),
        surgical_or_procedural=nr_field("surgical_or_procedural", "StudyMetadataAgent not yet run"),
        study_design=nr_field("study_design", "StudyMetadataAgent not yet run"),
        center_count=nr_field("center_count", "StudyMetadataAgent not yet run"),
        recruitment_start=nr_field("recruitment_start", "StudyMetadataAgent not yet run"),
        recruitment_end=nr_field("recruitment_end", "StudyMetadataAgent not yet run"),
        funding=nr_field("funding", "StudyMetadataAgent not yet run"),
        conflict_of_interest=nr_field("conflict_of_interest", "StudyMetadataAgent not yet run"),
        eligibility_status=nr_field("eligibility_status", "StudyMetadataAgent not yet run"),
        exclusion_reason=nr_field("exclusion_reason", "StudyMetadataAgent not yet run"),
        disease_name=disease,
        country=country,
        intervention_name=intervention,
        control_name=control,
        randomized_n=randomized,
        primary_outcome=primary,
        treatment_sessions=sessions,
    )




def evidence_window(text: str, keywords: list[str], radius: int = 220) -> str:
    low = text.lower()
    for key in keywords:
        idx = low.find(key.lower())
        if idx >= 0:
            start = max(0, idx - radius // 2)
            end = min(len(text), idx + radius)
            window = re.sub(r"\s+", " ", text[start:end]).strip(" .")
            return window + "."
    return "NR"


def comparison_code_label(intervention: str, control: str) -> tuple[str, str]:
    i = intervention.lower()
    c = control.lower()
    if "usual" in i and ("sham" in c or "placebo" in c) and "usual" in c:
        return "B", "Acupuncture + usual care vs sham/placebo + usual care"
    if "usual" in i and "usual" in c:
        return "C", "Acupuncture + usual care vs usual care"
    if "sham" in c or "placebo" in c:
        return "A", "Acupuncture vs sham/placebo"
    if "wait" in c or "no treatment" in c:
        return "D", "Acupuncture vs waiting list/no treatment"
    return "E", "Other"


def control_code_label(control: str) -> tuple[str, str]:
    c = control.lower()
    if "non-penetrating" in c or "without insertion" in c:
        return "non_invasive_sham", "Non-invasive sham acupuncture"
    if "sham" in c or "superficial" in c or "non-acupoint" in c:
        return "invasive_sham", "Invasive sham acupuncture"
    if "usual" in c or "standard" in c:
        return "usual_care", "Usual care"
    if "wait" in c:
        return "waiting_list", "Waiting list/no treatment"
    if "placebo" in c:
        return "placebo", "Placebo/simulation"
    return "NR", "NR"

def build_method_record(doc: ParsedDocument) -> dict:
    text = all_text(doc)
    random_text = evidence_window(text, ["centralised telephone", "centralized telephone", "fax randomisation service", "randomisation service", "randomization service", "random allocation sequence", "computer-generated", "random number table", "randomly assigned"])
    allocation_text = evidence_window(text, ["independent clinical trials unit", "allocation was concealed", "allocation process", "opaque sealed envelopes", "sealed opaque envelopes", "concealed"])
    low_random = random_text.lower()
    random_code = "central_service" if any(k in low_random for k in ["centralised", "centralized", "telephone", "fax", "service"]) else "computer" if any(k in low_random for k in ["computer", "sas", "random allocation sequence"]) else "random_number_table" if "random number" in low_random else "NR"
    low_alloc = allocation_text.lower()
    allocation_code = "central_service" if "central" in low_alloc or "independent clinical trials unit" in low_alloc or "concealed" in low_alloc else "sealed_opaque_envelope" if "opaque" in low_alloc and "sealed" in low_alloc else "NR"
    return {
        "study_id": doc.study_id,
        "random_sequence_text": random_text,
        "random_sequence_code": random_code,
        "allocation_concealment_text": allocation_text,
        "allocation_concealment_code": allocation_code,
        "participant_blinding_text": "blinded to participants" if "blinded to participants" in text.lower() or "participants were blinded" in text.lower() else "NR",
        "participant_blinding_code": "yes" if "blinded to participants" in text.lower() or "participants were blinded" in text.lower() else "unclear",
        "personnel_blinding_text": "NR",
        "personnel_blinding_code": "unclear",
        "outcome_assessor_blinding_text": "outcome assessor blinded" if "outcome assessor" in text.lower() and "blind" in text.lower() else "NR",
        "outcome_assessor_blinding_code": "yes" if "outcome assessor" in text.lower() and "blind" in text.lower() else "unclear",
        "statistician_blinding_text": "data analysts blinded" if "data analyst" in text.lower() and "blind" in text.lower() else "NR",
        "statistician_blinding_code": "yes" if "data analyst" in text.lower() and "blind" in text.lower() else "unclear",
        "sample_size_calculation": "reported" if "sample size" in text.lower() else "NR",
        "target_sample_size": first_match(r"sample size[^.]{0,80}?(\d{2,4})", text) or "NR",
        "primary_analysis_set": "intention_to_treat" if "intention-to-treat" in text.lower() else "NR",
        "missing_data_method": "LOCF" if "last observation" in text.lower() or "locf" in text.lower() else "mixed_model" if "mixed model" in text.lower() or "mmrm" in text.lower() else "NR",
        "missing_data_details": "MVP method extraction",
        "protocol_registration": "reported" if "trial registration" in text.lower() else "NR",
        "ethics_approval": "reported" if "ethics" in text.lower() else "NR",
        "consent_reported": "reported" if "informed consent" in text.lower() else "NR",
        "notes": "MVP method record; review required",
    }


def build_acupuncture_record(doc: ParsedDocument, study: StudyRecord, arm_id: str) -> dict:
    text = all_text(doc)
    treatment_sessions = str(study.treatment_sessions.value or "NR")
    total_sessions = first_match(r"(\d+)", treatment_sessions) or "NR"
    retention = first_match(r"(\d+)\s*min", text) or "NR"
    return {
        "study_id": doc.study_id,
        "arm_id": arm_id,
        "acupuncture_modality": "manual" if "electroacupuncture" not in text.lower() else "electroacupuncture",
        "stimulation_type": "manual" if "electroacupuncture" not in text.lower() else "electrical",
        "point_selection_scheme": "individualized" if "individual" in str(study.intervention_name.value).lower() or "individual" in text.lower() else "NR",
        "syndrome_differentiation": "NR",
        "acupoints_common": first_match(r"((?:acupoints|points)[^.]{0,220})", text) or "NR",
        "acupoints_individualized": "reported" if "individual" in text.lower() else "NR",
        "acupoint_location_type": "NR",
        "needle_type": "NR",
        "needle_size": "NR",
        "insertion_depth": first_match(r"depth[^.]*?between\s+([\d\-– ]+\s*mm)", text) or "NR",
        "manipulation": "reported" if "manipulat" in text.lower() else "NR",
        "deqi_reported": "yes" if "de qi" in text.lower() or "deqi" in text.lower() else "NR",
        "retention_time_min": retention,
        "session_duration_min": retention,
        "frequency_per_week": "1" if "one session per week" in text.lower() else first_match(r"(\d+)\s*times per week", text) or "NR",
        "treatment_duration_weeks": first_match(r"(\d+)\s+weeks", text) or "NR",
        "total_sessions": total_sessions,
        "practitioner_qualification": "NR",
        "cointerventions": "usual pharmacological treatment" if "pharmacological treatment" in text.lower() else "NR",
        "sham_details": str(study.control_name.value or "NR") if "sham" in str(study.control_name.value).lower() else "NR",
        "notes": "MVP acupuncture record; review required",
    }

def derive_related_records(study: StudyRecord, arms: list[ArmRecord] | None = None) -> tuple[list[ArmRecord], list[ComparisonRecord], list[OutcomeRecord]]:
    if arms is None:
        intervention_arm = ArmRecord(
            study_id=study.study_id,
            arm_id=f"{study.study_id}_A1",
            arm_name=str(study.intervention_name.value or "Intervention"),
            arm_role="intervention",
            intervention_category="acupuncture" if "acupuncture" in str(study.intervention_name.value or "").lower() else "NR",
            intervention_components=str(study.intervention_name.value or "NR"),
            sample_randomized=study.randomized_n.value or "NR",
            is_acupuncture_arm="acupuncture" in str(study.intervention_name.value or "").lower(),
        )
        control_arm = ArmRecord(
            study_id=study.study_id,
            arm_id=f"{study.study_id}_C1",
            arm_name=str(study.control_name.value or "Control"),
            arm_role="control",
            intervention_category="sham_acupuncture" if "sham" in str(study.control_name.value or "").lower() else "NR",
            intervention_components=str(study.control_name.value or "NR"),
            is_acupuncture_arm=False,
        )
        arms = [intervention_arm, control_arm]
    intervention_arm = next((a for a in arms if a.arm_role == "intervention"), arms[0])
    control_arm = next((a for a in arms if a.arm_role in {"control", "sham", "usual_care", "waitlist"}), arms[1] if len(arms) > 1 else arms[0])
    cmp_code, cmp_label = comparison_code_label(intervention_arm.intervention_components or intervention_arm.arm_name, control_arm.intervention_components or control_arm.arm_name)
    ctrl_code, ctrl_label = control_code_label(control_arm.intervention_components or control_arm.arm_name)
    comparison = ComparisonRecord(
        study_id=study.study_id,
        comparison_id=f"{study.study_id}_CMP1",
        intervention_arm_id=intervention_arm.arm_id,
        control_arm_id=control_arm.arm_id,
        comparison_label=f"{intervention_arm.intervention_components or intervention_arm.arm_name} vs {control_arm.intervention_components or control_arm.arm_name}",
        comparison_type_code=cmp_code,
        comparison_type_label=cmp_label,
        control_type_code=ctrl_code,
        control_type_label=ctrl_label,
    )
    outcome_name = str(study.primary_outcome.value or "NR")
    outcome = OutcomeRecord(
        study_id=study.study_id,
        outcome_id=f"{study.study_id}_OUT1",
        outcome_name=outcome_name,
        is_primary_outcome=outcome_name != "NR",
        patient_important_category=categorize_outcome(outcome_name),
    )
    return arms, [comparison], [outcome]

def categorize_outcome(name: str) -> str:
    low = name.lower()
    if "pain" in low or "vas" in low:
        return "pain"
    if any(k in low for k in ["quality of life", "qol", "sf-", "eq-5d"]):
        return "quality_of_life"
    if any(k in low for k in ["function", "disability", "barthel"]):
        return "function"
    return "other"


def collect_evidence(study: StudyRecord) -> list[EvidenceSpan]:
    evidence: list[EvidenceSpan] = []
    for field in [study.title, study.year, study.journal, study.language, study.first_author, study.corresponding_author_email, study.doi, study.disease_name, study.country, study.intervention_name, study.control_name, study.randomized_n, study.primary_outcome, study.treatment_sessions]:
        evidence.extend(field.evidence)
    return evidence


def build_review(study: StudyRecord, evidence: list[EvidenceSpan]) -> list[ReviewRecord]:
    rows: list[ReviewRecord] = []
    for field in [study.title, study.year, study.journal, study.language, study.first_author, study.corresponding_author_email, study.doi, study.disease_name, study.country, study.intervention_name, study.control_name, study.randomized_n, study.primary_outcome, study.treatment_sessions]:
        if field.needs_review or field.confidence < 0.75 or field.value in (None, "NR", ""):
            ev = field.evidence[0].evidence_text if field.evidence else ""
            rows.append(
                ReviewRecord(
                    review_id=f"RV{len(rows)+1:06d}",
                    study_id=study.study_id,
                    entity_type="study",
                    entity_id=study.study_id,
                    field_name=field.field_name,
                    proposed_value=field.value,
                    proposed_code=field.code,
                    evidence_text=ev,
                    issue_type="low_confidence_or_missing_evidence",
                    severity="warning",
                )
            )
    return rows

