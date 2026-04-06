"""Session storage backed by SQLite."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class SessionStore:
    """Manages browser sessions in the same SQLite database as config."""

    def __init__(self, db_path: str, ttl_seconds: int = 86400) -> None:
        self._path = Path(db_path)
        self._ttl = ttl_seconds
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_table(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(token TEXT PRIMARY KEY, expires_at TEXT NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()

    def create(self) -> str:
        """Create a new session token and return it."""
        self.cleanup_expired()
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(seconds=self._ttl)).isoformat()
        conn = self._connect()
        try:
            conn.execute("INSERT INTO sessions (token, expires_at) VALUES (?, ?)", (token, expires))
            conn.commit()
        finally:
            conn.close()
        return token

    def is_valid(self, token: str) -> bool:
        """Check whether a token exists and has not expired."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT expires_at FROM sessions WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                return False
            expires_at = datetime.fromisoformat(row[0])
            if datetime.now(timezone.utc) >= expires_at:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
                return False
            return True
        finally:
            conn.close()

    def revoke(self, token: str) -> None:
        """Delete a session token."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        finally:
            conn.close()

    def revoke_all(self, *, except_token: str | None = None) -> None:
        """Delete all session tokens, optionally keeping one token."""
        conn = self._connect()
        try:
            if except_token:
                conn.execute("DELETE FROM sessions WHERE token != ?", (except_token,))
            else:
                conn.execute("DELETE FROM sessions")
            conn.commit()
        finally:
            conn.close()

    def cleanup_expired(self) -> None:
        """Remove all expired sessions."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            conn.commit()
        finally:
            conn.close()
