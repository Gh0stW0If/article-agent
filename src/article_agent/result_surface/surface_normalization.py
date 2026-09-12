"""Conservative text surfaces. No synonyms, participant reordering or grade logic."""
import re
import unicodedata


def surface_text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def contrast_surface(value):
    # Only the punctuation of the relational token is normalized.
    return re.sub(r"\bvs\.(?=\s|$)", "vs", surface_text(value))


def contrast_parts(value):
    parts = re.split(r"\s+vs\s+", contrast_surface(value))
    return tuple(parts) if len(parts) == 2 and all(parts) else None


def normalize_contrast_conflict(field):
    """All candidates must carry the same ordered, explicit binary contrast."""
    candidates = field.conflict_candidates
    if field.status != "SOURCE_CONFLICT" or len(candidates) < 2:
        return None
    if any(not isinstance(c.value, str) or not c.evidence_ids for c in candidates):
        return None
    surfaces = [contrast_surface(c.value) for c in candidates]
    if len(set(surfaces)) != 1 or contrast_parts(surfaces[0]) is None:
        return None
    return surfaces[0]
