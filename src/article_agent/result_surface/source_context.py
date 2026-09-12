"""Adapt EXISTING lossless blocks; no PDF parsing, routing, extraction or Gold."""
from copy import deepcopy

from ..result_identity.source_context import reporting_statements


def context_from_blocks(blocks, markdown, *, source_ref, source_document_sha256):
    tables = []
    for block in blocks:
        position = markdown.find(block.raw_table)
        # A table-local adjacent paragraph, not a page-wide search for P values.
        footnote = ""
        if position >= 0:
            following = markdown[position + len(block.raw_table):].lstrip()
            footnote = following.split("\n\n", 1)[0]
        tables.append({
            "table_id": block.table_id, "caption": block.caption,
            "raw_table": block.raw_table, "header_rows": list(block.header_rows),
            "column_map": deepcopy(list(block.column_map)), "footnote": footnote,
            "source_ref": source_ref, "source_offset": position if position >= 0 else None,
        })
    return {"tables": tables, "reporting_statements": reporting_statements(markdown),
            "source_ref": source_ref, "source_document_sha256": source_document_sha256}
