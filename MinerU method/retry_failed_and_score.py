"""Retry only incomplete API shards, then score the articles they affect.

The normal pipeline also re-requests metadata, acupuncture, risk and VLM modules
when invoked.  This utility deliberately avoids that broad replay: it reuses
valid table caches, sends only missing table/post-processing shards, and keeps a
complete existing post-processing result if a repair attempt remains partial.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from article_agent.models import OpenAICompatibleClient

from build_field_audit import build as build_field_audit
from evaluate_2015_01 import evaluate
from mineru_method.gold import sheet3_gold
from mineru_method.llm import (
    classify_outcome_tables_with_llm,
    extract_outcomes_by_table,
    extract_outcomes_from_results_narrative,
    merge_outcome_extractions,
    postprocess_outcomes_with_llm,
)
from mineru_method.routing import contexts_for_modules
from mineru_method.schemas import OutcomeExtraction
from mineru_method.table_parser import extract_outcome_table_blocks, parse_primary_painvas


def read_json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def request_delay() -> float:
    try:
        value = float(os.getenv("ARTICLE_AGENT_OUTCOME_REQUEST_DELAY_SECONDS", "0.01"))
    except ValueError:
        value = 0.01
    return max(0.0, min(value, 60.0))


def _coverage_table_key(value: object) -> str:
    """Normalize table/partition IDs for append-only manifest reconciliation.

    A whole-table/row fallback appends request IDs with ``#part`` and the
    Results prose pass appends paragraph ranges (``narrative-results:p001``).
    Coverage is about the stable source row ID, so these transport partitions
    must share one table key; otherwise an earlier failed request can keep
    appearing uncovered after its row succeeds in a retry.
    """

    text = str(value or "").split("#part-", 1)[0].strip().lower()
    if text.startswith("narrative-results"):
        return "narrative-results"
    match = re.search(r"table[-_ ]*0*(\d+)", text)
    return f"table-{int(match.group(1))}" if match else text


def _read_request_lines(path: Path) -> list[dict]:
    """Read valid JSONL request records without treating malformed lines as coverage."""

    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _merge_request_manifest(root_path: Path, *source_paths: Path) -> list[dict]:
    """Append request records while remapping colliding IDs from old retries.

    A resumed run can reuse the historical ``table-001-part-01`` identifier.
    Keeping both attempts is required for auditability; a collision is
    therefore remapped to a deterministic retry suffix instead of silently
    discarding the newer coverage acknowledgement.
    """

    merged: list[dict] = []
    by_id: dict[str, dict] = {}
    for path in (root_path, *source_paths):
        for item in _read_request_lines(path):
            request_id = str(item.get("request_id") or "").strip()
            if not request_id:
                continue
            candidate = dict(item)
            if request_id in by_id:
                previous = by_id[request_id]
                same = (
                    str(previous.get("input_sha256") or "")
                    == str(candidate.get("input_sha256") or "")
                    and str(previous.get("response_status") or "")
                    == str(candidate.get("response_status") or "")
                    and str(previous.get("covered_row_ids") or "")
                    == str(candidate.get("covered_row_ids") or "")
                )
                if same:
                    continue
                base = request_id
                suffix = 2
                request_id = f"{base}-retry-{suffix:02d}"
                while request_id in by_id:
                    suffix += 1
                    request_id = f"{base}-retry-{suffix:02d}"
                candidate["request_id"] = request_id
                candidate["remapped_from_request_id"] = base
            by_id[request_id] = candidate
            merged.append(candidate)
    if merged:
        root_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in merged),
            encoding="utf-8",
        )
    return merged


def workers() -> int:
    # This repair utility intentionally ignores a larger ambient worker value.
    # It is a serial recovery path to avoid another burst of TLS connections.
    return 1


def table_cache_paths(raw_dir: Path, manifest: dict) -> list[Path]:
    paths: list[Path] = []
    for table in manifest.get("tables", []) if isinstance(manifest, dict) else []:
        for part in table.get("parts", []) if isinstance(table, dict) else []:
            cache = part.get("cache") if isinstance(part, dict) else None
            if cache:
                paths.append(raw_dir / str(cache))
    return paths


def retry_table_shards(article_dir: Path, client: OpenAICompatibleClient, retries: int = 2) -> dict:
    raw_dir = article_dir / "raw_module_responses"
    manifest_path = raw_dir / "outcomes.tablewise.manifest.json"
    original_manifest = read_json(manifest_path, {}) or {}
    cache_paths = table_cache_paths(raw_dir, original_manifest)
    missing = [str(path.name) for path in cache_paths if not path.exists()]
    # A cache file can exist even when its request failed or covered only a
    # subset of the declared rows.  Reconcile the lossless request manifest
    # before deciding that the table stage is complete; otherwise a failed
    # whole-table probe would be silently treated as a valid empty response.
    request_rows: dict[str, set[str]] = {}
    covered_rows: dict[str, set[str]] = {}
    request_manifest_path = raw_dir / "request_manifest.jsonl"
    # ``extract_outcomes_by_table`` writes its local request manifest for the
    # current call.  Save the append-only history before invoking it so a
    # targeted retry cannot erase earlier source coverage/error records.
    previous_request_manifest_path = raw_dir / ".request_manifest.previous.jsonl"
    if request_manifest_path.exists():
        previous_request_manifest_path.write_text(
            request_manifest_path.read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
    if request_manifest_path.exists():
        for line in request_manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict):
                continue
            table_id = _coverage_table_key(item.get("table_id"))
            if not table_id or table_id.startswith("narrative-results"):
                continue
            request_rows.setdefault(table_id, set()).update(
                str(value) for value in (item.get("row_ids") or [])
                if value not in (None, "", "NR")
            )
            covered_rows.setdefault(table_id, set()).update(
                str(value) for value in (item.get("covered_row_ids") or [])
                if value not in (None, "", "NR")
            )
    # Recover the complete expected/covered row inventory from the
    # authoritative tablewise manifest as well.  Older retry code overwrote
    # the root JSONL with only the latest targeted request, so relying on that
    # file alone would lose rows that were already covered in earlier parts.
    for table in original_manifest.get("tables", []) if isinstance(original_manifest, dict) else []:
        if not isinstance(table, dict):
            continue
        table_id = _coverage_table_key(table.get("table_id"))
        if not table_id or table_id.startswith("narrative-results"):
            continue
        expected_ids: set[str] = set()
        for part in table.get("parts", []) if isinstance(table.get("parts"), list) else []:
            if isinstance(part, dict):
                expected_ids.update(
                    str(value) for value in (part.get("row_ids") or [])
                    if value not in (None, "", "NR")
                )
        expected_ids.update(
            str(value) for value in (table.get("covered_row_ids") or [])
            if value not in (None, "", "NR")
        )
        expected_ids.update(
            str(value) for value in (table.get("missing_row_ids") or [])
            if value not in (None, "", "NR")
        )
        if expected_ids:
            request_rows.setdefault(table_id, set()).update(expected_ids)
        covered_rows.setdefault(table_id, set()).update(
            str(value) for value in (table.get("covered_row_ids") or [])
            if value not in (None, "", "NR")
        )
    manifest_uncovered: dict[str, set[str]] = {
        table_id: rows - covered_rows.get(table_id, set())
        for table_id, rows in request_rows.items()
        if rows - covered_rows.get(table_id, set())
    }
    for table_id, row_ids in manifest_uncovered.items():
        marker = f"uncovered:{table_id}:{','.join(sorted(row_ids))}"
        if marker not in missing:
            missing.append(marker)
    # A failed table classifier produces no cache path at all and therefore
    # used to be treated as a complete (empty) extraction.  Re-enter the
    # classifier whenever any source table failed or remained ``unknown``;
    # otherwise articles such as 2015-02 lose all table outcomes silently.
    classification_records = original_manifest.get("table_classification") or []
    classification_failed = [
        str(item.get("table_id") or f"table-{index + 1:03d}")
        for index, item in enumerate(classification_records)
        if isinstance(item, dict)
        and (item.get("status") == "failed" or str(item.get("table_category") or "unknown") == "unknown")
    ]
    table_incomplete = [
        str(item.get("table_id") or f"table-{index + 1:03d}")
        for index, item in enumerate(original_manifest.get("tables") or [])
        if isinstance(item, dict)
        and item.get("status") not in {"success", "skipped"}
    ]
    retry_markers = [f"classification:{value}" for value in classification_failed] + [
        f"table:{value}" for value in table_incomplete
    ]
    missing.extend(value for value in retry_markers if value not in missing)
    if not missing:
        return {"status": "skipped", "reason": "all_table_shard_caches_present", "missing": []}
    table_relevant_missing = [
        value for value in missing
        if not str(value).startswith("uncovered:narrative-results")
        and not str(value).startswith("narrative-results")
    ]
    if not table_relevant_missing:
        return {
            "status": "skipped",
            "reason": "only_results_narrative_rows_uncovered",
            "missing": missing,
        }

    markdown_path = article_dir / "article.md"
    markdown = markdown_path.read_text(encoding="utf-8")
    contexts = contexts_for_modules(markdown)
    table_blocks = extract_outcome_table_blocks(contexts["outcomes"], defer_classification=True)
    if not table_blocks:
        return {"status": "failed", "reason": "no_reconstructable_tables", "missing": missing}

    # Recovery can deliberately reduce the rows-per-request size (often to
    # one) when a gateway accepts small row payloads but rejects the original
    # multi-row shard.  With no override, retain the source manifest setting.
    try:
        configured_rows = os.getenv("ARTICLE_AGENT_OUTCOME_ROWS_PER_REQUEST")
        max_rows = int(configured_rows) if configured_rows not in (None, "") else int(original_manifest.get("max_rows_per_request") or 3)
    except (TypeError, ValueError):
        max_rows = 3
    max_rows = max(1, min(max_rows, 12))
    # Keep the complete Results context for routing/recovery.  Earlier retry
    # code used a prefix before the first table, which silently omitted prose
    # outcomes reported after a table.
    narrative_hint = contexts["outcomes"]
    classifier_model = (
        os.getenv("ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL")
        or os.getenv("ARTICLE_AGENT_BASIC_MATCH_MODEL")
        or "gpt-5.6-luna"
    ).strip() or "gpt-5.6-luna"
    try:
        classifier_retries = int(os.getenv("ARTICLE_AGENT_TABLE_CLASSIFIER_RETRIES", "1"))
    except ValueError:
        classifier_retries = 1
    classifier_retries = max(0, min(classifier_retries, 5))
    classified_blocks, classification_manifest = classify_outcome_tables_with_llm(
        client if classifier_model == client.model else OpenAICompatibleClient(
            api_key=client.api_key,
            base_url=client.base_url,
            model=classifier_model,
            timeout=client.timeout,
        ),
        table_blocks,
        raw_dir,
        narrative_hint=narrative_hint,
        retries=classifier_retries,
        request_delay_seconds=request_delay(),
    )

    # Restrict repair requests to source rows that the authoritative manifest
    # says are missing.  The previous retry path re-sent every row of an
    # incomplete table, which was both slow and likely to create duplicate
    # records.  We keep the full deterministic header/column map on each
    # selected block; only the target row set is narrowed.
    def table_key(value: object) -> str:
        text = str(value or "").split("#part-", 1)[0].strip().lower()
        match = re.search(r"table[-_ ]*0*(\d+)", text)
        return f"table-{int(match.group(1))}" if match else text

    def row_key(value: object) -> str:
        text = str(value or "").split("#part-", 1)[0]
        return text.rsplit(":", 1)[-1].strip().lower()

    target_rows: dict[str, set[str] | None] = {}
    skipped_table_keys: set[str] = set()
    for index, item in enumerate(original_manifest.get("tables") or [], start=1):
        if not isinstance(item, dict):
            continue
        key = table_key(item.get("table_id") or f"table-{index:03d}")
        status = str(item.get("status") or "unknown")
        if status == "skipped":
            skipped_table_keys.add(key)
            continue
        if status == "success" and not any(
            str(path).startswith(str(item.get("table_id") or "")) for path in missing
        ):
            continue
        missing_ids = {
            row_key(value)
            for value in (item.get("missing_row_ids") or [])
            if value not in (None, "", "NR")
        }
        # A partial table with no explicit row list is unsafe to narrow: keep
        # all selected rows so no source coverage is lost.  Likewise, a
        # missing shard cache requires replaying that table's complete rows.
        target_rows[key] = missing_ids or None
    for value in classification_failed:
        key = table_key(value)
        if key not in skipped_table_keys:
            target_rows.setdefault(key, None)
    for value in missing:
        if str(value).startswith("outcomes.table-"):
            match = re.search(r"outcomes\.(table-[^.]+)", str(value))
            if match:
                key = table_key(match.group(1))
                if key not in skipped_table_keys:
                    target_rows.setdefault(key, None)
        elif str(value).startswith("uncovered:"):
            # Marker format is generated above and keeps the exact row set
            # available for a targeted replay.
            parts = str(value).split(":", 2)
            if len(parts) == 3:
                key = table_key(parts[1])
                # Results-prose rows are repaired by ``retry_narrative``;
                # they are not source tables.  Treating this marker as a
                # table target previously caused the no-block fallback to
                # replay every table in an otherwise complete article.
                if key.startswith("narrative-results"):
                    continue
                if key not in skipped_table_keys:
                    target_rows[key] = {
                        row_key(row_id) for row_id in parts[2].split(",")
                        if row_id not in (None, "", "NR")
                    }

    targeted_blocks = []
    for block in classified_blocks:
        key = table_key(block.table_id)
        if key not in target_rows:
            continue
        wanted = target_rows[key]
        if wanted is None:
            targeted_blocks.append(block)
            continue
        selected_rows = []
        selected_ids = []
        for row, row_id in zip(block.target_rows, block.target_row_ids):
            if row_key(row_id) in wanted:
                selected_rows.append(row)
                selected_ids.append(row_id)
        if selected_rows:
            targeted_blocks.append(replace(
                block,
                selected_rows=tuple(selected_rows),
                selected_row_ids=tuple(selected_ids),
            ))
    # If a legacy manifest cannot be reconciled with the newly parsed row IDs,
    # fail open to the complete classified table set and preserve an explicit
    # reason in the retry manifest instead of silently sending nothing.
    target_selection_fallback = bool(target_rows) and not targeted_blocks
    if target_selection_fallback:
        targeted_blocks = list(classified_blocks)
    if not targeted_blocks:
        return {
            "status": "failed",
            "reason": "missing_rows_not_reconstructable",
            "missing": missing,
            "target_rows": {key: sorted(value) if isinstance(value, set) else None for key, value in target_rows.items()},
        }
    tablewise, table_manifest = extract_outcomes_by_table(
        client,
        targeted_blocks,
        raw_dir,
        narrative_hint=narrative_hint,
        retries=retries,
        max_rows_per_request=max_rows,
        max_workers=workers(),
        request_delay_seconds=request_delay(),
        whole_table_first=os.getenv("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_FIRST", "1").strip().lower() not in {
            "0", "false", "no", "off",
        },
        whole_table_timeout=max(10, int(os.getenv("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_TIMEOUT", "30"))),
        request_id_prefix=f"table-retry-{uuid.uuid4().hex[:10]}",
    )
    _merge_request_manifest(request_manifest_path, previous_request_manifest_path)
    try:
        previous_request_manifest_path.unlink()
    except OSError:
        pass

    # Keep the repaired rows alongside the existing source dataset.  Exact
    # byte-for-byte duplicates from a retry are not appended a second time,
    # while genuinely different table/narrative records remain available for
    # conflict grouping in the post-processing layer.  The original raw
    # response and every retry request are still preserved on disk.
    extraction_path = article_dir / "extraction.json"
    existing_extraction = read_json(extraction_path, {}) or {}
    try:
        existing_outcomes = OutcomeExtraction.model_validate(existing_extraction.get("outcomes") or {})
    except Exception:
        existing_outcomes = OutcomeExtraction(outcomes=[])
    repaired_outcomes = merge_outcome_extractions(
        tablewise,
        parse_primary_painvas(contexts["outcomes"]),
    )
    seen_outcome_keys = {
        json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        for item in existing_outcomes.outcomes
    }
    merged_outcome_items = list(existing_outcomes.outcomes)
    for item in repaired_outcomes.outcomes:
        key = json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        if key in seen_outcome_keys:
            continue
        seen_outcome_keys.add(key)
        merged_outcome_items.append(item)
    merged_outcomes = OutcomeExtraction(outcomes=merged_outcome_items)

    # Merge coverage from the retry manifest into the authoritative tablewise
    # manifest.  This makes previously successful tables and newly repaired
    # rows visible to QA without replacing the full source-table inventory by
    # the targeted subset used in this request.
    original_tables = {
        table_key(item.get("table_id")): dict(item)
        for item in (original_manifest.get("tables") or [])
        if isinstance(item, dict) and item.get("table_id")
    }
    retry_tables = {
        table_key(item.get("table_id")): dict(item)
        for item in table_manifest
        if isinstance(item, dict) and item.get("table_id")
    }
    merged_tables: list[dict] = []
    for key, old_item in original_tables.items():
        new_item = retry_tables.get(key)
        if new_item is None:
            merged_tables.append(old_item)
            continue
        merged_item = dict(old_item)
        old_parts = [dict(part) for part in (old_item.get("parts") or []) if isinstance(part, dict)]
        new_parts = [dict(part) for part in (new_item.get("parts") or []) if isinstance(part, dict)]
        for part in new_parts:
            part["retry_attempt"] = True
        merged_item["parts"] = old_parts + new_parts
        expected_ids = {
            str(value)
            for part in merged_item["parts"]
            for value in (part.get("row_ids") or [])
            if value not in (None, "", "NR")
        }
        expected_ids.update(str(value) for value in (old_item.get("missing_row_ids") or []) if value not in (None, "", "NR"))
        covered_ids = {
            str(value)
            for value in (old_item.get("covered_row_ids") or [])
            if value not in (None, "", "NR")
        }
        covered_ids.update(str(value) for value in (new_item.get("covered_row_ids") or []) if value not in (None, "", "NR"))
        merged_item["covered_row_ids"] = sorted(covered_ids)
        merged_item["missing_row_ids"] = sorted(expected_ids - covered_ids)
        merged_item["status"] = "success" if not merged_item["missing_row_ids"] else "partial"
        merged_item["outcome_count"] = sum(int(part.get("outcome_count") or 0) for part in merged_item["parts"])
        merged_item["repair_status"] = new_item.get("status")
        merged_tables.append(merged_item)
    for key, new_item in retry_tables.items():
        if key not in original_tables:
            merged_tables.append(new_item)
    merged_tables.sort(key=lambda item: str(item.get("table_id") or ""))
    eligible_merged_tables = [item for item in merged_tables if item.get("status") != "skipped"]
    merged_complete = bool(merged_tables) and all(item.get("status") == "success" for item in eligible_merged_tables)
    classification_complete = bool(classification_manifest) and all(
        item.get("status") in {"success", "cached"}
        and str(item.get("table_category") or "unknown") != "unknown"
        for item in classification_manifest
        if isinstance(item, dict)
    )
    complete = classification_complete and merged_complete
    if repaired_outcomes.outcomes:
        existing_extraction["outcomes"] = merged_outcomes.model_dump(mode="json")
        write_json(extraction_path, existing_extraction)
        write_json(raw_dir / "outcomes.table-parser.json", merged_outcomes.model_dump(mode="json"))
    merged_authoritative_manifest = dict(original_manifest)
    merged_authoritative_manifest.update({
        "tables": merged_tables,
        "table_classification": classification_manifest or original_manifest.get("table_classification") or [],
        "total_outcomes": len(merged_outcomes.outcomes),
        "status": "success" if complete else "partial",
        "last_repair": "targeted_missing_row_ids",
    })
    write_json(manifest_path, merged_authoritative_manifest)
    all_parts = [
        part
        for table in table_manifest
        for part in table.get("parts", [])
    ]
    eligible_tables = [table for table in table_manifest if table.get("status") != "skipped"]
    retry_manifest = {
        "strategy": "llm_table_classification_then_targeted_missing_table_shards_serial_10ms",
        "table_classification_model": classifier_model,
        "basic_match_model": os.getenv("ARTICLE_AGENT_BASIC_MATCH_MODEL", "").strip() or None,
        "table_classification_retries": classifier_retries,
        "table_classification": classification_manifest,
        "target_rows": {key: sorted(value) if isinstance(value, set) else None for key, value in target_rows.items()},
        "target_selection_fallback": target_selection_fallback,
        "max_rows_per_request": max_rows,
        "whole_table_first": True,
        "max_workers": workers(),
        "request_delay_seconds": request_delay(),
        "missing_cache_files_before": missing,
        "tables": table_manifest,
        "total_outcomes": len(tablewise.outcomes),
        "status": "success" if complete else "partial",
    }
    write_json(raw_dir / "outcomes.tablewise.retry-serial-10ms.manifest.json", retry_manifest)

    if not complete:
        return {
            "status": "partial",
            "missing": missing,
            "retry_manifest": str(raw_dir / "outcomes.tablewise.retry-serial-10ms.manifest.json"),
        }
    canonical_manifest = {
        "strategy": "llm_table_classification_then_deterministic_header_row_selection_then_rowwise_llm_preserve_raw",
        "document_wide_row_limit": None,
        "table_classification_model": classifier_model,
        "basic_match_model": os.getenv("ARTICLE_AGENT_BASIC_MATCH_MODEL", "").strip() or None,
        "table_classification_retries": classifier_retries,
        "table_classification": classification_manifest,
        "max_rows_per_request": max_rows,
        "whole_table_first": True,
        "max_workers": workers(),
        "request_delay_seconds": request_delay(),
        "table_count": len(table_blocks),
        "total_outcomes": len(merged_outcomes.outcomes),
        "tables": merged_tables,
    }
    write_json(manifest_path, canonical_manifest)
    return {
        "status": "success",
        "missing": missing,
        "repaired_outcome_count": len(repaired_outcomes.outcomes),
        "retry_manifest": str(raw_dir / "outcomes.tablewise.retry-serial-10ms.manifest.json"),
    }


def postprocess_needs_retry(article_dir: Path, batch_size: int) -> tuple[bool, list[str]]:
    extraction = read_json(article_dir / "extraction.json", {}) or {}
    source_count = len((extraction.get("outcomes") or {}).get("outcomes") or [])
    post_path = article_dir / "outcomes.postprocessed.json"
    raw_dir = article_dir / "raw_module_responses"
    expected = [
        raw_dir / f"outcomes.postprocess.part-{part:03d}.json"
        for part in range(1, (source_count + batch_size - 1) // batch_size + 1)
    ]
    missing: list[str] = []
    for part, path in enumerate(expected, start=1):
        expected_indices = set(range((part - 1) * batch_size, min(part * batch_size, source_count)))
        if not path.exists():
            missing.append(str(path.name))
            continue
        payload = read_json(path, {}) or {}
        records = payload.get("records") if isinstance(payload, dict) else None
        actual_indices = {
            int(item.get("source_index"))
            for item in (records or [])
            if isinstance(item, dict) and str(item.get("source_index", "")).lstrip("-").isdigit()
        }
        if actual_indices != expected_indices:
            missing.append(str(path.name))
    # A missing postprocessed file is an incomplete stage even when no old
    # error marker was written (for example, an article from an earlier run).
    return (not post_path.exists() or bool(missing)), missing


def narrative_needs_retry(article_dir: Path) -> tuple[bool, str]:
    """Return whether the Results-prose pass has incomplete coverage.

    A successful table pass does not imply that narrative outcomes were
    handled.  The narrative manifest is authoritative for paragraph coverage;
    the original directory is never overwritten by a repair attempt.
    """

    manifest_path = article_dir / "raw_module_responses" / "narrative" / "outcomes.narrative.manifest.json"
    manifest = read_json(manifest_path, {}) or {}
    retry_manifest = read_json(
        article_dir / "raw_module_responses" / "outcomes.narrative.retry-serial-10ms.manifest.json",
        {},
    ) or {}
    retry_complete = retry_manifest.get("status") == "success"
    # Check the combined request manifest as a second, independent coverage
    # source.  A narrative part may be labelled success by an older manifest
    # even though one of its row-level fallback requests failed.  Any
    # requested narrative row that has no successful acknowledgement must be
    # replayed; it is never silently treated as a non-outcome.
    request_manifest_path = article_dir / "raw_module_responses" / "request_manifest.jsonl"
    narrative_requested: set[str] = set()
    narrative_covered: set[str] = set()
    if request_manifest_path.exists():
        for line in request_manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict) or not str(item.get("table_id") or "").startswith("narrative-results"):
                continue
            narrative_requested.update(
                str(value) for value in (item.get("row_ids") or [])
                if value not in (None, "", "NR")
            )
            narrative_covered.update(
                str(value) for value in (item.get("covered_row_ids") or [])
                if value not in (None, "", "NR")
            )
    # A previous isolated retry may have been written before its request IDs
    # were remapped into the root manifest.  Its per-part coverage is still a
    # valid acknowledgement for the same stable row IDs, so include it when
    # deciding whether another retry is necessary.
    for part in (retry_manifest.get("manifest") or []) if isinstance(retry_manifest, dict) else []:
        if not isinstance(part, dict):
            continue
        for row_id in part.get("covered_row_ids", []) if isinstance(part.get("covered_row_ids"), list) else []:
            narrative_covered.add(str(row_id))
        for nested in part.get("parts", []) if isinstance(part.get("parts"), list) else []:
            if not isinstance(nested, dict):
                continue
            for row_id in nested.get("covered_row_ids", []) if isinstance(nested.get("covered_row_ids"), list) else []:
                narrative_covered.add(str(row_id))
    if narrative_requested - narrative_covered:
        return True, "request_manifest_uncovered_narrative_rows:" + ",".join(
            sorted(narrative_requested - narrative_covered)
        )
    if not manifest:
        if retry_complete:
            return False, "completed_by_retry_manifest"
        return True, "missing_narrative_manifest"
    parts = manifest.get("manifest") if isinstance(manifest, dict) else None
    if not isinstance(parts, list):
        if retry_complete:
            return False, "completed_by_retry_manifest"
        return True, "malformed_narrative_manifest"
    for item in parts:
        if not isinstance(item, dict):
            if retry_complete:
                return False, "completed_by_retry_manifest"
            return True, "malformed_narrative_part"
        if item.get("status") not in {"success", "skipped"}:
            if retry_complete:
                return False, "completed_by_retry_manifest"
            return True, f"narrative_part_status:{item.get('status') or 'unknown'}"
        if item.get("missing_row_ids"):
            if retry_complete:
                return False, "completed_by_retry_manifest"
            return True, "narrative_missing_row_ids"
    if all(
        isinstance(item, dict) and item.get("status") in {"success", "skipped"}
        for item in parts
    ):
        return False, "complete"
    if retry_complete:
        return False, "completed_by_retry_manifest"
    return True, "narrative_retry_incomplete"


def retry_narrative(article_dir: Path, client: OpenAICompatibleClient, retries: int = 2) -> dict:
    """Replay only incomplete Results prose chunks in an isolated directory."""

    needed, reason = narrative_needs_retry(article_dir)
    raw_dir = article_dir / "raw_module_responses"
    if not needed:
        # Even when coverage is already complete, an earlier interrupted
        # process may have left the isolated retry JSONL out of the article
        # root.  Merge it once so the root manifest remains a full audit log;
        # colliding IDs are remapped rather than dropped.
        _merge_request_manifest(
            raw_dir / "request_manifest.jsonl",
            raw_dir / "narrative_retry" / "request_manifest.jsonl",
        )
        return {"status": "skipped", "reason": reason}
    markdown_path = article_dir / "article.md"
    if not markdown_path.exists():
        return {"status": "failed", "reason": "missing_article_markdown"}
    markdown = markdown_path.read_text(encoding="utf-8")
    contexts = contexts_for_modules(markdown)
    retry_dir = raw_dir / "narrative_retry"
    retry_dir.mkdir(parents=True, exist_ok=True)
    # Restrict a recovery request to the stable narrative row IDs that are
    # actually uncovered.  The selected paragraphs remain complete and keep
    # their original indices, so this is a lossless transport optimization,
    # not semantic filtering.  If the legacy manifest cannot expose an exact
    # set, leave the value unset and replay the complete candidate set.
    only_row_ids: set[str] = set()
    request_manifest_path = raw_dir / "request_manifest.jsonl"
    previous_retry_manifest = read_json(
        raw_dir / "outcomes.narrative.retry-serial-10ms.manifest.json",
        {},
    ) or {}
    previous_narrative_manifest = read_json(
        raw_dir / "narrative" / "outcomes.narrative.manifest.json",
        {},
    ) or {}
    requested_rows: set[str] = set()
    covered_rows: set[str] = set()
    if request_manifest_path.exists():
        for line in request_manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict) or not str(item.get("table_id") or "").startswith("narrative-results"):
                continue
            requested_rows.update(
                str(value) for value in (item.get("row_ids") or [])
                if value not in (None, "", "NR")
            )
            covered_rows.update(
                str(value) for value in (item.get("covered_row_ids") or [])
                if value not in (None, "", "NR")
            )
    for part in (previous_retry_manifest.get("manifest") or []) if isinstance(previous_retry_manifest, dict) else []:
        if not isinstance(part, dict):
            continue
        covered_rows.update(
            str(value) for value in (part.get("covered_row_ids") or [])
            if value not in (None, "", "NR")
        )
        for nested in part.get("parts", []) if isinstance(part.get("parts"), list) else []:
            if isinstance(nested, dict):
                covered_rows.update(
                    str(value) for value in (nested.get("covered_row_ids") or [])
                    if value not in (None, "", "NR")
                )
    if requested_rows:
        only_row_ids = requested_rows - covered_rows
    if not only_row_ids:
        manifest_parts = (
            previous_narrative_manifest.get("manifest")
            if isinstance(previous_narrative_manifest, dict)
            else None
        ) or []
        if isinstance(manifest_parts, list):
            for part in manifest_parts:
                if not isinstance(part, dict):
                    continue
                only_row_ids.update(
                    str(value) for value in (part.get("missing_row_ids") or [])
                    if value not in (None, "", "NR")
                )
    try:
        extracted, manifest = extract_outcomes_from_results_narrative(
            client,
            contexts["outcomes"],
            retry_dir,
            retries=retries,
            request_delay_seconds=request_delay(),
            only_row_ids=only_row_ids or None,
            request_id_prefix=f"narrative-retry-{uuid.uuid4().hex[:10]}",
        )
    except Exception as exc:
        retry_manifest = {
            "strategy": "isolated_results_narrative_retry_preserve_original",
            "reason": reason,
            "status": "failed",
            "error": str(exc),
            "outcome_count": 0,
        }
        write_json(raw_dir / "outcomes.narrative.retry-serial-10ms.manifest.json", retry_manifest)
        return retry_manifest

    extraction_path = article_dir / "extraction.json"
    extraction = read_json(extraction_path, {}) or {}
    existing = OutcomeExtraction.model_validate(extraction.get("outcomes") or {})
    # Preserve every prior source record.  A successful replay is appended,
    # never used to replace a prior record; canonical/conflict processing later
    # decides whether the two sources are duplicate or conflicting.
    merged = merge_outcome_extractions(existing, extracted)
    extraction["outcomes"] = merged.model_dump(mode="json")
    write_json(extraction_path, extraction)
    write_json(raw_dir / "outcomes.table-parser.json", merged.model_dump(mode="json"))
    # Carry the isolated retry requests into the article-level manifest while
    # retaining every original attempt.  Colliding legacy IDs are remapped by
    # ``_merge_request_manifest`` so a newer successful row acknowledgement is
    # never hidden behind an earlier failed request with the same ID.
    root_manifest_path = raw_dir / "request_manifest.jsonl"
    _merge_request_manifest(root_manifest_path, retry_dir / "request_manifest.jsonl")
    retry_status = "success" if all(
        item.get("status") in {"success", "skipped"}
        for item in manifest
        if isinstance(item, dict)
    ) else "partial"
    retry_manifest = {
        "strategy": "isolated_results_narrative_retry_preserve_original",
        "reason": reason,
        "status": retry_status,
        "outcome_count": len(extracted.outcomes),
        "merged_outcome_count": len(merged.outcomes),
        "target_row_ids": sorted(only_row_ids) if only_row_ids else None,
        "retry_directory": str(retry_dir),
        "manifest": manifest,
    }
    tablewise_path = raw_dir / "outcomes.tablewise.manifest.json"
    tablewise = read_json(tablewise_path, {}) or {}
    if isinstance(tablewise, dict):
        tablewise["narrative_retry"] = {
            "status": retry_status,
            "outcome_count": len(extracted.outcomes),
            "retry_directory": str(retry_dir),
        }
        tablewise["narrative_outcome_count"] = sum(
            1 for item in merged.outcomes if str(item.table_id).startswith("narrative-results")
        )
        tablewise["total_outcomes"] = len(merged.outcomes)
        write_json(tablewise_path, tablewise)
    write_json(raw_dir / "outcomes.narrative.retry-serial-10ms.manifest.json", retry_manifest)
    return retry_manifest


def has_unresolved_postprocess_error(article_dir: Path) -> bool:
    raw_dir = article_dir / "raw_module_responses"
    for error_path in raw_dir.glob("outcomes.postprocess.part-*.error.txt"):
        cache_path = raw_dir / error_path.name.replace(".error.txt", ".json")
        if not cache_path.exists():
            return True
    return False


def retry_postprocessing(article_dir: Path, client: OpenAICompatibleClient, retries: int = 2) -> dict:
    batch_size = 4
    configured_batch = os.getenv("ARTICLE_AGENT_OUTCOME_POSTPROCESS_BATCH_SIZE")
    try:
        batch_size = int(configured_batch) if configured_batch not in (None, "") else 4
    except ValueError:
        batch_size = 4
    # Preserve the historical shard size for this run when no explicit
    # override is supplied; the postprocessor itself can still reuse caches
    # by source_index if a previous attempt used different boundaries.
    use_existing_batch = os.getenv("ARTICLE_AGENT_POSTPROCESS_USE_EXISTING_BATCH_SIZE", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if use_existing_batch and configured_batch in (None, ""):
        prior_manifest = read_json(article_dir / "raw_module_responses" / "outcomes.postprocess.manifest.json", {}) or {}
        try:
            prior_batch = int(prior_manifest.get("batch_size") or 0)
        except (TypeError, ValueError):
            prior_batch = 0
        if 1 <= prior_batch <= 16:
            batch_size = prior_batch
    # A 16-record shard still carries complete source/evidence units while
    # reducing the number of gateway round trips for large articles.  It is
    # not a record limit: the function creates as many shards as needed.
    batch_size = max(1, min(batch_size, 16))
    force_fresh = os.getenv("ARTICLE_AGENT_FORCE_POSTPROCESS", "0").strip().lower() in {"1", "true", "yes"}
    needed, missing = postprocess_needs_retry(article_dir, batch_size)
    if force_fresh:
        needed = True
        missing = ["forced_fresh_run"]
    if not needed:
        return {"status": "skipped", "reason": "postprocessing_complete_and_cached", "missing": []}

    extraction = read_json(article_dir / "extraction.json", {}) or {}
    outcomes = OutcomeExtraction.model_validate(extraction.get("outcomes") or {})
    contexts = contexts_for_modules((article_dir / "article.md").read_text(encoding="utf-8"))
    raw_dir = article_dir / "raw_module_responses"
    result, parts = postprocess_outcomes_with_llm(
        client,
        outcomes,
        sheet3_gold(ROOT, article_dir.name),
        contexts["outcomes"],
        raw_dir,
        retries=retries,
        batch_size=batch_size,
        max_workers=workers(),
        request_delay_seconds=request_delay(),
    )
    retry_manifest = {
        "strategy": "targeted_missing_postprocess_shards_serial_10ms",
        "run_id": os.getenv("ARTICLE_AGENT_RUN_ID") or None,
        "model": client.model,
        "batch_size": batch_size,
        "max_workers": workers(),
        "request_delay_seconds": request_delay(),
        "missing_cache_files_before": missing,
        "source_outcome_count": result.source_outcome_count,
        "processed_outcome_count": result.processed_outcome_count,
        "conflict_count": result.conflict_count,
        "status": result.status,
        "parts": parts,
    }
    retry_manifest_path = raw_dir / "outcomes.postprocess.retry-serial-10ms.manifest.json"
    write_json(retry_manifest_path, retry_manifest)

    canonical_path = article_dir / "outcomes.postprocessed.json"
    existing = read_json(canonical_path, {}) or {}
    # Never replace a complete prior result with a partial repair result.  A
    # forced run only bypasses the cache check; it must not turn a transient
    # gateway/SSL failure into a destructive overwrite of a complete dataset.
    if result.status == "success" or not existing or existing.get("status") != "success":
        canonical_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        write_json(raw_dir / "outcomes.postprocess.manifest.json", {
            "strategy": "post_extraction_llm_annotation_with_gold_conflict_preservation",
            "run_id": os.getenv("ARTICLE_AGENT_RUN_ID") or None,
            "model": client.model,
            "gold_used_for_extraction": False,
            "gold_used_for_postprocess_comparison": True,
            "batch_size": batch_size,
            "max_workers": workers(),
            "request_delay_seconds": request_delay(),
            "source_outcome_count": result.source_outcome_count,
            "processed_outcome_count": result.processed_outcome_count,
            "conflict_count": result.conflict_count,
            "canonical_dataset": "outcomes.canonical.json",
            "canonical_outcome_count": result.canonical_dataset.canonical_outcome_count if result.canonical_dataset else 0,
            "canonical_conflict_group_count": result.canonical_dataset.conflict_group_count if result.canonical_dataset else 0,
            "parts": parts,
        })
        if result.canonical_dataset is not None:
            write_json(article_dir / "outcomes.canonical.json", result.canonical_dataset.model_dump(mode="json"))
    return {
        "status": result.status,
        "missing": missing,
        "processed_outcome_count": result.processed_outcome_count,
        "conflict_count": result.conflict_count,
        "retry_manifest": str(retry_manifest_path),
    }


def score_article(article_dir: Path, tag: str) -> dict:
    result = evaluate(
        article_dir,
        tag=tag,
        use_postprocessed=True,
        request_delay_seconds=request_delay(),
    )
    evaluation_path = article_dir / f"llm_evaluation.{tag}.json"
    audit_path = article_dir / f"FIELD_AUDIT.{tag}.html"
    build_field_audit(article_dir / "extraction.json", evaluation_path, audit_path)
    return {
        "status": "success",
        "overall_score": result.get("overall_score"),
        "module_scores": result.get("module_scores"),
        "evaluation": str(evaluation_path),
        "field_audit": str(audit_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry only failed MinerU API shards and score affected articles")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/mineru_method_2015_tablewise_v2")
    parser.add_argument("--articles", nargs="*", help="Optional article IDs; default scans incomplete shard caches")
    parser.add_argument("--tag", default="serial10ms", help="Suffix for new evaluation files")
    parser.add_argument("--skip-retry", action="store_true")
    parser.add_argument(
        "--postprocess-only",
        action="store_true",
        help="Run the source-preserving LLM post-processing stage only; do not replay table/narrative extraction",
    )
    parser.add_argument(
        "--skip-postprocess",
        action="store_true",
        help="Retry table shards only; leave the post-extraction annotation stage for a separate run",
    )
    parser.add_argument("--skip-score", action="store_true")
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    run_id_path = output_root / "RUN_ID.txt"
    if "ARTICLE_AGENT_RUN_ID" not in os.environ and run_id_path.exists():
        os.environ["ARTICLE_AGENT_RUN_ID"] = run_id_path.read_text(encoding="utf-8", errors="replace").strip()
    article_dirs = [output_root / item for item in args.articles] if args.articles else sorted(output_root.glob("2015-*"))
    article_dirs = [path for path in article_dirs if path.is_dir() and (path / "extraction.json").exists()]
    explicit_targets = bool(args.articles)
    client = OpenAICompatibleClient(timeout=max(10, int(os.getenv("ARTICLE_AGENT_API_TIMEOUT", "180"))))
    try:
        table_retries = max(0, min(int(os.getenv("ARTICLE_AGENT_OUTCOME_RETRIES", "2")), 5))
    except (TypeError, ValueError):
        table_retries = 2
    try:
        postprocess_retries = max(0, min(int(os.getenv("ARTICLE_AGENT_OUTCOME_POSTPROCESS_RETRIES", "2")), 5))
    except (TypeError, ValueError):
        postprocess_retries = 2
    # Keep extraction/post-processing retries on the same 5.6-sol model as
    # the primary pass.  5.6-luna is reserved for semantic table routing.
    retry_model = (
        os.getenv("ARTICLE_AGENT_RETRY_MODEL")
        or client.model
    ).strip() or client.model
    retry_client = (
        client
        if retry_model == client.model
        else OpenAICompatibleClient(
            api_key=client.api_key,
            base_url=client.base_url,
            model=retry_model,
            timeout=client.timeout,
        )
    )
    summary = {
        "strategy": "targeted_failed_shards_serial_10ms_then_score",
        "retry_model": retry_model,
        "evaluation_model": os.getenv("ARTICLE_AGENT_EVAL_MODEL") or os.getenv("ARTICLE_AGENT_MODEL", client.model),
        "table_retries": table_retries,
        "postprocess_retries": postprocess_retries,
        "request_delay_seconds": request_delay(),
        "max_workers": workers(),
        "articles": {},
    }
    affected: set[str] = set()

    for article_dir in article_dirs:
        item = summary["articles"].setdefault(article_dir.name, {})
        if args.postprocess_only:
            post_result = retry_postprocessing(article_dir, retry_client, retries=postprocess_retries)
            item["postprocess_retry"] = post_result
            affected.add(article_dir.name)
            continue
        if not args.skip_retry:
            table_result = retry_table_shards(article_dir, retry_client, retries=table_retries)
            item["table_retry"] = table_result
            table_targeted = bool(table_result.get("missing"))
            narrative_result = retry_narrative(article_dir, retry_client, retries=table_retries)
            item["narrative_retry"] = narrative_result
            narrative_targeted = narrative_result.get("status") not in {"skipped", "success"} or bool(
                narrative_result.get("outcome_count")
            )
            post_targeted = has_unresolved_postprocess_error(article_dir)
            if explicit_targets:
                post_targeted = True
                affected.add(article_dir.name)
            if table_targeted:
                affected.add(article_dir.name)
            if narrative_targeted:
                affected.add(article_dir.name)
            if post_targeted:
                affected.add(article_dir.name)
            if args.skip_postprocess:
                post_result = {"status": "skipped", "reason": "cli_skip_postprocess"}
            elif table_targeted or narrative_targeted or post_targeted:
                post_result = retry_postprocessing(article_dir, retry_client, retries=postprocess_retries)
            else:
                post_result = {"status": "skipped", "reason": "no_unresolved_shard_error"}
            item["postprocess_retry"] = post_result
        else:
            # Explicit article selection with --skip-retry is useful for a
            # scoring-only continuation after a manual repair.
            affected.add(article_dir.name)

    if not args.skip_score:
        for article_dir in article_dirs:
            if article_dir.name not in affected:
                continue
            item = summary["articles"].setdefault(article_dir.name, {})
            try:
                item["score"] = score_article(article_dir, args.tag)
            except Exception as exc:  # continue scoring other affected articles
                item["score"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    output_path = output_root / f"RETRY_SCORE_SUMMARY.{args.tag}.json"
    write_json(output_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(
        item.get("score", {}).get("status") != "failed"
        for item in summary["articles"].values()
        if item.get("score")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
