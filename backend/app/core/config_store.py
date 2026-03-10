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
_HOST_REQUIRED_KEYS = ("host", "token_id", "token_secret", "node")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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
        self._migrate_multi_host()

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

    def _migrate_multi_host(self) -> None:
        """Promote legacy flat Proxmox fields to a ``proxmox_hosts`` list."""
        data = self.load()
        if not data:
            return
        if "proxmox_hosts" in data:
            return  # already migrated
        if not data.get("proxmox_host"):
            return  # nothing to migrate

        host_entry = {
            "id": "default",
            "label": "Default",
            "host": data.get("proxmox_host", ""),
            "token_id": data.get("proxmox_token_id", ""),
            "token_secret": data.get("proxmox_token_secret", ""),
            "node": data.get("proxmox_node", ""),
            "verify_ssl": data.get("verify_ssl", False),
            "ssh_username": data.get("ssh_username", "root"),
            "ssh_password": data.get("ssh_password", ""),
            "ssh_key_path": data.get("ssh_key_path", ""),
            "pct_exec_enabled": False,
        }
        data["proxmox_hosts"] = [host_entry]
        self.save(data)
        logger.info("Migrated single-host config to proxmox_hosts list")

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
        """True if at least one host has all required fields (from DB or env)."""
        return len(self.get_missing_fields()) == 0

    def get_missing_fields(self) -> list[str]:
        """Return names of required fields that are missing or empty.

        Checks ``proxmox_hosts`` first (multi-host); falls back to legacy
        flat fields for backward compatibility.
        """
        file_data = self.load()
        hosts = file_data.get("proxmox_hosts")
        if isinstance(hosts, list) and hosts:
            # Check that at least one host has all required keys
            for host in hosts:
                if isinstance(host, dict) and all(host.get(k) for k in _HOST_REQUIRED_KEYS):
                    return []
            # None of the hosts are fully configured -- report host-level missing
            first = hosts[0] if hosts else {}
            if isinstance(first, dict):
                return [k for k in _HOST_REQUIRED_KEYS if not first.get(k)]
            return list(_HOST_REQUIRED_KEYS)

        # Legacy flat fields
        missing: list[str] = []
        for field in REQUIRED_FIELDS:
            value = file_data.get(field) or os.environ.get(field.upper(), "") or os.environ.get(field, "")
            if not value:
                missing.append(field)
        return missing

    def merge_into_settings(self, settings: Settings) -> Settings:
        """Return a new Settings instance with DB values taking priority over env/defaults."""
        from app.config import AppConfig, ProxmoxHostConfig, Settings as SettingsCls

        config_data = self.load()
        if not config_data:
            return settings
        current = settings.model_dump()
        for key, value in config_data.items():
            if key == "app_config":
                if isinstance(value, dict):
                    merged_apps: dict = {}
                    for k, v in value.items():
                        if isinstance(v, dict):
                            try:
                                merged_apps[k] = AppConfig(**v)
                            except Exception as exc:
                                logger.warning("Skipping invalid app_config entry '%s': %s", k, exc)
                        else:
                            merged_apps[k] = v
                    current["app_config"] = merged_apps
            elif key == "proxmox_hosts":
                if isinstance(value, list):
                    merged_hosts: list = []
                    for i, h in enumerate(value):
                        if isinstance(h, dict):
                            try:
                                merged_hosts.append(ProxmoxHostConfig(**h))
                            except Exception as exc:
                                logger.warning("Skipping invalid proxmox_hosts[%d]: %s", i, exc)
                        else:
                            merged_hosts.append(h)
                    current["proxmox_hosts"] = merged_hosts
            elif key in current and value is not None:
                current[key] = value
        return SettingsCls(**current)
