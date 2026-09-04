from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from article_agent.models import OpenAICompatibleClient
from evaluate_2015_01 import _lossless_table_evidence_contexts


def main() -> None:
    payload_path = Path(__import__("os").getenv(
        "ARTICLE_AGENT_PROBE_PAYLOAD",
        str(ROOT / "outputs/mineru_method_lossless_sol_luna_v5/2015-01/raw_module_responses/evaluation_outcomes/evaluation_input.lossless_sol_v5.outcomes.part-0001.json"),
    ))
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if "--all-table" in sys.argv:
        extraction = json.loads((ROOT / "outputs/mineru_method_lossless_sol_luna_v5/2015-01/extraction.json").read_text(encoding="utf-8"))
        all_records = extraction.get("outcomes", {}).get("outcomes", [])
        records = [item for item in all_records if isinstance(item, dict) and str(item.get("table_id", "")) == "table-003"]
        try:
            requested_rows = max(1, int(__import__("os").getenv("ARTICLE_AGENT_PROBE_ROWS", "0")))
        except ValueError:
            requested_rows = 0
        if requested_rows:
            records = records[:requested_rows]
        payload["candidate_records"] = [{"source_index": i, "record": item} for i, item in enumerate(records)]
        payload["source_contexts"] = [{
            "source_index": i,
            "table_id": item.get("table_id", "NR"),
            "row_id": item.get("row_id", "NR"),
            "unit_id": "u0001",
            "row_evidence": item.get("source_evidence", "NR"),
        } for i, item in enumerate(records)]
        table_contexts = _lossless_table_evidence_contexts(ROOT / "outputs/mineru_method_lossless_sol_luna_v5/2015-01")
        payload["source_context_units"] = [{"unit_id": "u0001", "table_id": "table-003", "row_ids": [item.get("row_id", "NR") for item in records], "source_indices": list(range(len(records))), "context": table_contexts.get("table-003", "") }]
        payload["json_template"]["row_audits"] = [{"source_index": i, "module_score": 0, "module_verdict": "string", "field_findings": [], "strengths": [], "weaknesses": [], "gold_quality_notes": []} for i in range(len(records))]
        payload["field_definitions"]["source_indices"] = list(range(len(records)))
        payload["field_definitions"]["source_index"] = list(range(len(records)))
    # Keep one complete row and the complete table evidence for diagnosis.
    if "--tiny" in sys.argv:
        payload = {"ping": "return JSON", "json_template": {"ok": True}}
    elif "--all-table" not in sys.argv:
        try:
            row_count = max(1, int(__import__("os").getenv("ARTICLE_AGENT_PROBE_ROWS", "1")))
        except ValueError:
            row_count = 1
        payload["candidate_records"] = payload["candidate_records"][:row_count]
        payload["source_contexts"] = payload["source_contexts"][:row_count]
        payload["json_template"]["row_audits"] = payload["json_template"]["row_audits"][:row_count]
        table_contexts = _lossless_table_evidence_contexts(ROOT / "outputs/mineru_method_lossless_sol_luna_v5/2015-01")
        for unit in payload.get("source_context_units", []):
            if isinstance(unit, dict) and unit.get("table_id") in table_contexts:
                unit["context"] = table_contexts[unit["table_id"]]
    if "--all-table" not in sys.argv and "--tiny" not in sys.argv:
        try:
            row_count = max(1, int(__import__("os").getenv("ARTICLE_AGENT_PROBE_ROWS", "1")))
        except ValueError:
            row_count = 1
        payload["candidate_records"] = payload["candidate_records"][:row_count]
        payload["source_contexts"] = payload["source_contexts"][:row_count]
        payload["json_template"]["row_audits"] = payload["json_template"]["row_audits"][:row_count]
    if "--minimal" in sys.argv:
        payload["task_description"] = "For every source_index, score extraction quality against the complete evidence and Gold. Cover every index. Return only source_index, an integer module_score, and a verdict of at most 20 words. Never alter source values."
        payload["field_definitions"] = {"source_indices": [item.get("source_index") for item in payload.get("candidate_records", [])], "source_context_rule": "resolve source_contexts.unit_id; row_evidence is verbatim"}
        payload["json_template"] = {"row_audits": [{"source_index": item.get("source_index"), "module_score": 0, "module_verdict": "at most 20 words"} for item in payload.get("candidate_records", [])]}
    messages = [
        {"role": "system", "content": "You are an independent medical RCT extraction quality auditor. Return one JSON object only."},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    print(f"payload_bytes={len(messages[1]['content'].encode('utf-8'))}", flush=True)
    try:
        timeout = int(__import__("os").getenv("ARTICLE_AGENT_PROBE_TIMEOUT", "15"))
    except ValueError:
        timeout = 15
    client = OpenAICompatibleClient(model="gpt-5.6-sol", timeout=timeout)
    endpoints = list(client.base_urls)
    for endpoint in endpoints:
        client.base_url = endpoint
        client.base_urls = [endpoint]
        started = time.time()
        try:
            result = client.chat_json(messages)
            audits = result.get("row_audits") if isinstance(result, dict) else None
            expected = {item.get("source_index") for item in payload.get("candidate_records", [])}
            returned = {item.get("source_index") for item in audits if isinstance(item, dict)} if isinstance(audits, list) else set()
            if returned != expected:
                raise RuntimeError(f"source_index coverage mismatch: expected={sorted(expected)}, returned={sorted(returned)}")
            print(f"success endpoint={client.base_url} elapsed={time.time()-started:.1f}s rows={len(returned)} keys={sorted(result)[:8]}", flush=True)
            return
        except Exception as exc:
            print(f"error endpoint={endpoint} elapsed={time.time()-started:.1f}s type={type(exc).__name__} msg={str(exc)[:300]}", flush=True)


if __name__ == "__main__":
    main()
