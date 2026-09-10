"""Explicit deterministic normalization, without clinical synonym rules."""
import unicodedata

OPERATIONS = ("unicode_nfkc", "strip", "casefold", "collapse_whitespace")


def normalize(value, operations=OPERATIONS):
    unknown = set(operations) - set(OPERATIONS)
    if unknown:
        raise ValueError(f"Unknown normalization operations: {sorted(unknown)}")
    if isinstance(value, list):
        return [normalize(item, operations) for item in value]
    if not isinstance(value, str):
        if operations:
            raise ValueError("String normalization requires a string or string list")
        return value
    for operation in operations:
        if operation == "unicode_nfkc":
            value = unicodedata.normalize("NFKC", value)
        elif operation == "strip":
            value = value.strip()
        elif operation == "casefold":
            value = value.casefold()
        else:
            value = " ".join(value.split())
    return value
