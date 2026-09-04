from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

from .schemas import EvidenceQuote, MetadataExtraction


DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def extract_doi(text: str) -> str | None:
    matches = DOI_PATTERN.findall(text)
    if not matches:
        return None
    return matches[0].rstrip(".,;)]}").lower()


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _year(message: dict) -> tuple[int | None, str | None]:
    for key in ("published-print", "published", "published-online", "issued"):
        parts = message.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            return int(parts[0][0]), key
    return None, None


def _request_json(url: str, timeout: int = 25) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Article-Agent/0.1 (mailto:metadata@example.invalid)",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def lookup_crossref(title: str, doi: str | None = None) -> dict:
    if doi:
        encoded = urllib.parse.quote(doi, safe="")
        body = _request_json(f"https://api.crossref.org/works/{encoded}")
        message = body["message"]
        method = "doi"
        score = 1.0
    else:
        query = urllib.parse.urlencode({
            "query.title": title,
            "rows": 3,
            "select": "DOI,title,container-title,author,published,published-print,published-online,issued,URL",
        })
        body = _request_json(f"https://api.crossref.org/works?{query}")
        candidates = body.get("message", {}).get("items", [])
        if not candidates:
            raise RuntimeError("Crossref title search returned no candidates")
        target = _normalized_title(title)
        scored = []
        for item in candidates:
            candidate_title = (item.get("title") or [""])[0]
            scored.append((SequenceMatcher(None, target, _normalized_title(candidate_title)).ratio(), item))
        score, message = max(scored, key=lambda pair: pair[0])
        if score < 0.88:
            raise RuntimeError(f"Crossref title match below threshold: {score:.3f}")
        method = "title"

    year, year_source = _year(message)
    authors = message.get("author") or []
    first_author = "NR"
    if authors:
        first_author = " ".join(part for part in (authors[0].get("given"), authors[0].get("family")) if part) or "NR"
    result = {
        "lookup_method": method,
        "match_score": score,
        "doi": str(message.get("DOI") or doi or "").lower() or None,
        "title": (message.get("title") or [None])[0],
        "journal": (message.get("container-title") or [None])[0],
        "publication_year": year,
        "publication_year_source": year_source,
        "first_author": first_author,
        "url": message.get("URL"),
    }
    return result


def enrich_metadata(
    metadata: MetadataExtraction,
    markdown: str,
    output_path: Path,
) -> tuple[MetadataExtraction, dict]:
    doi = extract_doi(markdown)
    try:
        lookup = lookup_crossref(metadata.title, doi=doi)
        lookup["status"] = "matched"
    except Exception as exc:
        lookup = {"status": "error", "doi": doi, "error": str(exc)}
        output_path.write_text(json.dumps(lookup, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata, lookup

    output_path.write_text(json.dumps(lookup, ensure_ascii=False, indent=2), encoding="utf-8")
    updates = {}
    if lookup.get("publication_year") is not None and metadata.publication_year != lookup["publication_year"]:
        updates["publication_year"] = lookup["publication_year"]
    if lookup.get("journal") and metadata.journal != lookup["journal"]:
        updates["journal"] = lookup["journal"]
    if metadata.first_author == "NR" and lookup.get("first_author"):
        updates["first_author"] = lookup["first_author"]
    if metadata.title == "NR" and lookup.get("title"):
        updates["title"] = lookup["title"]
    if not updates:
        return metadata, lookup

    quote = (
        f"Crossref DOI {lookup.get('doi')}: title={lookup.get('title')}; "
        f"container-title={lookup.get('journal')}; "
        f"{lookup.get('publication_year_source')}={lookup.get('publication_year')}"
    )
    evidence = list(metadata.evidence)
    for field_id in updates:
        evidence.append(EvidenceQuote(
            field_id=field_id,
            quote=quote,
            source="crossref",
            support_type="direct",
        ))
    return metadata.model_copy(update={**updates, "evidence": evidence}), lookup
