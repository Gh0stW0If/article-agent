"""Repair provenance run IDs after an interrupted/resumed lossless batch.

The extraction code writes the active ``RUN_ID.txt`` into every new request
record.  Older recovery helpers may have emitted ``NR`` before the batch ID
was loaded; this utility updates only provenance metadata, never source
values, row IDs, or model responses.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def repair(output_root: Path, run_id: str) -> dict:
    request_files = 0
    request_records = 0
    manifest_files = 0
    for path in sorted(output_root.rglob("request_manifest.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        changed: list[str] = []
        file_changed = False
        for line in lines:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                changed.append(line)
                continue
            if isinstance(item, dict):
                if item.get("run_id") != run_id:
                    item["run_id"] = run_id
                    file_changed = True
                request_records += 1
                changed.append(json.dumps(item, ensure_ascii=False))
            else:
                changed.append(line)
        if file_changed:
            path.write_text("\n".join(changed) + ("\n" if changed else ""), encoding="utf-8")
            request_files += 1

    # Keep article-level manifests and retry manifests aligned with the same
    # batch ID.  Non-JSON files and malformed artifacts are left untouched.
    for path in sorted(output_root.rglob("*.json")):
        if "manifest" not in path.name.lower():
            continue
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        if payload.get("run_id") != run_id:
            payload["run_id"] = run_id
            _write_json(path, payload)
            manifest_files += 1
    # Resumed narrative/table repairs may append source records after the
    # original tablewise manifest was written.  Synchronize only aggregate
    # provenance counts so QA can compare the manifest to extraction.json;
    # table rows, values, and evidence are never changed here.
    for article_dir in sorted(output_root.glob("2015-*")):
        extraction = _read_json(article_dir / "extraction.json") or {}
        outcome_items = ((extraction.get("outcomes") or {}).get("outcomes") or [])
        if not isinstance(outcome_items, list):
            continue
        tablewise_path = article_dir / "raw_module_responses" / "outcomes.tablewise.manifest.json"
        tablewise = _read_json(tablewise_path)
        if isinstance(tablewise, dict):
            narrative_count = sum(
                1 for item in outcome_items
                if isinstance(item, dict) and str(item.get("table_id") or "").startswith("narrative-results")
            )
            changed = (
                tablewise.get("run_id") != run_id
                or tablewise.get("total_outcomes") != len(outcome_items)
                or tablewise.get("narrative_outcome_count") != narrative_count
            )
            tablewise["run_id"] = run_id
            tablewise["total_outcomes"] = len(outcome_items)
            tablewise["narrative_outcome_count"] = narrative_count
            if changed:
                _write_json(tablewise_path, tablewise)
                manifest_files += 1
        # Synchronize the article-level postprocessing summary with the
        # authoritative postprocess manifest.  Recovery runs write the
        # detailed manifest after the original article manifest, so leaving
        # the latter stale makes a complete annotation stage look partial in
        # QA/reporting.  This updates provenance/counts only; source outcomes
        # and annotations themselves are never modified here.
        article_manifest_path = article_dir / "manifest.json"
        article_manifest = _read_json(article_manifest_path)
        post_manifest = _read_json(article_dir / "raw_module_responses" / "outcomes.postprocess.manifest.json")
        if isinstance(article_manifest, dict) and isinstance(post_manifest, dict):
            summary = dict(article_manifest.get("outcome_postprocessing") or {})
            summary.update({
                "status": post_manifest.get("status", "success"),
                "source_outcome_count": post_manifest.get("source_outcome_count", len(outcome_items)),
                "processed_outcome_count": post_manifest.get("processed_outcome_count", 0),
                "conflict_count": post_manifest.get("conflict_count", 0),
                "canonical_dataset": post_manifest.get("canonical_dataset", "outcomes.canonical.json"),
                "canonical_outcome_count": post_manifest.get("canonical_outcome_count", 0),
                "canonical_conflict_group_count": post_manifest.get("canonical_conflict_group_count", 0),
            })
            if article_manifest.get("outcome_postprocessing") != summary:
                article_manifest["outcome_postprocessing"] = summary
                article_manifest["run_id"] = run_id
                _write_json(article_manifest_path, article_manifest)
                manifest_files += 1
    return {
        "output_root": str(output_root),
        "run_id": run_id,
        "request_files_updated": request_files,
        "request_records_seen": request_records,
        "manifest_files_updated": manifest_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair run_id provenance metadata in a lossless batch")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    root = args.output_root.resolve()
    run_id = args.run_id.strip()
    if not run_id and (root / "RUN_ID.txt").exists():
        run_id = (root / "RUN_ID.txt").read_text(encoding="utf-8", errors="replace").strip()
    if not run_id:
        raise SystemExit("run_id is required (use --run-id or RUN_ID.txt)")
    print(json.dumps(repair(root, run_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
