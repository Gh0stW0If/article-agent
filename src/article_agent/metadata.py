from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import os
import shutil
import subprocess
from difflib import SequenceMatcher
from html import unescape
from typing import Any

from pydantic import BaseModel, Field

from .baml_adapter import BamlExtractor
from .models import OpenAICompatibleClient
try:
    import fitz
except Exception:
    fitz = None

from .schemas import EvidenceSpan, FieldValue, ParsedDocument, StudyRecord



class _MetadataEvidence(BaseModel):
    field_id: str
    quote: str
    page: int | None = None
    source: str = "markdown"
    support_type: str = "direct"
    derivation: str | None = None


class _MetadataExtraction(BaseModel):
    title: str = "NR"
    publication_year: int | None = None
    language: str = "NR"
    journal: str = "NR"
    first_author: str = "NR"
    author_contact: str = "NR"
    disease_name: str = "NR"
    country: str = "NR"
    intervention: str = "NR"
    control: str = "NR"
    evidence: list[_MetadataEvidence] = Field(default_factory=list)


def _baml_metadata(doc: ParsedDocument, raw_dir: Any = None) -> tuple[_MetadataExtraction | None, str]:
    """Run the generated Metadata BAML skill when explicitly configured.

    A missing BAML client or failed call is non-fatal: deterministic PDF and
    external metadata enrichment remains authoritative, and unavailable values
    stay NR rather than being guessed.
    """
    extractor = BamlExtractor(raw_dir=raw_dir)
    if extractor.generated_client is None:
        return None, "baml_unavailable"
    context = "\n\n".join(
        f"[page={c.page}; section={c.section}; source_type={c.source_type}; chunk_id={c.chunk_id}] {c.text}"
        for c in doc.chunks[:24]
    )
    try:
        result = extractor.extract("metadata", _MetadataExtraction, context, {
            "task_description": "Extract article metadata, first author and author contact from supplied evidence only. Return NR when unavailable; never guess.",
            "field_boundaries": {"first_author": "first listed author", "author_contact": "corresponding author email, otherwise first-author email"},
            "json_template": {"first_author": "NR", "author_contact": "NR", "evidence": []},
        })
        return result, extractor.backend_name
    except Exception:
        return None, "baml_error"



def _vision_first_page_metadata(doc: ParsedDocument) -> tuple[dict[str, Any] | None, str]:
    """Read the first page as an image; failures leave the field unresolved."""
    if fitz is None or not doc.source_pdf.exists():
        return None, "vision_unavailable"
    try:
        pdf = fitz.open(str(doc.source_pdf)); page = pdf.load_page(0)
        image = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False).tobytes("png")
        result = OpenAICompatibleClient().chat_vision_json(
            "Read only the article first page. Return JSON with title, journal, doi, first_author, author_contact. "
            "Copy exact text; if a value is not clearly visible return NR. Never infer or repair a DOI.", image, "image/png")
        return result, "vision"
    except Exception:
        return None, "vision_error"


def _text(doc: ParsedDocument) -> str:
    return " ".join(c.text for c in doc.chunks)


def clean_contact_string(raw: str | None) -> str:
    """Normalize workbook/contact text without changing the email itself."""
    value = str(raw or "").strip()
    value = re.sub(r"^\s*[1-3]\s*[:：]\s*", "", value)
    value = re.sub(r"\s+(?=[.@])|(?<=[.@])\s+", "", value)
    return value.strip(" .;,()[]")


def extract_email_candidates(raw: str | None) -> list[str]:
    value = clean_contact_string(raw)
    # Permit line breaks/spaces inserted around @ and dots, but return only
    # syntactically complete addresses.
    compact = re.sub(r"\s+(?=[.@])|(?<=[.@])\s+", "", value)
    candidates = re.findall(r"[A-Za-z0-9_%+\-]+(?:\.[A-Za-z0-9_%+\-]+)*@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+", compact)
    return list(dict.fromkeys(_clean_email(x) for x in candidates))


