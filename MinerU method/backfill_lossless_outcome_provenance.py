"""Backfill deterministic cell provenance on outcomes from an existing run.

This migration is intentionally source-first.  It never replaces a value that
was returned by the LLM; it only adds missing ``source_cells``/
``p_value_cells`` and deterministic arm aliases when the complete source row
and parsed multilevel header uniquely support them.  Narrative records keep
their original values and receive no fabricated table cells.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from mineru_method.llm import _normalize_outcome_items
from mineru_method.routing import contexts_for_modules
from mineru_method.schemas import OutcomeExtraction
from mineru_method.table_parser import extract_outcome_table_blocks


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _table_key(value: object) -> str:
    text = str(value or "").split("#part-", 1)[0].strip().lower()
    match = re.search(r"table[-_ ]*0*(\d+)", text)
    return f"table-{int(match.group(1))}" if match else text


def _row_key(value: object) -> tuple[str, str]:
    text = str(value or "")
    return _table_key(text.split(":", 1)[0]), text.rsplit(":", 1)[-1].lower()


def _source_contexts(article_dir: Path) -> dict[tuple[str, str], str]:
    markdown = (article_dir / "article.md").read_text(encoding="utf-8")
    contexts = contexts_for_modules(markdown)
    result: dict[tuple[str, str], str] = {}
    for block in extract_outcome_table_blocks(contexts["outcomes"], defer_classification=True):
        table_key = _table_key(block.table_id)
        for row, row_id in zip(block.source_data_rows, block.source_data_row_ids):
            key = (table_key, str(row_id).rsplit(":", 1)[-1].lower())
            selected = replace(block, selected_rows=(row,), selected_row_ids=(row_id,))
            result[key] = selected.prompt_text("")
    return result


def _merge_arm_provenance(original: list, projected: list) -> list:
    if not isinstance(original, list):
        original = []
    if not isinstance(projected, list):
        return original
    merged = [dict(item) for item in original if isinstance(item, dict)]
    by_label = {
        re.sub(r"\s+", " ", str(item.get("arm_label") or item.get("label") or "NR")).strip().lower(): item
        for item in merged
    }
    for candidate in projected:
        if not isinstance(candidate, dict):
            continue
        label = re.sub(r"\s+", " ", str(candidate.get("arm_label") or "NR")).strip().lower()
        if not label or label == "nr":
            continue
        target = by_label.get(label)
        if target is None:
            merged.append(dict(candidate))
            by_label[label] = merged[-1]
            continue
        # Only fill absent aliases; all source values/roles already present in
        # the original record remain authoritative.
        for field in ("value", "sd", "change", "estimate", "lower", "upper", "n"):
            if target.get(field) in (None, "", "NR") and candidate.get(field) not in (None, "", "NR"):
                target[field] = candidate[field]
    return merged


def repair_article(article_dir: Path) -> dict:
    path = article_dir / "extraction.json"
    payload = _read(path)
    source = payload.get("outcomes") if isinstance(payload.get("outcomes"), dict) else {}
    original_items = source.get("outcomes") if isinstance(source.get("outcomes"), list) else []
    context_map = _source_contexts(article_dir)
    updated_items = []
    changed = 0
    for item in original_items:
        if not isinstance(item, dict):
            continue
        updated = dict(item)
        table_id = str(item.get("table_id") or "")
        row_id = str(item.get("row_id") or "")
        context = context_map.get(_row_key(f"{table_id}:{row_id.rsplit(':', 1)[-1]}"))
        if context:
            try:
                projected = _normalize_outcome_items(
                    {"outcomes": [item]}, context, source="markdown", table_id=table_id
                ).outcomes[0]
            except (IndexError, TypeError, ValueError):
                projected = None
            if projected is not None:
                for field in ("source_values", "source_evidence", "source_cells", "p_value_cells"):
                    old = updated.get(field)
                    new = getattr(projected, field)
                    if field == "source_evidence":
                        if old in (None, "", "NR") and new not in (None, "", "NR"):
                            updated[field] = new
                    elif not isinstance(old, list) or not old:
                        if new:
                            updated[field] = new
                if isinstance(projected.arm, list):
                    merged_arms = _merge_arm_provenance(updated.get("arm"), [arm.model_dump(mode="json") for arm in projected.arm])
                    if merged_arms != updated.get("arm"):
                        updated["arm"] = merged_arms
                # A single P-value column is an unambiguous scalar projection;
                # multiple P columns remain in p_value_cells only.
                if updated.get("outcome_p_value") in (None, "", "NR") and len(projected.p_value_cells) == 1:
                    value = projected.p_value_cells[0].get("value")
                    if value is not None:
                        updated["outcome_p_value"] = value
                        updated["outcome_p_value_comparator"] = projected.p_value_cells[0].get("comparator") or "NR"
        if updated != item:
            changed += 1
        updated_items.append(updated)
    payload["outcomes"] = {**source, "outcomes": updated_items}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_path = article_dir / "raw_module_responses" / "outcomes.table-parser.json"
    raw_path.write_text(json.dumps(payload["outcomes"], ensure_ascii=False, indent=2), encoding="utf-8")
    return {"article_id": article_dir.name, "source_outcome_count": len(updated_items), "records_changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_root.resolve()
    summary = [repair_article(path) for path in sorted(root.glob("2015-*")) if path.is_dir()]
    print(json.dumps({"article_count": len(summary), "articles": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
