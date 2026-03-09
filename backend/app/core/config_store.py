"""Config persistence layer using SQLite."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%%H:%%M:%%SZ', 'now'))
)
"""

_UPSERT = """
INSERT INTO settings (id, data, updated_at)
VALUES (1, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
"""


class ConfigStore:
    """Manages reading/writing of settings in a SQLite database."""

    def __init__(self, path: str = "/app/data/proxmon.db") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_from_json()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    def _migrate_from_json(self) -> None:
        """One-time migration: import config.json into SQLite if DB is empty."""
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM settings WHERE id = 1").fetchone()
            if row is not None:
                return

        json_path = self._path.parent / "config.json"
        if not json_path.exists():
            return

        try:
            raw = json_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return
            self.save(data)
            logger.info("Migrated config.json \u2192 SQLite (%s)", self._path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to migrate config.json: %s", exc)

    def load(self) -> dict:
        """Read settings from SQLite, return as dict."""
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
            if row is None:
                return {}
            try:
                data = json.loads(row["data"])
                if not isinstance(data, dict):
                    logger.error("Settings data is not a JSON object, ignoring")
                    return {}
                return data
            except (json.JSONDecodeError, TypeError) as exc:
                logger.error("Failed to parse settings data: %s", exc)
                return {}

    def save(self, data: dict) -> None:
        """Write settings to SQLite (upsert single row)."""
        payload = json.dumps(data, indent=2, default=str)
        with self._connect() as conn:
            conn.execute(_UPSERT, (payload,))
        logger.info("Settings saved via UI")

    def is_configured(self) -> bool:
        """True if all required Proxmox fields are non-empty (from DB or env)."""
        return len(self.get_missing_fields()) == 0

    def get_missing_fields(self) -> list[str]:
        """Return names of required fields that are missing or empty."""
        file_data = self.load()
        missing: list[str] = []
        for field in REQUIRED_FIELDS:
            value = file_data.get(field) or os.environ.get(field.upper(), "") or os.environ.get(field, "")
            if not value:
                missing.append(field)
        return missing

    def merge_into_settings(self, settings: Settings) -> Settings:
        """Return a new Settings instance with DB values taking priority over env/defaults."""
        from app.config import AppConfig, Settings as SettingsCls

        config_data = self.load()
        if not config_data:
            return settings
        current = settings.model_dump()
        for key, value in config_data.items():
            if key == "app_config":
                if isinstance(value, dict):
                    current["app_config"] = {
                        k: AppConfig(**v) if isinstance(v, dict) else v
                        for k, v in value.items()
                    }
            elif key in current and value is not None:
                current[key] = value
        return SettingsCls(**current)