def email_matches_gold(candidates: list[str] | str | None, gold_contact: str | None) -> bool:
    """Return true when any normalized candidate matches an email in Gold text."""
    left = candidates if isinstance(candidates, list) else [candidates]
    predicted = {x.lower() for value in left for x in extract_email_candidates(value)}
    expected = {x.lower() for x in extract_email_candidates(gold_contact)}
    return bool(predicted & expected)


def _clean_email(raw: str) -> str:
    value = re.sub(r"\s+", "", raw.strip().strip(".;,()[]"))
    value = value.replace("mailto:", "")
    return value


def extract_email_from_pdf(doc: ParsedDocument) -> FieldValue:
    text = _text(doc)
    candidates = extract_email_candidates(text)
    if not candidates:
        return FieldValue(field_name="corresponding_author_email", value="NR", code="NR", confidence=0.0, needs_review=True, reason="No email found in PDF text")
    email = candidates[0]
    chunk = next((c for c in doc.chunks if "@" in c.text or email.split("@")[0] in c.text), doc.chunks[0] if doc.chunks else None)
    evidence = []
    if chunk:
        evidence.append(EvidenceSpan(
            evidence_id="META_EMAIL",
            study_id=doc.study_id,
            entity_type="study",
            entity_id=doc.study_id,
            field_name="corresponding_author_email",
            extracted_value=email,
            normalized_value=email,
            code=email,
            evidence_text=chunk.text[:420],
            page=chunk.page,
            section=chunk.section,
            confidence=0.75,
            needs_review=True,
            review_reason="Email extracted from PDF text; verify spacing/author association",
            extractor_version="metadata-0.1",
        ))
    return FieldValue(field_name="corresponding_author_email", value=email, code=email, evidence=evidence, confidence=0.75, needs_review=True, reason="Email extracted from PDF")


def extract_doi_from_pdf(doc: ParsedDocument) -> FieldValue:
    text = _text(doc)
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text)
    if not match:
        return FieldValue(field_name="doi", value="NR", code="NR", confidence=0.0, needs_review=True, reason="No DOI found in PDF text")
    doi = match.group(0).rstrip(".);,")
    chunk = next((c for c in doc.chunks if doi[:12] in c.text), doc.chunks[0] if doc.chunks else None)
    evidence = []
    if chunk:
        evidence.append(EvidenceSpan(
            evidence_id="META_DOI",
            study_id=doc.study_id,
            entity_type="study",
            entity_id=doc.study_id,
            field_name="doi",
            extracted_value=doi,
            normalized_value=doi,
            code=doi,
            evidence_text=chunk.text[:420],
            page=chunk.page,
            section=chunk.section,
            confidence=0.8,
            needs_review=True,
            review_reason="DOI extracted from PDF text",
            extractor_version="metadata-0.1",
        ))
    return FieldValue(field_name="doi", value=doi, code=doi, evidence=evidence, confidence=0.8, needs_review=True, reason="DOI extracted from PDF")


