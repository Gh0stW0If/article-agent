from __future__ import annotations

import re
from dataclasses import dataclass, field


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def normalize_heading(title: str) -> str:
    low = re.sub(r"[^a-z]+", " ", title.lower()).strip()
    if "abstract" in low or low == "summary":
        return "abstract"
    if "introduction" in low or low == "background":
        return "introduction"
    if any(x in low for x in ("method", "materials", "patients and methods")):
        return "methods"
    if "result" in low or "finding" in low:
        return "results"
    if "discussion" in low:
        return "discussion"
    if "reference" in low or "bibliography" in low:
        return "references"
    return "other"


@dataclass
class RoutedMarkdown:
    sections: dict[str, list[str]] = field(default_factory=dict)
    tables: list[str] = field(default_factory=list)

    def text(self, names: tuple[str, ...], include_tables: bool = False, max_chars: int | None = None) -> str:
        """Return the complete routed text.

        ``max_chars`` remains in the signature for callers compiled against
        the early API, but it is intentionally ignored.  Truncating here can
        hide a Methods qualifier or a Results paragraph; any provider-size
        constraint must be handled by an explicit table/row/paragraph
        partition with a manifest entry.
        """
        parts: list[str] = []
        for name in names:
            parts.extend(self.sections.get(name, []))
        if include_tables:
            parts.extend(self.tables)
        text = "\n\n".join(parts)
        del max_chars
        return text


def route_markdown(markdown: str) -> RoutedMarkdown:
    routed = RoutedMarkdown()
    current = "front_matter"
    buffer: list[str] = []
    table_buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        if text:
            routed.sections.setdefault(current, []).append(text)
        buffer = []

    def flush_table() -> None:
        nonlocal table_buffer
        if table_buffer:
            routed.tables.append("\n".join(table_buffer))
            table_buffer = []

    for line in markdown.splitlines():
        match = HEADING.match(line)
        if match:
            flush_table()
            flush()
            normalized = normalize_heading(match.group(2))
            # MinerU preserves subsection headings such as "Interventions" and
            # "Statistical plan". Unknown headings inherit their enclosing
            # canonical section instead of ejecting subsequent text to "other".
            if normalized != "other":
                current = normalized
            buffer.append(line)
            continue
        if TABLE_ROW.match(line):
            table_buffer.append(line)
        else:
            flush_table()
        buffer.append(line)
    flush_table()
    flush()
    # MinerU emits reconstructed tables as HTML and may place a floating table
    # after the next top-level heading because of PDF page layout. Collect HTML
    # tables globally, then expose them only through include_tables routing.
    routed.tables.extend(re.findall(r"<table\b.*?</table>", markdown, flags=re.I | re.S))
    return routed


def contexts_for_modules(markdown: str) -> dict[str, str]:
    routed = route_markdown(markdown)
    # Section routing is intentionally lossless.  If an API cannot accept a
    # complete section, callers must partition it at paragraph/table
    # boundaries and record the partition in a manifest; this function must
    # never discard a suffix merely because it is long.
    abstract = routed.text(("abstract",))
    methods = routed.text(("methods",))
    metadata = routed.text(("front_matter", "abstract", "introduction"))

    def matching_lines(text: str, patterns: tuple[str, ...]) -> str:
        lines = []
        for line in text.splitlines():
            if any(re.search(pattern, line, re.I) for pattern in patterns):
                lines.append(line.strip())
        return "\n".join(dict.fromkeys(line for line in lines if line))

    abstract_blinding = matching_lines(abstract, (
        r"blind(?:ed|ing)?\s+to\s+participants", r"participants?.{0,50}blind",
        r"intention-to-treat\s+analysis", r"primary\s+outcome",
    ))
    timepoint_dictionary = matching_lines(methods, (
        r"baseline\s*\(T0\)", r"10\s*weeks?\s*\(T1\)", r"6\s*months?\s*\(T2\)", r"12\s*months?\s*\(T3\)",
    ))
    bibliographic_lines = matching_lines(markdown, (
        r"\bdoi\s*:\s*10\.\d{4,9}/", r"\bAcupunct\s+Med\s+20\d{2}\b", r"published online",
    ))
    return {
        "metadata": "\n\n".join(part for part in (metadata, "## Bibliographic evidence\n" + bibliographic_lines if bibliographic_lines else "") if part),
        "acupuncture": methods,
        "risk_of_bias": "\n\n".join(part for part in (methods, "## Targeted abstract blinding evidence\n" + abstract_blinding if abstract_blinding else "") if part),
        "outcomes": "\n\n".join(part for part in (
            "## Timepoint dictionary from Methods\n" + timepoint_dictionary if timepoint_dictionary else "",
            routed.text(("results",), include_tables=True),
        ) if part),
    }
