from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


TERMINAL = {"completed", "failed", "busy", "no_answer", "declined", "canceled", "timed_out"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_phone(number: str) -> str:
    if len(number) <= 7:
        return "***"
    return f"{number[:4]}***{number[-4:]}"


class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    phone_masked TEXT NOT NULL,
                    task_json TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sip_status TEXT,
                    result_json TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    idempotency_key TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS call_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_at TEXT NOT NULL,
                    source TEXT NOT NULL
                );
            """)

    def active_count(self) -> int:
        placeholders = ",".join("?" for _ in TERMINAL)
        with self.connect() as db:
            row = db.execute(f"SELECT COUNT(*) AS n FROM calls WHERE status NOT IN ({placeholders})", tuple(TERMINAL)).fetchone()
            return int(row["n"])

    def by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM calls WHERE idempotency_key = ?", (key,)).fetchone()
        return self._serialize(row) if row else None

    def create(self, call_id: str, phone: str, task: dict[str, Any], mode: str, key: str | None) -> dict[str, Any]:
        timestamp = now()
        with self.lock, self.connect() as db:
            db.execute(
                """INSERT INTO calls(
                    id, created_at, updated_at, phone_number, phone_masked,
                    task_json, mode, status, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (call_id, timestamp, timestamp, phone, mask_phone(phone), json.dumps(task, ensure_ascii=False), mode, "queued", key),
            )
            db.execute("INSERT INTO call_events(call_id,event_type,event_at,source) VALUES (?,?,?,?)", (call_id, "queued", timestamp, "api"))
        return self.get(call_id)

    def set_status(self, call_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        timestamp = now()
        with self.lock, self.connect() as db:
            db.execute(
                "UPDATE calls SET status=?, updated_at=?, result_json=COALESCE(?, result_json) WHERE id=?",
                (status, timestamp, json.dumps(result, ensure_ascii=False) if result else None, call_id),
            )
            db.execute("INSERT INTO call_events(call_id,event_type,event_at,source) VALUES (?,?,?,?)", (call_id, status, timestamp, "mock_dispatch"))

    def get(self, call_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
            events = db.execute("SELECT event_type,event_at,source FROM call_events WHERE call_id=? ORDER BY id", (call_id,)).fetchall()
        if not row:
            return None
        value = self._serialize(row)
        value["events"] = [dict(event) for event in events]
        return value

    def list(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM calls ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._serialize(row) for row in rows]

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["task"] = json.loads(value.pop("task_json"))
        value["result"] = json.loads(value.pop("result_json")) if value.get("result_json") else None
        value.pop("phone_number", None)
        value.pop("idempotency_key", None)
        return value