def _crossref_request(url: str) -> dict[str, Any]:
    timeout = float(os.getenv("ARTICLE_AGENT_METADATA_TIMEOUT", "8"))
    mailto = os.getenv("CROSSREF_MAILTO") or os.getenv("UNPAYWALL_EMAIL") or "article-agent@example.com"
    headers = {
        "Accept": "application/json",
        "User-Agent": f"Article-Agent/0.3 (mailto:{mailto})",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as urllib_error:
        # Windows Anaconda OpenSSL can fail behind some proxies while the
        # installed curl.exe (Schannel) can reach the same endpoint.
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            raise urllib_error
        completed = subprocess.run(
            [curl, "--silent", "--show-error", "--fail", "--location",
             "--max-time", str(max(1, int(timeout))),
             "-H", f"Accept: {headers['Accept']}",
             "-H", f"User-Agent: {headers['User-Agent']}", url],
            check=True,
            capture_output=True,
            timeout=timeout + 2,
        )
        return json.loads(completed.stdout.decode("utf-8"))


def _normalize_doi(value: str | None) -> str:
    doi = str(value or "").strip()
    doi = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi\s*:\s*", "", doi, flags=re.I)
    return doi.strip().rstrip(".,;:)]}")


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def lookup_crossref(title: str | None = None, doi: str | None = None) -> dict[str, Any] | None:
    try:
        normalized_doi = _normalize_doi(doi)
        if normalized_doi and normalized_doi.upper() != "NR":
            url = "https://api.crossref.org/works/" + urllib.parse.quote(normalized_doi, safe="")
            data = _crossref_request(url)
            message = data.get("message")
            return message if isinstance(message, dict) else None
        if title and title != "NR":
            qs = urllib.parse.urlencode({"query.title": title, "rows": 3})
            data = _crossref_request(f"https://api.crossref.org/works?{qs}")
            items = data.get("message", {}).get("items", [])
            if not isinstance(items, list):
                return None
            target = _normalize_title(title)
            scored = [
                (
                    SequenceMatcher(None, target, _normalize_title((item.get("title") or [""])[0])).ratio(),
                    item,
                )
                for item in items
                if isinstance(item, dict)
            ]
            if not scored:
                return None
            score, message = max(scored, key=lambda pair: pair[0])
            return message if score >= 0.88 else None
    except Exception:
        return None
    return None


def _author_name(author: dict[str, Any]) -> str:
    given = author.get("given", "")
    family = author.get("family", "")
    name = " ".join(part for part in [given, family] if part).strip()
    return name or author.get("name", "") or "NR"



def _request_json(url: str) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "article-agent-mvp/0.1 (mailto:unknown@example.com)"})
        with urllib.request.urlopen(req, timeout=float(os.getenv("ARTICLE_AGENT_METADATA_TIMEOUT", "8"))) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _request_text(url: str, max_bytes: int = 1_000_000) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "article-agent-mvp/0.1 (mailto:unknown@example.com)"})
        with urllib.request.urlopen(req, timeout=float(os.getenv("ARTICLE_AGENT_METADATA_TIMEOUT", "8"))) as response:
            ctype = response.headers.get("Content-Type", "")
            if "pdf" in ctype.lower():
                return None
            raw = response.read(max_bytes)
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_email_from_text(text: str) -> str | None:
    if not text:
        return None
    decoded = unescape(text)
    decoded = decoded.replace("[at]", "@").replace("(at)", "@").replace(" at ", " @ ")
    decoded = decoded.replace("[dot]", ".").replace("(dot)", ".")
    compact = re.sub(r"\s+(?=[.@])|(?<=[.@])\s+", "", decoded)
    match = re.search(r"[A-Za-z0-9._%+\-]+\s*@\s*[A-Za-z0-9.\-]+\s*\.\s*[A-Za-z]{2,}", compact)
    return _clean_email(match.group(0)) if match else None


def lookup_unpaywall(doi: str | None) -> dict[str, Any] | None:
    if not doi or doi == "NR":
        return None
    email = os.getenv("UNPAYWALL_EMAIL") or "article-agent@example.com"
    url = "https://api.unpaywall.org/v2/" + urllib.parse.quote(doi, safe="") + "?" + urllib.parse.urlencode({"email": email})
    return _request_json(url)


def lookup_europe_pmc(title: str | None = None, doi: str | None = None) -> dict[str, Any] | None:
    query = None
    if doi and doi != "NR":
        query = f'DOI:"{doi}"'
    elif title and title != "NR":
        query = f'TITLE:"{title}"'
    if not query:
        return None
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode({"query": query, "format": "json", "pageSize": 1})
    data = _request_json(url)
    results = (data or {}).get("resultList", {}).get("result", [])
    return results[0] if results else None


