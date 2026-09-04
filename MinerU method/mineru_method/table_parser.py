from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, replace
from typing import Literal

from .schemas import EvidenceQuote, OutcomeArm, OutcomeComparison, OutcomeExtraction, OutcomeStatistic


NUMBER = r"[-−–]?\s*\d+(?:\.\d+)?"

TableCategory = Literal[
    "outcome", "safety", "subgroup", "sensitivity", "baseline", "flow", "other", "unknown"
]


@dataclass(frozen=True)
class OutcomeTableBlock:
    """One deduplicated Results table routed to the table-wise LLM pass.

    The raw table is kept for auditability, while ``prompt_text`` exposes
    every row with a stable row marker so the model cannot silently collapse
    a long table into a few representative outcomes.
    """

    table_id: str
    caption: str
    raw_table: str
    rows: tuple[str, ...]
    source: str = "html"
    header_rows: tuple[str, ...] = ()
    # ``selected_rows`` is separate from ``rows`` so the raw table remains
    # available for audit while the LLM sees only deterministic target rows.
    # ``None`` means an externally constructed block has not been classified;
    # extraction then preserves the backwards-compatible all-row behaviour.
    selected_rows: tuple[str, ...] | None = None
    selected_row_ids: tuple[str, ...] = ()
    table_category: TableCategory = "unknown"
    selection_reason: str = ""
    column_labels: tuple[str, ...] = ()
    arm_registry: tuple[str, ...] = ()
    timepoint_labels: tuple[str, ...] = ()
    statistic_columns: tuple[str, ...] = ()
    # Populated by the independent LLM routing pass.  These fields are
    # provenance only; they never alter raw table rows or outcome values.
    classification_confidence: float | None = None
    classification_model: str = ""
    # Lossless cell-level mapping for multi-level clinical outcome headers.
    # It is provenance metadata and does not replace the legacy Excel fields.
    column_map: tuple[dict[str, object], ...] = ()

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def target_rows(self) -> tuple[str, ...]:
        return self.rows if self.selected_rows is None else self.selected_rows

    @property
    def target_row_ids(self) -> tuple[str, ...]:
        if self.selected_rows is None:
            return tuple(f"{self.table_id}:r{index:03d}" for index in range(1, len(self.rows) + 1))
        if self.selected_row_ids:
            return self.selected_row_ids
        return tuple(f"{self.table_id}:r{index:03d}" for index in range(1, len(self.target_rows) + 1))

    @property
    def source_data_rows(self) -> tuple[str, ...]:
        """Return all non-header rows before routing selection is applied."""

        if self.header_rows:
            return self.rows[len(self.header_rows):]
        return self.rows

    @property
    def source_data_row_ids(self) -> tuple[str, ...]:
        """Stable IDs for every source data row, including non-target rows."""

        offset = len(self.header_rows)
        return tuple(f"{self.table_id}:r{offset + index:03d}" for index in range(1, len(self.source_data_rows) + 1))

    def classification_prompt_text(self, narrative_hint: str = "") -> str:
        """Render the full table for semantic LLM classification.

        Classification must see the table as a whole.  No keyword-based
        category decision is made here; deterministic header parsing only
        supplies structural context such as column and arm labels.
        """

        lines = [
            f"TABLE_ID: {self.table_id}",
            f"TABLE_CAPTION: {self.caption or 'NR'}",
            f"TABLE_SOURCE: {self.source}",
            "TABLE_CATEGORY: unclassified",
        ]
        if narrative_hint:
            lines.extend(["NEARBY_RESULTS_NARRATIVE:", narrative_hint.strip()])

        def render_row(row: str) -> str:
            if self.source == "html":
                cells = _cells(row)
                return " | ".join(cells) if cells else _clean(row)
            return _clean(row)

        if self.column_labels:
            lines.append("TABLE_COLUMN_LABELS (deterministically parsed; structural context only):")
            lines.append(" | ".join(self.column_labels))
        if self.arm_registry:
            lines.append("TABLE_ARM_REGISTRY (deterministically parsed labels/sample sizes; structural context only):")
            lines.append(" | ".join(self.arm_registry))
        if self.timepoint_labels:
            lines.append("TABLE_TIMEPOINT_LABELS (deterministically parsed header labels):")
            lines.append(" | ".join(self.timepoint_labels))
        if self.statistic_columns:
            lines.append("TABLE_STATISTIC_COLUMNS (deterministically parsed statistic headers):")
            lines.append(" | ".join(self.statistic_columns))
        if self.column_map:
            lines.append("TABLE_COLUMN_MAP (lossless deterministic cell mapping; do not invent mappings):")
            lines.append(json.dumps(list(self.column_map), ensure_ascii=False, separators=(",", ":")))
        if self.header_rows:
            lines.append("TABLE_HEADER_ROWS:")
            for index, row in enumerate(self.header_rows, start=1):
                lines.append(f"[HEADER {index:03d}] {render_row(row)}")
        lines.append("TABLE_ALL_DATA_ROWS (classification sees every source row):")
        for index, row in enumerate(self.source_data_rows, start=1):
            row_id = self.source_data_row_ids[index - 1]
            lines.append(f"[ROW {_row_number(row_id, index):03d}] {render_row(row)} ROW_ID={row_id}")
        if not self.source_data_rows:
            lines.append("[NO_DATA_ROWS]")
        return "\n".join(lines)

    def prompt_text(self, narrative_hint: str = "") -> str:
        lines = [
            f"TABLE_ID: {self.table_id}",
            f"SOURCE_TABLE_ID: {self.table_id.split('#part-', 1)[0]}",
            f"TABLE_CAPTION: {self.caption or 'NR'}",
            f"TABLE_SOURCE: {self.source}",
            f"TABLE_CATEGORY: {self.table_category}",
            f"TARGET_SELECTION_REASON: {self.selection_reason or 'not classified; preserve supplied rows'}",
        ]
        if narrative_hint:
            lines.extend(["NEARBY_RESULTS_NARRATIVE:", narrative_hint.strip()])
        def render_row(row: str) -> str:
            if self.source == "html":
                cells = _cells(row)
                return " | ".join(cells) if cells else _clean(row)
            return _clean(row)

        if self.column_labels:
            lines.append("TABLE_COLUMN_LABELS (deterministically parsed; do not invent new columns):")
            lines.append(" | ".join(self.column_labels))
        if self.arm_registry:
            lines.append("TABLE_ARM_REGISTRY (deterministically parsed labels/sample sizes; use only when the row supports them):")
            lines.append(" | ".join(self.arm_registry))
        if self.timepoint_labels:
            lines.append("TABLE_TIMEPOINT_LABELS (deterministically parsed header labels):")
            lines.append(" | ".join(self.timepoint_labels))
        if self.statistic_columns:
            lines.append("TABLE_STATISTIC_COLUMNS (deterministically parsed statistic headers):")
            lines.append(" | ".join(self.statistic_columns))
        if self.column_map:
            lines.append("TABLE_COLUMN_MAP (lossless deterministic cell mapping; use raw header paths and column indexes):")
            lines.append(json.dumps(list(self.column_map), ensure_ascii=False, separators=(",", ":")))
        if self.header_rows:
            lines.append("TABLE_HEADER_ROWS (context only; do not return these as outcomes):")
            for index, row in enumerate(self.header_rows, start=1):
                lines.append(f"[HEADER {index:03d}] {render_row(row)}")
            lines.append("TABLE_DATA_ROWS (return every clinically relevant row):")
        else:
            lines.append("TABLE_ROWS (return every clinically relevant data row):")
        target_rows = self.target_rows
        target_row_ids = self.target_row_ids
        for index, row in enumerate(target_rows, start=1):
            row_id = target_row_ids[index - 1] if index - 1 < len(target_row_ids) else f"{self.table_id}:r{index:03d}"
            source_number = _row_number(row_id, index)
            lines.append(f"[ROW {source_number:03d}] {render_row(row)} ROW_ID={row_id}")
        if not target_rows:
            lines.append("[NO_TARGET_ROWS] No rows selected for outcome extraction.")
        return "\n".join(lines)


