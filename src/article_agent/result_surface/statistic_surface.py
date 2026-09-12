"""Explicit statistic labels + structural cells, never numeric-shape inference alone."""
import re

from ..result_identity.source_context import reporting_statements

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
PAIR = re.compile(rf"^\s*({NUMBER})\s*(?:±|\+/-)\s*({NUMBER})\s*$")
PAREN_PAIR = re.compile(rf"^\s*({NUMBER})\s*\(\s*({NUMBER})\s*\)\s*$")
MEAN_SD = re.compile(r"\bmean\s*(?:±|\+/-|\(|and)\s*(?:sd\b|standard deviation\b)", re.I)
INCOMPATIBLE = re.compile(r"\bmedian\b|\bIQR\b|\bSE\b|\bstandard error\b|\bn\s*\(\s*%\s*\)", re.I)


def recognize_mean(raw_cell, header, statements=(), row_label=""):
    """Return the exact supporting cue, or abstain. Does not accept a Gold value."""
    context = header + " " + row_label
    if INCOMPATIBLE.search(context) or "%" in raw_cell:
        return None
    pair = PAIR.fullmatch(raw_cell) or PAREN_PAIR.fullmatch(raw_cell)
    if not pair:
        return None
    explicit = MEAN_SD.search(header)
    if explicit:
        return {"header": header, "reporting_statement": None, "raw_cell": raw_cell,
                "mean_scalar": pair[1], "sd_scalar": pair[2]}
    # A global statement licenses ± rows, not arbitrary parentheses/count shapes.
    supported = reporting_statements(" ".join(statements))
    if PAIR.fullmatch(raw_cell) and supported:
        return {"header": header, "reporting_statement": supported[0], "raw_cell": raw_cell,
                "mean_scalar": pair[1], "sd_scalar": pair[2]}
    return None