def candidate_fulltext_urls(unpaywall: dict[str, Any] | None, europe_pmc: dict[str, Any] | None) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    if unpaywall:
        best = unpaywall.get("best_oa_location") or {}
        for key in ["url_for_landing_page", "url_for_pdf"]:
            if best.get(key):
                urls.append(("unpaywall", best[key]))
        for loc in unpaywall.get("oa_locations") or []:
            for key in ["url_for_landing_page", "url_for_pdf"]:
                if loc.get(key):
                    urls.append(("unpaywall", loc[key]))
    if europe_pmc:
        pmcid = europe_pmc.get("pmcid")
        if pmcid:
            urls.append(("europe_pmc", f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"))
            urls.append(("europe_pmc", f"https://europepmc.org/article/PMC/{pmcid.replace('PMC','')}"))
        doi = europe_pmc.get("doi")
        if doi:
            urls.append(("europe_pmc", "https://doi.org/" + doi))
    seen=set(); dedup=[]
    for source,url in urls:
        if url not in seen:
            seen.add(url); dedup.append((source,url))
    return dedup[:6]


def lookup_email_from_external_fulltext(unpaywall: dict[str, Any] | None, europe_pmc: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:
    for source, url in candidate_fulltext_urls(unpaywall, europe_pmc):
        html = _request_text(url)
        email = _extract_email_from_text(html or "")
        if email:
            return email, source, url
    return None, None, None


def external_email_field(study_id: str, email: str, source: str, url: str) -> FieldValue:
    ev = EvidenceSpan(
        evidence_id="META_EMAIL_EXTERNAL",
        study_id=study_id,
        entity_type="study",
        entity_id=study_id,
        field_name="corresponding_author_email",
        extracted_value=email,
        normalized_value=email,
        code=email,
        evidence_text=f"Email retrieved from {source} full text/landing page: {url}",
        page="external",
        section="metadata",
        confidence=0.86,
        needs_review=False,
        review_reason=f"External metadata/fulltext source: {source}",
        extractor_version="metadata-0.2",
    )
    return FieldValue(field_name="corresponding_author_email", value=email, code=email, evidence=[ev], confidence=0.86, needs_review=False, reason=f"Email retrieved from {source}")

def enrich_study_metadata(doc: ParsedDocument, study: StudyRecord, use_external: bool) -> tuple[StudyRecord, dict[str, Any]]:
    baml_result, baml_status = _baml_metadata(doc)
    vision_result, vision_status = _vision_first_page_metadata(doc) if use_external else (None, "vision_not_requested")
    email = extract_email_from_pdf(doc)
    doi = extract_doi_from_pdf(doc)
    if vision_result:
        vdoi = str(vision_result.get("doi") or "NR").strip().rstrip(".,;)")
        if vdoi.lower() != "nr" and re.fullmatch(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", vdoi):
            doi.value = vdoi; doi.code = vdoi; doi.confidence = max(doi.confidence, 0.82); doi.needs_review = True
            doi.reason = "DOI read from first-page image; pending Crossref confirmation"
    study.corresponding_author_email = email
    study.doi = doi
    # Conservative PDF fallback: first author often follows title on page 1.
    pdf_text = _text(doc)
    first_author = "NR"
    title = str(study.title.value or "")
    if title and title in pdf_text:
        after = pdf_text.split(title, 1)[1][:250]
        m = re.search(r"([A-Z][A-Za-z\-]+\s+[A-Z][A-Za-z\-]+)", after)
        if m:
            first_author = m.group(1)
    source = "pdf"
    if vision_result:
        v_author = str(vision_result.get("first_author") or "NR").strip()
        if v_author and v_author != "NR": first_author = v_author; source = "vision"
        v_contact = str(vision_result.get("author_contact") or "NR").strip()
        if v_contact != "NR" and "@" in v_contact:
            email = FieldValue(field_name="corresponding_author_email", value=_clean_email(v_contact), code=_clean_email(v_contact), confidence=0.78, needs_review=True, reason="Email read from first-page image; verify with external metadata")
    if baml_result is not None:
        if baml_result.first_author not in ("", "NR"):
            first_author = baml_result.first_author
            source = "baml"
        if baml_result.author_contact not in ("", "NR") and "@" in baml_result.author_contact:
            email = FieldValue(field_name="corresponding_author_email", value=baml_result.author_contact, code=baml_result.author_contact, confidence=0.8, needs_review=True, reason="Email extracted by Metadata BAML skill")
    metadata = None
    unpaywall = None
    europe_pmc = None
    external_email = None
    external_email_source = None
    external_email_url = None
    if use_external:
        observed_title = str((vision_result or {}).get("title") or "").strip() or str((baml_result.title if baml_result else "") or "").strip() or str(study.title.value or "")
        metadata = lookup_crossref(observed_title, str(doi.value or ""))
        crossref_verified = False
        title_similarity = 0.0
        if metadata:
            crossref_doi = _normalize_doi(metadata.get("DOI"))
            candidate_doi = _normalize_doi(str(doi.value or ""))
            crossref_verified = bool(crossref_doi and candidate_doi and crossref_doi.lower() == candidate_doi.lower())
            crossref_title = str((metadata.get("title") or [""])[0]).strip()
            title_similarity = SequenceMatcher(None, _normalize_title(observed_title), _normalize_title(crossref_title)).ratio() if crossref_title else 0.0
            if crossref_verified and crossref_title:
                study.title = FieldValue(field_name="title", value=crossref_title, code=crossref_title, confidence=0.98, needs_review=False, reason=f"Title confirmed by Crossref DOI; source title similarity={title_similarity:.3f}")
            authors = metadata.get("author") or []
            if authors and crossref_verified:
                first_author = _author_name(authors[0])
                source = "crossref"
            if crossref_verified:
                # A DOI-verified Crossref record is the authoritative
                # bibliographic source. Replace conflicting low-confidence
                # PDF/BAML values rather than preserving a stale candidate.
                published = metadata.get("published") or metadata.get("published-print") or metadata.get("published-online") or {}
                parts = published.get("date-parts") or []
                if parts and parts[0] and parts[0][0]:
                    study.year = FieldValue(
                        field_name="year", value=int(parts[0][0]), code=str(parts[0][0]),
                        confidence=0.99, needs_review=False,
                        reason="Publication year confirmed by Crossref DOI",
                    )
            if metadata.get("DOI") and doi.value == "NR":
                doi.value = metadata.get("DOI")
                doi.code = doi.value
                doi.confidence = 0.85
                doi.reason = "DOI retrieved from Crossref by title"
            if metadata.get("container-title") and crossref_verified:
                titles = metadata.get("container-title") or []
                if titles:
                    study.journal = FieldValue(
                        field_name="journal", value=unescape(str(titles[0])).strip(),
                        code=unescape(str(titles[0])).strip(), confidence=0.99,
                        needs_review=False, reason="Journal confirmed by Crossref DOI",
                    )
        unpaywall = lookup_unpaywall(str(doi.value or ""))
        europe_pmc = lookup_europe_pmc(str(study.title.value or ""), str(doi.value or ""))
        external_email, external_email_source, external_email_url = lookup_email_from_external_fulltext(unpaywall, europe_pmc)
        if external_email:
            email = external_email_field(doc.study_id, external_email, external_email_source or "external", external_email_url or "")
    evidence = []
    if doc.chunks:
        evidence.append(EvidenceSpan(
            evidence_id="META_AUTHOR",
            study_id=doc.study_id,
            entity_type="study",
            entity_id=doc.study_id,
            field_name="first_author",
            extracted_value=first_author,
            normalized_value=first_author,
            code=first_author,
            evidence_text=(f"Crossref metadata for title/DOI" if source == "crossref" else doc.chunks[0].text[:420]),
            page="external" if source == "crossref" else doc.chunks[0].page,
            section="metadata",
            confidence=0.9 if source == "crossref" else 0.65,
            needs_review=source != "crossref",
            review_reason=f"First author source: {source}",
            extractor_version="metadata-0.1",
        ))
    study.first_author = FieldValue(field_name="first_author", value=first_author, code=first_author, evidence=evidence, confidence=0.9 if source == "crossref" else 0.65, needs_review=source != "crossref", reason=f"First author source: {source}")
    study.corresponding_author_email = email
    study.doi = doi
    return study, {
        "metadata_source": source,
        "baml_status": baml_status,
        "vision_status": vision_status,
        "crossref_used": bool(metadata),
        "crossref_doi_verified": crossref_verified if use_external else False,
        "crossref_title_similarity": title_similarity if use_external else 0.0,
        "title_source": study.title.reason,
        "unpaywall_used": bool(unpaywall),
        "europe_pmc_used": bool(europe_pmc),
        "external_email_source": external_email_source,
        "external_email_url": external_email_url,
        "doi": doi.value,
        "first_author": first_author,
        "email_found": email.value != "NR",
    }

