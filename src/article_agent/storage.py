from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            create table if not exists runs (
                run_id text primary key,
                created_at text,
                status text,
                metadata_json text
            )
            """
        )
        conn.execute(
            """
            create table if not exists records (
                run_id text,
                record_type text,
                record_id text,
                payload_json text,
                primary key (run_id, record_type, record_id)
            )
            """
        )
        conn.execute(
            """
            create table if not exists logs (
                run_id text,
                seq integer primary key autoincrement,
                event_json text
            )
            """
        )


def write_run(path: Path, run_id: str, created_at: str, status: str, metadata: dict[str, Any]) -> None:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "insert or replace into runs(run_id, created_at, status, metadata_json) values (?, ?, ?, ?)",
            (run_id, created_at, status, json.dumps(metadata, ensure_ascii=False)),
        )


def write_record(path: Path, run_id: str, record_type: str, record_id: str, payload: dict[str, Any]) -> None:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "insert or replace into records(run_id, record_type, record_id, payload_json) values (?, ?, ?, ?)",
            (run_id, record_type, record_id, json.dumps(payload, ensure_ascii=False, default=str)),
        )


def write_log(path: Path, run_id: str, event: dict[str, Any]) -> None:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("insert into logs(run_id, event_json) values (?, ?)", (run_id, json.dumps(event, ensure_ascii=False, default=str)))
