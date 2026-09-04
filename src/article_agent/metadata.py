from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import os
from html import unescape
from typing import Any

from .schemas import EvidenceSpan, FieldValue, ParsedDocument, StudyRecord


def _text(doc: ParsedDocument) -> str:
    return " ".join(c.text for c in doc.chunks)


def _clean_email(raw: str) -> str:
    value = re.sub(r"\s+", "", raw.strip().strip(".;,()[]"))
    value = value.replace("mailto:", "")
    return value


def extract_email_from_pdf(doc: ParsedDocument) -> FieldValue:
    text = _text(doc)
    # Also tolerate PDFs that insert spaces around dots.
    compact = re.sub(r"\s+(?=[.@])|(?<=[.@])\s+", "", text)
    match = re.search(r"[A-Za-z0-9._%+\-]+\s*@\s*[A-Za-z0-9.\-]+\s*\.\s*[A-Za-z]{2,}", compact)
    if not match:
        return FieldValue(field_name="corresponding_author_email", value="NR", code="NR", confidence=0.0, needs_review=True, reason="No email found in PDF text")
    email = _clean_email(match.group(0))
    # Multi-column PDFs sometimes split the local part, e.g. "jorgef.vas. ... sspa@domain".
    before_at = text[max(0, text.find("@") - 160): text.find("@")]
    prefix_matches = re.findall(r"([A-Za-z][A-Za-z0-9._%+\-]*\.)\s+", before_at)
    if prefix_matches and not email.lower().startswith(prefix_matches[-1].lower().rstrip(".")):
        email = _clean_email(prefix_matches[-1] + email)
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
    req = urllib.request.Request(url, headers={"User-Agent": "article-agent-mvp/0.1 (mailto:unknown@example.com)"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def lookup_crossref(title: str | None = None, doi: str | None = None) -> dict[str, Any] | None:
    try:
        if doi and doi != "NR":
            url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
            data = _crossref_request(url)
            return data.get("message")
        if title and title != "NR":
            qs = urllib.parse.urlencode({"query.title": title, "rows": 1})
            data = _crossref_request(f"https://api.crossref.org/works?{qs}")
            items = data.get("message", {}).get("items", [])
            return items[0] if items else None
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
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _request_text(url: str, max_bytes: int = 1_000_000) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "article-agent-mvp/0.1 (mailto:unknown@example.com)"})
        with urllib.request.urlopen(req, timeout=30) as response:
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
    email = extract_email_from_pdf(doc)
    doi = extract_doi_from_pdf(doc)
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
    metadata = None
    unpaywall = None
    europe_pmc = None
    external_email = None
    external_email_source = None
    external_email_url = None
    if use_external:
        metadata = lookup_crossref(str(study.title.value or ""), str(doi.value or ""))
        if metadata:
            authors = metadata.get("author") or []
            if authors:
                first_author = _author_name(authors[0])
                source = "crossref"
            if metadata.get("DOI") and doi.value == "NR":
                doi.value = metadata.get("DOI")
                doi.code = doi.value
                doi.confidence = 0.85
                doi.reason = "DOI retrieved from Crossref by title"
            if metadata.get("container-title") and study.journal.value in (None, "NR", ""):
                titles = metadata.get("container-title") or []
                if titles:
                    study.journal.value = titles[0]
                    study.journal.code = titles[0]
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
        "crossref_used": bool(metadata),
        "unpaywall_used": bool(unpaywall),
        "europe_pmc_used": bool(europe_pmc),
        "external_email_source": external_email_source,
        "external_email_url": external_email_url,
        "doi": doi.value,
        "first_author": first_author,
        "email_found": email.value != "NR",
    }