def _clean(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    value = value.replace("−", "-").replace("–", "-")
    value = re.sub(r"-\s+(?=\d)", "-", value)
    return re.sub(r"\s+", " ", value).strip()


def _number(value: str) -> float:
    return float(_clean(value))


def _integer(value: str) -> int:
    return int(float(_clean(value)))


def _ci(value: str) -> tuple[float | None, float | None]:
    match = re.search(rf"({NUMBER})\s+to\s+({NUMBER})", _clean(value), re.I)
    if not match:
        return None, None
    return _number(match.group(1)), _number(match.group(2))


def _p(value: str) -> tuple[float | None, str]:
    match = re.search(r"(<=|>=|<|>)?\s*(0?\.\d+|\d+(?:\.\d+)?)", _clean(value))
    if not match:
        return None, "NR"
    return float(match.group(2)), match.group(1) or "="


def _cells(row: str) -> list[str]:
    return [_clean(cell) for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.I | re.S)]


def _cell_specs(row: str, source: str) -> list[tuple[str, int, int]]:
    """Return cell text and explicit span attributes for a table row."""

    if source == "html":
        result: list[tuple[str, int, int]] = []
        for match in re.finditer(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", row, re.I | re.S):
            attrs, body = match.group(1), match.group(2)

            def attr_int(name: str) -> int:
                found = re.search(rf"\b{name}\s*=\s*[\"']?(\d+)", attrs, re.I)
                try:
                    return max(1, int(found.group(1))) if found else 1
                except (TypeError, ValueError):
                    return 1

            result.append((_clean(body), attr_int("colspan"), attr_int("rowspan")))
        return result
    stripped = row.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [(_clean(cell.replace("\\|", "|")), 1, 1) for cell in stripped.split("|")]


def _expand_header_grid(headers: tuple[str, ...], source: str) -> list[list[str]]:
    """Expand HTML spans and retain every header level for each column."""

    grid: list[list[str]] = []
    active: dict[int, tuple[str, int]] = {}
    width = 0
    for row in headers:
        specs = _cell_specs(row, source)
        cells: dict[int, str] = {}
        column = 0

        def consume_active() -> None:
            nonlocal column
            while column in active:
                text, remaining = active[column]
                cells[column] = text
                if remaining <= 1:
                    del active[column]
                else:
                    active[column] = (text, remaining - 1)
                column += 1

        for text, colspan, rowspan in specs:
            consume_active()
            colspan = max(1, colspan)
            for offset in range(colspan):
                target = column + offset
                cells[target] = text
                if rowspan > 1:
                    active[target] = (text, rowspan - 1)
            column += colspan
        consume_active()
        width = max(width, column, *(cells.keys() or [0]), *(active.keys() or [0]))
        grid.append([cells.get(index, active.get(index, ("", 0))[0]) for index in range(width)])
    if not grid:
        return grid
    width = max(len(row) for row in grid)
    return [row + [""] * (width - len(row)) for row in grid]


def _header_timepoint(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    patterns = (
        r"\bbefore\s+treatment\b", r"\b\d+(?:\.\d+)?\s*(?:days?|weeks?|months?|years?|hours?)\s*(?:after|post)?\s*treatment?\b",
        r"\bat\s+baseline\b", r"\bbaseline\b", r"\bfollow[- ]?up\b", r"\bend\s+of\s+(?:treatment|study)\b",
        r"\b\d+(?:\.\d+)?\s*(?:days?|weeks?|months?|years?|hours?)\b", r"\bafter\s+treatment\b",
        r"\bT\d+\b", r"\bpost[- ]?treatment\b",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.I)
        if match:
            return match.group(0)
    return "NR"


def _header_arm(texts: list[str]) -> str:
    arm_terms = ("group", "arm", "acupuncture", "sham", "control", "placebo", "intervention", "treatment")
    statistic_terms = ("mean", "sd", "se", "p-value", "p value", "confidence", "ci", "md", "smd", "or", "rr", "rd", "hr")
    for text in texts:
        low = text.lower()
        if any(term in low for term in arm_terms) and low.strip() not in statistic_terms:
            return re.sub(r"\s+", " ", text).strip() or "NR"
    return "NR"


def _header_statistic(text: str) -> str:
    low = re.sub(r"\s+", " ", text.lower())
    if re.search(r"\bp\s*(?:[- ]?value)?\b|significance", low):
        return "p_value"
    if re.search(r"confidence|\bci\b", low):
        return "confidence_interval"
    if re.search(r"mean\s*[(:]?\s*sd|mean\s*[±+]\s*sd", low):
        return "mean_sd"
    if re.search(r"\b(?:mean|median)\b", low):
        return "mean_or_median"
    if re.search(r"\b(?:sd|se|iqr)\b", low):
        return "dispersion"
    if re.search(r"\b(?:change|difference|md|smd|or|rr|rd|hr|effect)\b", low):
        return "effect"
    if re.search(r"\bn\b|number|patients?|participants?", low):
        return "n"
    return "value"


def _header_analysis_set(text: str) -> str:
    """Map an explicitly printed analysis-set header to its stable label."""

    patterns = (
        (r"\bintention\s*[- ]?to\s*[- ]?treat\b|\bITT\b|\bmITT\b", "ITT"),
        (r"\bper\s*[- ]?protocol\b|\bPPS\b|\bPP\b", "PP"),
        (r"\bfull\s*analysis\s*set\b|\bFAS\b", "FAS"),
        (r"\bLOCF\b|last\s+observation\s+carried\s+forward", "LOCF"),
        (r"\bMMRM\b|mixed\s+model", "MMRM"),
    )
    for pattern, label in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return label
    return "NR"


def parse_table_column_map(headers: tuple[str, ...], source: str = "html") -> tuple[dict[str, object], ...]:
    """Build a lossless map from every header level to each data column."""

    grid = _expand_header_grid(headers, source)
    if not grid:
        return ()
    result: list[dict[str, object]] = []
    width = max(len(row) for row in grid)
    for column in range(width):
        path: list[str] = []
        for row in grid:
            value = row[column].strip() if column < len(row) else ""
            if not value or re.fullmatch(r":?-{3,}:?", value):
                continue
            if not path or value != path[-1]:
                path.append(value)
        joined = " | ".join(path)
        result.append({
            "column_index": column,
            "header_path": path,
            "raw_header": " > ".join(path) or f"column_{column + 1}",
            "arm_label": _header_arm(path),
            "timepoint_raw": _header_timepoint(joined),
            "statistic": _header_statistic(joined),
            "analysis_set": _header_analysis_set(joined),
            "header_evidence": joined or "NR",
        })
    return tuple(result)


def attach_source_cells(
    column_map: tuple[dict[str, object], ...],
    data_rows: tuple[str, ...],
    data_row_ids: tuple[str, ...],
    source: str = "html",
) -> tuple[dict[str, object], ...]:
    """Attach lossless source-cell coordinates to the header map.

    ``column_map`` describes the semantic header path for each output column.
    This companion pass records every original data-cell value and its
    row/column coordinate, including cells that the LLM may later classify as
    non-outcomes.  It is provenance metadata only: no value is inferred or
    copied between rows, arms, or time points.
    """

    if not column_map:
        return ()
    mapped = [dict(item) for item in column_map]
    for index, row in enumerate(data_rows):
        row_id = data_row_ids[index] if index < len(data_row_ids) else f"r{index + 1:03d}"
        cells = _cell_specs(row, source)
        for column_index, (value, colspan, rowspan) in enumerate(cells):
            if column_index >= len(mapped):
                # A malformed row can contain more cells than its header.  Do
                # not discard them; preserve a deterministic fallback column
                # with an empty header path so audit tooling can flag it.
                mapped.append({
                    "column_index": column_index,
                    "header_path": [],
                    "raw_header": f"column_{column_index + 1}",
                    "arm_label": "NR",
                    "timepoint_raw": "NR",
                    "statistic": "value",
                    "analysis_set": "NR",
                    "header_evidence": "NR",
                })
            source_cells = mapped[column_index].setdefault("source_cells", [])
            if not isinstance(source_cells, list):
                source_cells = []
                mapped[column_index]["source_cells"] = source_cells
            source_cells.append({
                "row_index": index,
                "row_id": row_id,
                "column_index": column_index,
                "raw_value": value,
                "colspan": colspan,
                "rowspan": rowspan,
                "coordinate": {"row": index, "column": column_index},
            })
    # Ensure every header column has an explicit (possibly empty) cell list so
    # consumers never mistake missing metadata for a silently clipped column.
    for item in mapped:
        item.setdefault("source_cells", [])
    return tuple(mapped)


def _row_number(row_id: str, fallback: int) -> int:
    match = re.search(r":r(\d+)$", str(row_id))
    return int(match.group(1)) if match else fallback


def _row_text(row: str, source: str = "html") -> str:
    if source == "html":
        return " | ".join(_cells(row)) or _clean(row)
    return _clean(row)


def _header_score(row: str, source: str = "html") -> int:
    """Score whether a row is a column header, without asking an LLM."""

    text = _row_text(row, source).lower()
    if not text:
        return 0
    score = 3 if source == "html" and re.search(r"<th\b", row, re.I) else 0
    terms = (
        r"\boutcome\b", r"\bgroup\b", r"\barm\b", r"\bvariable\b", r"\bcharacteristic\b", r"\bbaseline\b",
        r"\bweek", r"\bmonth", r"\bmean\b", r"\bsd\b", r"\bse\b", r"\bp(?:\s*value)?\b", r"\bci\b", r"\blsmd\b", r"\bestimate\b",
        r"\bconfidence\b", r"\bpatient number", r"\bintensity\b", r"\bquestionnaire\b", r"\bitems?\b", r"\btreatment\b", r"\bfollow[- ]?up\b", r"\bn\s*=",
    )
    score += sum(1 for term in terms if re.search(term, text, re.I))
    if re.search(r"n\s*=|significance|real\s+acupuncture|sham\s+acupuncture", text, re.I):
        score += 2
    # A row with mostly labels and no numeric token is more likely a header.
    if not re.search(r"[-+]?\d", text):
        score += 1
    return score


def parse_table_header_metadata(
    rows: tuple[str, ...],
    headers: tuple[str, ...],
    source: str = "html",
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Extract labels, arm/sample-size registry and statistic columns.

    This parser only copies strings and explicitly written ``n=`` values.  It
    never propagates an arm size from another table or calculates a missing
    value.  Group labels in a body ``Group`` column are retained because that
    label is an explicit cell-level fact.
    """

    header_text = " | ".join(_row_text(row, source) for row in headers)
    arm_registry: list[str] = []
    arm_header_texts = [header_text]
    # MinerU may preserve math glyphs as ``G r o u p`` and split digits as
    # ``4 9``.  Collapse only those formatting artefacts before looking for an
    # explicitly printed ``n=``; this is format normalization, not inference.
    compact_header = re.sub(r"\\[A-Za-z]+|[{}$]", " ", header_text)
    compact_header = re.sub(r"(?i)G\s+r\s+o\s+u\s+p", "Group", compact_header)
    compact_header = re.sub(r"(?i)S\s+h\s+a\s+m", "Sham", compact_header)
    compact_header = re.sub(r"(?<=\d)\s+(?=\d)", "", compact_header)
    arm_header_texts.append(compact_header)
    seen_header_matches: set[tuple[str, str]] = set()
    for arm_text in arm_header_texts:
        for match in re.finditer(r"([^|;]+?)\s*\(\s*n\s*=\s*(\d+)\s*\)", arm_text, re.I):
            label = re.sub(r"\s+", " ", match.group(1)).strip(" -:")
            token = f"{label} (n={int(match.group(2))})"
            key = (label.lower(), match.group(2))
            if key not in seen_header_matches:
                seen_header_matches.add(key)
                arm_registry.append(token)
    flattened_headers = [_row_text(row, source) for row in headers]
    last_header_cells = _cells(headers[-1]) if headers and source == "html" else []
    column_labels = tuple(last_header_cells or (flattened_headers[-1].split("|") if flattened_headers else []))
    # When no explicit n= header exists, collect unique group labels from the
    # explicit Group/Arm column in the selected body rows.
    group_index = None
    for header_row in headers:
        cells = _cells(header_row) if source == "html" else [part.strip() for part in header_row.strip().strip("|").split("|")]
        for index, cell in enumerate(cells):
            if re.fullmatch(r"(?:group|arm|treatment group|study group)", cell.strip(), re.I):
                group_index = index
                break
        if group_index is not None:
            break
    if group_index is not None:
        for row in rows:
            cells = _cells(row) if source == "html" else [part.strip() for part in row.strip().strip("|").split("|")]
            if group_index >= len(cells):
                continue
            label = re.sub(r"\s+", " ", cells[group_index]).strip()
            # HTML rowspans omit the repeated outcome/group cells.  In that
            # case a short alphabetic first cell (A/B/C) is the explicit group
            # label, while the nominal group-column position contains a
            # numeric statistic.
            if re.search(r"\d", label) and cells and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,15}", cells[0].strip()):
                label = cells[0].strip()
            if (
                label
                and not re.search(r"\d", label)
                and not re.search(r"^(?:group|arm|baseline|mean|sd|p|ci)$", label, re.I)
                and not re.search(r"(?:mean|sd|se|ci|lsmd|confidence)", label, re.I)
                and label not in arm_registry
            ):
                arm_registry.append(label)
    timepoints: list[str] = []
    for match in re.finditer(r"(?:baseline|follow[- ]?up|end of (?:treatment|study)|\b\d+\s+(?:days?|weeks?|months?|years?)\b|T\d+)", header_text, re.I):
        label = re.sub(r"\s+", " ", match.group(0)).strip()
        if label.lower() not in {item.lower() for item in timepoints}:
            timepoints.append(label)
    statistic_terms = ("mean", "sd", "se", "p", "ci", "confidence", "lsmd", "md", "smd", "or", "rr", "rd", "hr", "event", "n")
    statistic_columns = tuple(
        cell for cell in column_labels
        if any(re.search(rf"\b{re.escape(term)}\b", cell, re.I) for term in statistic_terms)
    )
    return tuple(column_labels), tuple(arm_registry), tuple(timepoints), statistic_columns


def split_table_headers(rows: tuple[str, ...], source: str = "html") -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Deterministically split headers and data while retaining raw row order.

    MinerU sometimes emits ``td`` for header cells, so relying only on ``th``
    loses the two-level headers used by clinical outcome tables.  We inspect a
    structural rows and consume consecutive high-scoring header rows; the
    rest stay untouched as data candidates. No character or row prefix is
    discarded.
    """

    if not rows:
        return (), (), ()
    # Pipe tables commonly use a separator row followed by a second semantic
    # header row.  Consume that full header stack so values such as
    # "Acupuncture / 4 weeks" remain attached to the correct columns.
    if source != "html" and len(rows) >= 2:
        def is_separator(row: str) -> bool:
            cells = _cell_specs(row, source)
            return bool(cells) and all(not re.search(r"[A-Za-z\u4e00-\u9fff]", cell[0]) and re.search(r"-{3,}", cell[0]) for cell in cells)

        separator_index = next((index for index, row in enumerate(rows) if is_separator(row)), None)
        if separator_index == 1:
            header_count = 2
            # A pipe/Markdown export can contain an arbitrary-depth header
            # stack after the separator (for example Table 2 in 2015-03 has
            # four semantic rows: analysis set, arm, statistic, then the
            # actual outcome rows).  Consume every consecutive structural
            # header row instead of stopping at a hard-coded third row.  A
            # numeric-heavy row is treated as data, so an outcome such as
            # ``PainVAS (T0-T1) | 78 | -41.2`` cannot be swallowed as a
            # header.  The raw rows remain unchanged either way.
            for candidate_index in range(2, len(rows)):
                candidate = rows[candidate_index]
                candidate_text = _row_text(candidate, source)
                if not re.search(r"[A-Za-z\u4e00-\u9fff]", candidate_text):
                    break
                numeric_count = len(re.findall(r"[-+]?\d+(?:\.\d+)?", re.sub(r"(?<=\d)\s+(?=\d)", "", candidate_text)))
                explicit_header_signal = bool(re.search(
                    r"\b(?:group|arm|variable|outcome|difference|mean|sd|se|p(?:\s*value)?|ci|confidence|estimate|n|treatment|before|after|follow[- ]?up|week|month|timepoint|F\s*\d+\s*,\s*\d+)\b",
                    candidate_text,
                    re.I,
                ))
                explicit_test_header = bool(
                    re.search(r"\bF\s*\d+\s*,\s*\d+\b", candidate_text, re.I)
                    or re.search(r"\bp\s*value\b", candidate_text, re.I)
                )
                if (
                    (_header_score(candidate, source) < 2 and not explicit_test_header)
                    or numeric_count > 12
                    or not explicit_header_signal
                ):
                    break
                header_count = candidate_index + 1
            headers = tuple(rows[:header_count])
            data_rows = tuple(rows[header_count:])
            row_ids = tuple(f"r{index:03d}" for index in range(header_count + 1, len(rows) + 1))
            return headers, data_rows, row_ids
    header_count = 0
    for index, row in enumerate(rows):
        score = _header_score(row, source)
        numeric_text = re.sub(r"(?<=\d)\s+(?=\d)", "", _row_text(row, source))
        numeric_count = len(re.findall(r"[-+]?\d+(?:\.\d+)?", numeric_text))
        # An explicit ``n=`` header is a strong signal even when a table has
        # four or more arms (and therefore more than three numeric tokens).
        # The previous numeric cutoff treated those multi-arm headers as data.
        explicit_header_signal = bool(re.search(r"\bn\s*=|\b(?:group|arm|variable|outcome)\b", _row_text(row, source), re.I))
        header_candidate = score >= 2 and (
            bool(re.search(r"<th\b", row, re.I))
            or numeric_count <= 3
            or explicit_header_signal and numeric_count <= 12
        )
        if index == 0 and header_candidate:
            header_count = 1
            continue
        if header_count and header_candidate:
            header_count = index + 1
            continue
        break
    headers = tuple(rows[:header_count])
    data_rows = tuple(rows[header_count:])
    row_ids = tuple(f"r{index:03d}" for index in range(header_count + 1, len(rows) + 1))
    return headers, data_rows, row_ids


def classify_outcome_table(caption: str, rows: tuple[str, ...], source: str = "html") -> tuple[TableCategory, str]:
    """Classify a table before any outcome LLM call.

    The classifier is intentionally conservative and evidence-based.  It is a
    routing hint, not a claim about the medical meaning of an otherwise
    ambiguous table; ambiguous tables are retained as ``unknown``.
    """

    text = f"{caption} {' '.join(_row_text(row, source) for row in rows)}".lower()
    baseline_markers = (
        r"\bage\b", r"\bsex\b", r"\bmale\b", r"\bfemale\b", r"\bsmoking\b",
        r"family history", r"\bmarital\b", r"\beducation\b", r"\boccupation\b",
    )
    outcome_markers = ("outcome", "score", "follow-up", "mean difference", "confidence interval", "lsmd")
    if sum(bool(re.search(marker, text, re.I)) for marker in baseline_markers) >= 2 and not any(marker in text for marker in outcome_markers):
        return "baseline", "early rows contain demographic/baseline variables without outcome statistics"
    rules: tuple[tuple[TableCategory, tuple[str, ...], str], ...] = (
        ("baseline", ("baseline characteristics", "sociodemographic", "participant characteristics", "demographic"), "caption/header identifies baseline or participant characteristics"),
        ("flow", ("consort", "flow of participants", "screened", "randomized", "allocated"), "caption/header identifies participant flow"),
        ("safety", ("adverse event", "adverse effects", "serious adverse", "causal relationship", "treatment-related", "action related to the intervention"), "caption/header identifies safety or adverse-event data"),
        ("subgroup", ("subgroup", "interaction", "cfs group", "icf group"), "caption/header identifies subgroup or interaction analysis"),
        ("sensitivity", ("sensitivity analysis", "sensitivity", "locf sensitivity"), "caption/header identifies a sensitivity analysis"),
        ("outcome", ("outcome", "result", "follow-up", "mean", "lsmd", "confidence interval", "p value", "p^", "score"), "caption/header contains clinical outcome statistics"),
    )
    for category, needles, reason in rules:
        if any(needle in text for needle in needles):
            return category, reason
    return "unknown", "no deterministic table-type signal; retain for review"


def select_target_rows(
    rows: tuple[str, ...],
    headers: tuple[str, ...],
    category: TableCategory,
    source: str = "html",
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """Select clinically relevant rows after table classification.

    Raw rows are never deleted from the block.  Baseline/flow/other/unknown
    tables are kept for audit but do not trigger outcome calls until a human
    or a future classifier supplies a positive target signal.  Safety,
    subgroup, sensitivity and outcome rows remain eligible, with their role
    conveyed in the prompt.
    """

    if category in {"baseline", "flow", "other", "unknown"}:
        return (), (), f"table category={category}; no outcome target rows selected"
    selected: list[str] = []
    selected_ids: list[str] = []
    normalized_headers = {
        re.sub(r"\s+", " ", _row_text(row, source)).strip().lower()
        for row in headers
    }
    for index, row in enumerate(rows, start=1):
        text = _row_text(row, source)
        if not text or not re.search(r"[A-Za-z\u4e00-\u9fff]", text):
            continue
        # Long MinerU tables occasionally repeat the header after a page
        # break.  Drop only an exact normalized header copy; all other raw
        # rows remain eligible and are retained in ``OutcomeTableBlock.rows``.
        normalized_text = re.sub(r"\s+", " ", text).strip().lower()
        if normalized_text in normalized_headers:
            continue
        # A repeated header or separator inside a long table is not a data row.
        if _header_score(row, source) >= 4 and not re.search(r"[-+]?\d", text):
            continue
        selected.append(row)
        selected_ids.append(f"r{len(headers) + index:03d}")
    return tuple(selected), tuple(selected_ids), f"category={category}; excluded blank and repeated header rows"


def prepare_outcome_table_block(
    table_id: str,
    caption: str,
    raw_table: str,
    rows: tuple[str, ...],
    source: str = "html",
    *,
    defer_classification: bool = False,
) -> OutcomeTableBlock:
    """Build a table block with structural metadata.

    The legacy/default path still performs deterministic classification for
    callers that explicitly rely on the old helper.  Production extraction
    passes ``defer_classification=True`` and routes the block through the LLM
    classifier before selecting target rows; this keeps keyword heuristics out
    of the active pipeline.
    """

    headers, data_rows, _data_ids = split_table_headers(rows, source)
    column_labels, arm_registry, timepoint_labels, statistic_columns = parse_table_header_metadata(data_rows, headers, source)
    column_map = attach_source_cells(
        parse_table_column_map(headers, source),
        data_rows,
        tuple(f"{table_id}:r{index:03d}" for index in range(len(headers) + 1, len(rows) + 1)),
        source,
    )
    if column_map:
        # Use the combined parent/child labels for downstream prompts while
        # retaining the legacy metadata tuple for compatibility.
        column_labels = tuple(str(item.get("raw_header") or "") for item in column_map)
    # ``rNNN`` IDs from ``select_target_rows`` are relative to the raw table;
    # selected rows preserve those IDs after blank/header filtering.
    labels = tuple(_row_text(row, source) for row in headers[-1:])
    if defer_classification:
        category = "unknown"
        selected_rows: tuple[str, ...] = ()
        selected_ids: tuple[str, ...] = ()
        selection_reason = "awaiting LLM semantic table classification"
    else:
        category, classification_reason = classify_outcome_table(caption, rows, source)
        selected_rows, selected_ids, selection_reason = select_target_rows(data_rows, headers, category, source)
        selection_reason = f"{classification_reason}; {selection_reason}"
    return OutcomeTableBlock(
        table_id=table_id,
        caption=caption,
        raw_table=raw_table,
        rows=rows,
        source=source,
        header_rows=headers,
        selected_rows=selected_rows,
        selected_row_ids=tuple(f"{table_id}:{row_id}" for row_id in selected_ids),
        table_category=category,
        selection_reason=selection_reason,
        column_labels=column_labels or labels,
        arm_registry=arm_registry,
        timepoint_labels=timepoint_labels,
        statistic_columns=statistic_columns,
        column_map=column_map,
    )


def apply_table_classification(
    block: OutcomeTableBlock,
    category: TableCategory,
    rationale: str,
    *,
    confidence: float | None = None,
    model: str = "",
) -> OutcomeTableBlock:
    """Apply an LLM table category, then perform structural row selection.

    The LLM decides only the semantic table type.  Header splitting, blank or
    repeated-header filtering, and stable row-ID construction remain
    deterministic and are performed after that decision.  Raw rows are never
    discarded from ``block.rows``.
    """

    selected_rows, selected_ids, selection_reason = select_target_rows(
        block.source_data_rows,
        block.header_rows,
        category,
        block.source,
    )
    normalized_rationale = re.sub(r"\s+", " ", str(rationale or "NR")).strip() or "NR"
    reason = f"LLM classification ({category}): {normalized_rationale}; {selection_reason}"
    return replace(
        block,
        selected_rows=selected_rows,
        selected_row_ids=tuple(
            row_id if row_id.startswith(f"{block.table_id}:") else f"{block.table_id}:{row_id}"
            for row_id in selected_ids
        ),
        table_category=category,
        selection_reason=reason,
        classification_confidence=confidence,
        classification_model=model,
    )


def _caption_before(context: str, start: int) -> str:
    """Find the nearest Markdown table caption before an HTML table."""
    prefix = context[max(0, start - 500):start]
    candidates = re.findall(
        r"(?im)^\s*((?:eTable|Supplementary\s+Table|Table)\s+[A-Za-z0-9][^\n<]*)",
        prefix,
    )
    if not candidates:
        return ""
    return re.sub(r"\s+", " ", candidates[-1]).strip(" -*")


def _caption_id(caption: str, ordinal: int) -> str:
    match = re.search(r"(?i)(eTable|Supplementary\s+Table|Table)\s+([A-Za-z0-9.-]+)", caption)
    if match:
        token = re.sub(r"\s+", "-", f"{match.group(1)}-{match.group(2)}").strip(".")
        return token.lower()
    return f"table-{ordinal:03d}"


def extract_outcome_table_blocks(
    context: str,
    *,
    defer_classification: bool = False,
) -> list[OutcomeTableBlock]:
    """Return every unique HTML/Markdown table in the routed Results context.

    ``contexts_for_modules`` may contain the same HTML table twice: once in
    the Results section and once in the global table collection.  Deduplication
    here prevents duplicate API calls while retaining the original order.
    Pipe tables are included for explicit PyMuPDF fallback output.
    """
    blocks: list[OutcomeTableBlock] = []
    seen: set[str] = set()
    ordinal = 0

    for match in re.finditer(r"<table\b.*?</table>", context, re.I | re.S):
        raw_table = match.group(0).strip()
        key = re.sub(r"\s+", " ", raw_table).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        rows = tuple(re.findall(r"<tr\b[^>]*>.*?</tr>", raw_table, re.I | re.S))
        if not rows:
            continue
        ordinal += 1
        caption = _caption_before(context, match.start())
        base_id = _caption_id(caption, ordinal)
        existing = {block.table_id for block in blocks}
        table_id = base_id
        suffix = 2
        while table_id in existing:
            table_id = f"{base_id}-{suffix}"
            suffix += 1
        blocks.append(prepare_outcome_table_block(
            table_id,
            caption,
            raw_table,
            rows,
            "html",
            defer_classification=defer_classification,
        ))

    pipe_lines = context.splitlines()
    index = 0
    while index < len(pipe_lines):
        line = pipe_lines[index]
        if not (line.strip().startswith("|") and line.strip().endswith("|")):
            index += 1
            continue
        start = index
        while index < len(pipe_lines) and pipe_lines[index].strip().startswith("|") and pipe_lines[index].strip().endswith("|"):
            index += 1
        group = pipe_lines[start:index]
        if len(group) < 2 or not any(re.search(r"\|\s*:?-{3,}", item) for item in group):
            continue
        raw_table = "\n".join(group).strip()
        key = re.sub(r"\s+", " ", raw_table).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        ordinal += 1
        # A caption may be on the immediately preceding non-table line.
        prefix = "\n".join(pipe_lines[max(0, start - 4):start])
        caption_candidates = re.findall(
            r"(?im)^\s*((?:eTable|Supplementary\s+Table|Table)\s+[A-Za-z0-9][^\n]*)",
            prefix,
        )
        caption = re.sub(r"\s+", " ", caption_candidates[-1]).strip(" -*") if caption_candidates else ""
        base_id = _caption_id(caption, ordinal)
        existing = {block.table_id for block in blocks}
        table_id = base_id
        suffix = 2
        while table_id in existing:
            table_id = f"{base_id}-{suffix}"
            suffix += 1
        blocks.append(prepare_outcome_table_block(
            table_id,
            caption,
            raw_table,
            tuple(group),
            "markdown",
            defer_classification=defer_classification,
        ))

    return blocks


def _timepoint(label: str, context: str) -> tuple[float | None, int | None, str | None]:
    match = re.search(r"T0\s*[-–]\s*(T[123])", label, re.I)
    if not match:
        return None, None, None
    code = match.group(1).upper()
    patterns = {
        "T1": (r"(?:10\s*weeks?\s*\(T1\)|\(T1\)[^\n.]{0,30}10\s*weeks?)", 10.0, 4, "Methods maps T1 to 10 weeks"),
        "T2": (r"(?:6\s*months?\s*\(T2\)|\(T2\)[^\n.]{0,30}6\s*months?)", 6.0, 2, "Methods maps T2 to 6 months"),
        "T3": (r"(?:12\s*months?\s*\(T3\)|\(T3\)[^\n.]{0,30}12\s*months?)", 12.0, 2, "Methods maps T3 to 12 months"),
    }
    pattern, value, unit, derivation = patterns[code]
    return (value, unit, derivation) if re.search(pattern, context, re.I) else (None, None, None)


def _evidence(field_id: str, quote: str, *, derivation: str | None = None) -> EvidenceQuote:
    return EvidenceQuote(
        field_id=field_id,
        quote=quote,
        page=None,
        source="table" if derivation is None else "markdown",
        support_type="derived" if derivation else "direct",
        derivation=derivation,
    )


def _timepoint_quote(label: str, context: str) -> str:
    code_match = re.search(r"T0\s*[-–]\s*(T[123])", label, re.I)
    if not code_match:
        return label
    code = code_match.group(1)
    line = next((line.strip() for line in context.splitlines() if re.search(rf"\({code}\)", line, re.I)), "")
    return f"{label}; {line}" if line else label


def _parse_html_tables(context: str) -> list[OutcomeStatistic]:
    target = None
    for table in re.findall(r"<table\b.*?</table>", context, re.I | re.S):
        cleaned = _clean(table)
        if "PainVAS (T0-T1)" in cleaned and "Per protocol" in cleaned:
            target = table
            break
    if target is None:
        return []

    header = _clean(target)
    itt_n = re.search(r"Acupuncture\s+n\s*=\s*(\d+).*?Sham\s+n\s*=\s*(\d+)", header, re.I)
    itt_intervention_n = int(itt_n.group(1)) if itt_n else None
    itt_control_n = int(itt_n.group(2)) if itt_n else None
    outcomes: list[OutcomeStatistic] = []
    for row_index, row in enumerate(re.findall(r"<tr\b[^>]*>.*?</tr>", target, re.I | re.S), start=1):
        cells = _cells(row)
        if len(cells) < 15 or not re.match(r"PainVAS\s*\(T0[–-]T[123]\)", cells[0], re.I):
            continue
        label = cells[0]
        time_value, time_unit, derivation = _timepoint(label, context)
        pp_il, pp_iu = _ci(cells[3])
        pp_cl, pp_cu = _ci(cells[6])
        pp_p, pp_comp = _p(cells[7])
        itt_il, itt_iu = _ci(cells[9])
        itt_cl, itt_cu = _ci(cells[11])
        itt_p, itt_comp = _p(cells[12])
        row_quote = " | ".join(cells)
        time_evidence = []
        if derivation:
            time_evidence = [_evidence(
                "outcome_observation_timepoint_value",
                _timepoint_quote(label, context),
                derivation=derivation,
            )]
        outcomes.append(OutcomeStatistic(
            table_id="painvas-primary",
            row_id=f"painvas-primary:r{row_index:03d}",
            outcome_name="PainVAS",
            measurement_instrument="PainVAS 0-100 mm",
            outcome_observation_timepoint_raw=label,
            outcome_observation_timepoint_value=time_value,
            outcome_observation_timepoint_unit=time_unit,
            statistic_type="continuous",
            analysis_population="ITT",
            intervention_estimate=_number(cells[8]),
            intervention_variance_lower=itt_il,
            intervention_variance_upper=itt_iu,
            intervention_n=itt_intervention_n,
            control_estimate=_number(cells[10]),
            control_variance_lower=itt_cl,
            control_variance_upper=itt_cu,
            control_n=itt_control_n,
            between_group_measure="SMD",
            outcome_between_group_estimate=_number(cells[13]),
            outcome_p_value=itt_p,
            outcome_p_value_comparator=itt_comp,
            effect_size_name="Cohen's d",
            arm=[
                OutcomeArm(arm_id="intervention", arm_label="Acupuncture", role="intervention", n=itt_intervention_n, estimate=_number(cells[8]), lower=itt_il, upper=itt_iu),
                OutcomeArm(arm_id="control", arm_label="Sham", role="control", n=itt_control_n, estimate=_number(cells[10]), lower=itt_cl, upper=itt_cu),
            ],
            comparison=OutcomeComparison(
                relation="intervention_vs_control",
                intervention_arm_id="intervention",
                control_arm_id="control",
                comparator_arm_ids=["control"],
                contrast="Acupuncture vs Sham",
            ),
            analysis_set="ITT",
            record_role="primary",
            evidence=[_evidence("intervention_estimate", row_quote), *time_evidence],
        ))
        outcomes.append(OutcomeStatistic(
            table_id="painvas-primary",
            row_id=f"painvas-primary:r{row_index:03d}:pp",
            outcome_name="PainVAS",
            measurement_instrument="PainVAS 0-100 mm",
            outcome_observation_timepoint_raw=label,
            outcome_observation_timepoint_value=time_value,
            outcome_observation_timepoint_unit=time_unit,
            statistic_type="continuous",
            analysis_population="PP",
            intervention_estimate=_number(cells[2]),
            intervention_variance_lower=pp_il,
            intervention_variance_upper=pp_iu,
            intervention_n=_integer(cells[1]),
            control_estimate=_number(cells[5]),
            control_variance_lower=pp_cl,
            control_variance_upper=pp_cu,
            control_n=_integer(cells[4]),
            between_group_measure="NR",
            outcome_p_value=pp_p,
            outcome_p_value_comparator=pp_comp,
            effect_size_name="NR",
            arm=[
                OutcomeArm(arm_id="intervention", arm_label="Acupuncture", role="intervention", n=_integer(cells[1]), estimate=_number(cells[2]), lower=pp_il, upper=pp_iu),
                OutcomeArm(arm_id="control", arm_label="Sham", role="control", n=_integer(cells[4]), estimate=_number(cells[5]), lower=pp_cl, upper=pp_cu),
            ],
            comparison=OutcomeComparison(
                relation="intervention_vs_control",
                intervention_arm_id="intervention",
                control_arm_id="control",
                comparator_arm_ids=["control"],
                contrast="Acupuncture vs Sham",
            ),
            analysis_set="PP",
            record_role="primary",
            evidence=[_evidence("intervention_estimate", row_quote), *time_evidence],
        ))
    return outcomes


def _parse_plain_primary(context: str) -> list[OutcomeStatistic]:
    searchable = _clean(context)
    row_match = re.search(r"PainVAS\s*\(T0[–-]T1\).{0,600}", searchable, re.I)
    if not row_match:
        return []
    row = row_match.group(0)
    pattern = re.compile(
        rf"(?P<p1>0?\.\d+)\s+"
        rf"(?P<ie>{NUMBER})\s+(?P<il>{NUMBER})\s+to\s+(?P<iu>{NUMBER})\s+"
        rf"(?P<ce>{NUMBER})\s+(?P<cl>{NUMBER})\s+to\s+(?P<cu>{NUMBER})\s+"
        rf"(?P<p2>0?\.\d+)\s+(?P<d>{NUMBER})\b",
        re.I,
    )
    match = pattern.search(row)
    if not match:
        return []
    values = match.groupdict()
    time_value, time_unit, derivation = _timepoint("T0-T1", context)
    evidence = [_evidence("outcome_between_group_estimate", row.strip())]
    if derivation:
        evidence.append(_evidence("outcome_observation_timepoint_value", "T0-T1; T1 at 10 weeks", derivation=derivation))
    return [OutcomeStatistic(
        table_id="narrative-primary",
        row_id="narrative-primary:r001",
        outcome_name="PainVAS",
        measurement_instrument="PainVAS 0-100 mm",
        outcome_observation_timepoint_raw="T0-T1",
        outcome_observation_timepoint_value=time_value,
        outcome_observation_timepoint_unit=time_unit,
        statistic_type="continuous",
        analysis_population="ITT",
        intervention_estimate=_number(values["ie"]),
        intervention_variance_lower=_number(values["il"]),
        intervention_variance_upper=_number(values["iu"]),
        control_estimate=_number(values["ce"]),
        control_variance_lower=_number(values["cl"]),
        control_variance_upper=_number(values["cu"]),
        between_group_measure="SMD",
        outcome_between_group_estimate=_number(values["d"]),
        outcome_p_value=_number(values["p2"]),
        outcome_p_value_comparator="=",
        effect_size_name="Cohen's d",
        arm=[
            OutcomeArm(arm_id="intervention", arm_label="Acupuncture", role="intervention", estimate=_number(values["ie"]), lower=_number(values["il"]), upper=_number(values["iu"])),
            OutcomeArm(arm_id="control", arm_label="Sham", role="control", estimate=_number(values["ce"]), lower=_number(values["cl"]), upper=_number(values["cu"])),
        ],
        comparison=OutcomeComparison(
            relation="intervention_vs_control",
            intervention_arm_id="intervention",
            control_arm_id="control",
            comparator_arm_ids=["control"],
            contrast="Acupuncture vs Sham",
        ),
        analysis_set="ITT",
        record_role="primary",
        evidence=evidence,
    )]


def parse_primary_painvas(context: str) -> OutcomeExtraction:
    """Parse PainVAS PP/ITT rows while preserving analysis population and derivations."""
    outcomes = _parse_html_tables(context) or _parse_plain_primary(context)
    return OutcomeExtraction(outcomes=outcomes)
