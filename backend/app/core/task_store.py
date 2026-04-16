"""Persistent task history store — records all guest actions and their outcomes."""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
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
) AND status NOT IN ('pending', 'running')
"""


class TaskRecord(BaseModel):
    id: str
    guest_id: str
    guest_name: str
    host_id: str
    action: str          # start|stop|shutdown|restart|snapshot|os_update|backup
    status: str          # pending|running|success|failed|skipped
    started_at: str      # ISO 8601
    finished_at: str | None = None
    output: str | None = None   # SSH output for os_update
    detail: str | None = None   # UPID for async actions; error text for failures
    batch_id: str | None = None


class TaskStore:
    """SQLite-backed store for guest action task history."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create(self, record: TaskRecord) -> None:
        with self._connect() as conn:
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
        with self._connect() as conn:
            conn.execute(
                f"UPDATE task_history SET {set_clause} WHERE id = ?", values
            )

    def list_recent(self, limit: int = 200) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_history ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [TaskRecord(**dict(row)) for row in rows]

    def list_recent_batched_tasks(self, limit: int = 50) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM task_history
                   WHERE batch_id IN (
                       SELECT batch_id FROM (
                           SELECT batch_id, MAX(started_at) AS m
                           FROM task_history
                           WHERE batch_id IS NOT NULL
                           GROUP BY batch_id
                           ORDER BY m DESC
                           LIMIT ?
                       )
                   )
                   ORDER BY batch_id, started_at
                   LIMIT 500""",
                (limit,),
            ).fetchall()
        return [TaskRecord(**dict(r)) for r in rows]

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_history WHERE id = ?", (task_id,)
            ).fetchone()
        return TaskRecord(**dict(row)) if row else None

    def list_running_for_guest(self, guest_id: str, action: str) -> list[TaskRecord]:
        """Return all tasks with status='running' for a given guest and action."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_history WHERE guest_id = ? AND action = ? AND status = 'running'",
                (guest_id, action),
            ).fetchall()
        return [TaskRecord(**dict(row)) for row in rows]

    def list_by_batch_id(self, batch_id: str) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_history WHERE batch_id = ? ORDER BY started_at",
                (batch_id,),
            ).fetchall()
        return [TaskRecord(**dict(r)) for r in rows]

    def reconcile_stale_running_tasks(self) -> int:
        """Mark all orphaned running/pending tasks as failed after a restart."""
        finished_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        detail = "Interrupted by proxmon restart"
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE task_history
                SET status = 'failed', detail = ?, finished_at = ?
                WHERE status IN ('running', 'pending')
                """,
                (detail, finished_at),
            )
            return cursor.rowcount

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM task_history")
