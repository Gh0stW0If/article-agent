"""Generic deterministic identity normalization, not value grading."""
import re
import unicodedata

from .models import Compatibility, NormalizationEvent, TimepointIdentity

_WORDS = {word: i for i, word in enumerate(
    "zero first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split())}
_UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week",
          "month": "month", "months": "month", "year": "year", "years": "year",
          "hour": "hour", "hours": "hour"}
_ANCHORS = {"surgery": "surgery", "operation": "surgery", "randomization": "randomization",
            "randomisation": "randomization", "treatment": "treatment", "baseline": "baseline",
            "treatment completion": "treatment_completion", "end of treatment": "treatment_completion"}
_STATS = {
    "mean": "mean", "mean value": "mean", "arithmetic mean": "mean", "median": "median",
    "event count": "event_count", "event_count": "event_count", "events": "event_count",
    "proportion": "proportion", "percentage": "percentage", "percent": "percentage",
    "change": "change", "change from baseline": "change", "other": "other",
    "mean difference": "mean_difference", "md": "mean_difference", "risk ratio": "risk_ratio",
    "rr": "risk_ratio", "odds ratio": "odds_ratio", "or": "odds_ratio",
}
_ANALYSIS = {"itt": "ITT", "intention-to-treat": "ITT", "intention to treat": "ITT",
    "pp": "PPS", "pps": "PPS", "per-protocol": "PPS", "per protocol": "PPS",
    "fas": "FAS", "full analysis set": "FAS", "mitt": "mITT",
    "modified itt": "mITT", "modified intention-to-treat": "mITT", "modified intention to treat": "mITT"}
_MISSING = {"", "nr", "not reported", "unresolved", "unknown", "unspecified"}


def normalize_text(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split()).strip()


def _event(field, rule, explanation, refs=()):
    return NormalizationEvent(field=field, rule=rule, explanation=explanation, source_refs=list(refs))


def normalize_timepoint(raw, structured_value=None, structured_unit=None):
    text = normalize_text(raw)
    text = re.sub(r"<[^>]+>", "", text)
    events, blockers = [], []
    if text in {"baseline", "pre-treatment", "pretreatment", "before treatment"}:
        return TimepointIdentity(kind="baseline", anchor="treatment" if text != "baseline" else None,
                                 relation="before" if text != "baseline" else None), [
            _event("timepoint", "TIMEPOINT_BASELINE_NORMALIZED", "Explicit pretreatment/baseline identity.")]
    # Anchors and relation are never stripped from the canonical representation.
    anchor, relation = None, None
    m = re.search(r"\s+(after|post|following|since|before)\s+(.+)$", text)
    if m:
        relation = "after" if m[1] in {"after", "post", "following", "since"} else "before"
        anchor_text = m[2].strip()
        anchor = _ANCHORS.get(anchor_text, anchor_text)
        text = text[:m.start()].strip()
    text = re.sub(r"^(?:at\s+)?(?:the\s+)?", "", text)
    for word, number in _WORDS.items():
        text = re.sub(rf"\b{word}\b", str(number), text)
    ordinal = re.search(r"(\d+)\s*(st|nd|rd|th|d)\b", text)
    if ordinal:
        events.append(_event("timepoint", "TIMEPOINT_ORDINAL_FORMAT_NORMALIZED",
                             "Generic ordinal/OCR suffix normalized; raw text retained."))
        text = re.sub(r"(\d+)\s*(?:st|nd|rd|th|d)\b", r"\1", text)
    parsed = re.fullmatch(r"(\d+(?:\.\d+)?)\s+(hours?|days?|weeks?|months?|years?)", text)
    reverse = re.fullmatch(r"(hours?|days?|weeks?|months?|years?)\s+(\d+(?:\.\d+)?)", text)
    number = float(parsed[1]) if parsed else float(reverse[2]) if reverse else None
    unit = _UNITS[parsed[2]] if parsed else _UNITS[reverse[1]] if reverse else None
    if structured_value is not None and normalize_text(structured_unit) in _UNITS:
        su = _UNITS[normalize_text(structured_unit)]
        if number is not None and (number != structured_value or unit != su):
            blockers.append("TIMEPOINT_STRUCTURED_TEXT_CONFLICT")
        elif number is None and text not in _MISSING:
            blockers.append("TIMEPOINT_TEXT_UNPARSED")
        else:
            number, unit = float(structured_value), su
    if number is None:
        return TimepointIdentity(anchor=anchor, relation=relation, blockers=blockers), events
    if relation == "before":
        # A measured pre-intervention interval is not a follow-up or generic baseline.
        blockers.append("TIMEPOINT_PRE_EVENT_INTERVAL_UNSUPPORTED")
    events.append(_event("timepoint", "TIMEPOINT_CANONICAL_DURATION",
                         "Duration parsed without changing its reference event."))
    return TimepointIdentity(kind="follow_up", value=number, unit=unit,
                             anchor=anchor, relation=relation, blockers=blockers), events


def compare_timepoints(a, b):
    if a.blockers or b.blockers:
        return Compatibility(status="UNKNOWN", reason="TIMEPOINT_AMBIGUOUS")
    if a.kind == "unknown" or b.kind == "unknown":
        return Compatibility(status="UNKNOWN", reason="TIMEPOINT_UNSPECIFIED")
    if a.kind != b.kind or (a.value, a.unit) != (b.value, b.unit):
        return Compatibility(status="CONTRADICTORY", reason="TIMEPOINT_CONTRADICTION")
    if a.anchor and b.anchor and (a.anchor != b.anchor or a.relation != b.relation):
        return Compatibility(status="CONTRADICTORY", reason="TIMEPOINT_ANCHOR_CONTRADICTION")
    if a.anchor != b.anchor:
        return Compatibility(status="COMPATIBLE", reason="TIMEPOINT_COMPATIBLE_UNSPECIFIED_ANCHOR")
    return Compatibility(status="EXACT", reason="TIMEPOINT_NORMALIZED_EQUIVALENT")


def normalize_statistic(raw, source_rows=()):
    key = normalize_text(raw)
    current = _STATS.get(key, key if key not in _MISSING else None)
    facts = {r.statistic_kind for r in source_rows if r.statistic_kind}
    refs = sorted({s for r in source_rows for s in r.source_refs})
    if len(facts) > 1 or (facts and current not in {None, "other", *facts}):
        return current, [], ["STATISTIC_SOURCE_CONFLICT"]
    if current in {None, "other"} and len(facts) == 1:
        value = next(iter(facts))
        rule = "STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE" if value == "mean" else "STATISTIC_KIND_FROM_COUNT_PERCENT_STRUCTURE"
        return value, [_event("statistic_kind", rule, "Source reporting structure, never numeric agreement.", refs)], []
    events = [] if current == raw or current is None else [
        _event("statistic_kind", "STATISTIC_KIND_LABEL_NORMALIZED", "Exact vocabulary normalization.")]
    return current, events, []


def normalize_analysis(raw):
    key = normalize_text(raw)
    if key in _MISSING:
        return None, []
    normalized = _ANALYSIS.get(key, key)
    return normalized, [_event("analysis_set", "ANALYSIS_SET_LABEL_NORMALIZED",
                              "Exact analysis population label; ITT, PPS, FAS and mITT remain distinct.")]


def compare_qualifier(a, b, dimension):
    if a in {None, "other"} or b in {None, "other"}:
        return Compatibility(status="UNKNOWN", reason=dimension + "_UNSPECIFIED")
    return Compatibility(status="EXACT" if a == b else "CONTRADICTORY",
                         reason=dimension + ("_EXACT" if a == b else "_CONTRADICTION"))
