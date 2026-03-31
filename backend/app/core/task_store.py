"""Persistent task history store — records all guest actions and their outcomes."""

import logging
import sqlite3
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS task_history (
    id TEXT PRIMARY KEY,
    guest_id TEXT NOT NULL,
    guest_name TEXT NOT NULL,
    host_id TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    output TEXT,
    detail TEXT,
    batch_id TEXT
)
"""

_PRUNE = """
DELETE FROM task_history WHERE id NOT IN (
    SELECT id FROM task_history ORDER BY started_at DESC LIMIT 500
)
"""


class TaskRecord(BaseModel):
    id: str
    guest_id: str
    guest_name: str
    host_id: str
    action: str          # start|stop|shutdown|restart|snapshot|os_update|backup
    status: str          # pending|running|success|failed
    started_at: str      # ISO 8601
    finished_at: str | None = None
    output: str | None = None   # SSH output for os_update
    detail: str | None = None   # UPID for async actions; error text for failures
    batch_id: str | None = None


class TaskStore:
    """SQLite-backed store for guest action task history."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._conn() as conn:
            conn.execute(_CREATE_TABLE)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, record: TaskRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO task_history
                   (id, guest_id, guest_name, host_id, action, status,
                    started_at, finished_at, output, detail, batch_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.id, record.guest_id, record.guest_name, record.host_id,
                 record.action, record.status, record.started_at,
                 record.finished_at, record.output, record.detail,
                 record.batch_id),
            )
            conn.execute(_PRUNE)

    def update(self, task_id: str, **fields: Any) -> None:
        """Update one or more fields on an existing task record."""
        allowed = {"status", "finished_at", "output", "detail", "batch_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE task_history SET {set_clause} WHERE id = ?", values
            )

    def list_recent(self, limit: int = 200) -> list[TaskRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_history ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [TaskRecord(**dict(row)) for row in rows]

    def clear(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM task_history")
