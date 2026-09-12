"""Value-blind adapter over EXISTING lossless table blocks.

Data cells are reduced to formatting shapes before interpretation. Neither numerical
magnitudes nor extracted n/SD/value fields are available to the identity linker.
"""
import re
from dataclasses import replace
from .models import SourceIdentityContext, SourceRowSemantics
from .normalizers import normalize_text


def cell_shape(text):
    # No captured number is returned or compared with any other observation.
    return re.sub(r"[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?", "#", text).strip()


def reporting_statements(markdown):
    statements = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", markdown):
        if re.search(r"\b(?:quantitative|continuous)\s+data\s+(?:were|are)\s+(?:expressed|presented|reported|summari[sz]ed)\s+as\s+(?:the\s+)?mean\s*(?:±|and|\+/-)\s*(?:standard deviation|SD)\b", sentence, re.I):
            statements.append(sentence.strip())
    return sorted(set(statements))


def explicit_header_blocks(blocks, parse_column_map, attach_cells):
    """Reuse existing parser helpers for missing metadata, never rewrite table parsing.

    Only an explicit first-row Arm header can authorize this fallback; a bare numeric
    data row cannot. Raw rows and the original block objects stay unchanged.
    """
    result = []
    for block in blocks:
        if not block.column_map and block.rows:
            columns = parse_column_map((block.rows[0],), block.source)
            labels = {c.get("arm_label") for c in columns} - {None, "", "NR"}
            if len(labels) >= 2:
                ids = tuple(f"{block.table_id}:r{i:03d}" for i in range(2, len(block.rows) + 1))
                block = replace(block, header_rows=(block.rows[0],), column_map=attach_cells(
                    columns, block.rows[1:], ids, block.source))
        result.append(block)
    return result


def context_from_table_blocks(blocks, statements=(), *, source_ref="article.md", source_sha256=None):
    """Caller supplies existing parsed blocks, not a Gold or comparison object."""
    rows = []
    global_mean_sd = bool(reporting_statements(" ".join(statements)))
    for block in blocks:
        row_maps = {rid: [] for rid in block.source_data_row_ids}
        for column in block.column_map:
            for cell in column.get("source_cells", []):
                row_id = cell.get("row_id")
                if row_id in row_maps:
                    row_maps[row_id].append((int(column["column_index"]), column, cell))
        for rid, cells in row_maps.items():
            cells.sort(key=lambda item: item[0])
            if not cells:
                continue
            def cell_text(cell):
                return str(cell.get("raw_value", ""))
            label = cell_text(cells[0][2])
            # Only cells whose columns have explicit Arm labels are descriptive observations.
            arm_cells = [(col, cell) for index, col, cell in cells if index > 0 and col.get("arm_label") not in {None, "", "NR"}]
            shapes = [cell_shape(cell_text(cell)) for _, cell in arm_cells]
            header_mean = bool(arm_cells) and all(
                re.search(r"mean\s*(?:±|\+/-|\(|and)\s*(?:sd|standard deviation)",
                          " ".join(str(x) for x in col.get("header_path", [])), re.I)
                for col, _ in arm_cells)
            paired = bool(shapes) and all(re.fullmatch(r"#\s*±\s*#", s) for s in shapes)
            incompatible_header = any(re.search(r"\bmedian\b|\bstandard error\b|\bSE\b",
                label + " " + " ".join(str(x) for x in col.get("header_path", [])), re.I) for col, _ in arm_cells)
            count_label = bool(re.search(r"\(\s*n\s*[,/]\s*%\s*\)", label, re.I)) or (
                bool(re.search(r"\bnumber\b.*\b(?:patients|participants|responders)\b", label, re.I))
                and bool(shapes) and all("%" in s for s in shapes))
            counts = bool(shapes) and all(re.fullmatch(r"#\s*\(\s*#\s*%?\s*\)", s) for s in shapes)
            statistic, rules = None, []
            if count_label and counts:
                statistic, rules = "event_count", ["STATISTIC_KIND_FROM_COUNT_PERCENT_STRUCTURE"]
            elif paired and not incompatible_header and (header_mean or global_mean_sd):
                statistic, rules = "mean", ["STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE"]
            rows.append(SourceRowSemantics(
                table_id=block.table_id, row_id=rid, row_label=label, statistic_kind=statistic,
                source_refs=[f"{source_ref}#{rid}"] + ([f"{source_ref}#statistical-analysis"] if global_mean_sd and statistic == "mean" else []),
                rules=rules))
    return SourceIdentityContext(rows=rows, reporting_statements=list(statements),
                                 source_document_sha256=source_sha256)


def source_blocks_for_result(result):
    pairs = set()
    if hasattr(result, "source_table_id") and result.source_table_id and result.source_row_id:
        pairs.add((result.source_table_id, result.source_row_id))
    for observation in result.legacy_fields.get("source_observations", []):
        if observation.get("table_id") and observation.get("row_id"):
            pairs.add((observation["table_id"], observation["row_id"]))
    return sorted(pairs)
