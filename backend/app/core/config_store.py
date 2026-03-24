"""Config persistence layer using SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

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
        """True if at least one host has all required fields in the DB."""
        return len(self.get_missing_fields()) == 0

    def get_missing_fields(self) -> list[str]:
        """Return names of required fields that are missing or empty."""
        file_data = self.load()
        hosts = file_data.get("proxmox_hosts")
        if isinstance(hosts, list) and hosts:
            for host in hosts:
                if isinstance(host, dict) and all(host.get(k) for k in _HOST_REQUIRED_KEYS):
                    return []
            first = hosts[0] if hosts else {}
            if isinstance(first, dict):
                return [k for k in _HOST_REQUIRED_KEYS if not first.get(k)]
            return list(_HOST_REQUIRED_KEYS)

        return list(_HOST_REQUIRED_KEYS)

    def merge_into_settings(self, settings: Settings) -> Settings:
        """Return a new Settings instance with DB values taking priority over env/defaults.

        Invalid entries inside ``app_config``, ``guest_config``, or
        ``proxmox_hosts`` are logged and skipped so the application can still
        start.  A summary is logged at ERROR level when entries are dropped so
        misconfiguration is clearly visible.
        """
        # Avoid circular imports between config_store and config modules.
        from app.config import AppConfig, CustomAppDef, ProxmoxHostConfig, Settings as SettingsCls

        config_data = self.load()
        if not config_data:
            return settings
        current = settings.model_dump()
        skipped: list[str] = []
        for key, value in config_data.items():
            if key == "app_config":
                if isinstance(value, dict):
                    merged_apps: dict = {}
                    for k, v in value.items():
                        if isinstance(v, dict):
                            try:
                                merged_apps[k] = AppConfig(**v)
                            except Exception as exc:
                                skipped.append(f"app_config[{k}]")
                                logger.warning("Skipping invalid app_config entry '%s': %s", k, exc)
                        else:
                            skipped.append(f"app_config[{k}]")
                            logger.warning("Skipping non-dict app_config entry '%s'", k)
                    current["app_config"] = merged_apps
            elif key == "guest_config":
                if isinstance(value, dict):
                    merged_guests: dict = {}
                    for k, v in value.items():
                        if isinstance(v, dict):
                            try:
                                merged_guests[k] = AppConfig(**v)
                            except Exception as exc:
                                skipped.append(f"guest_config[{k}]")
                                logger.warning("Skipping invalid guest_config entry '%s': %s", k, exc)
                        else:
                            skipped.append(f"guest_config[{k}]")
                            logger.warning("Skipping non-dict guest_config entry '%s'", k)
                    current["guest_config"] = merged_guests
            elif key == "custom_app_defs":
                if isinstance(value, list):
                    merged_custom: list = []
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            try:
                                merged_custom.append(CustomAppDef(**item))
                            except Exception as exc:
                                skipped.append(f"custom_app_defs[{i}]")
                                logger.warning("Skipping invalid custom_app_defs[%d]: %s", i, exc)
                        else:
                            skipped.append(f"custom_app_defs[{i}]")
                            logger.warning("Skipping non-dict custom_app_defs[%d]", i)
                    current["custom_app_defs"] = merged_custom
            elif key == "proxmox_hosts":
                if isinstance(value, list):
                    merged_hosts: list = []
                    for i, h in enumerate(value):
                        if isinstance(h, dict):
                            try:
                                merged_hosts.append(ProxmoxHostConfig(**h))
                            except Exception as exc:
                                skipped.append(f"proxmox_hosts[{i}]")
                                logger.warning("Skipping invalid proxmox_hosts[%d]: %s", i, exc)
                        else:
                            skipped.append(f"proxmox_hosts[{i}]")
                            logger.warning("Skipping non-dict proxmox_hosts[%d]", i)
                    current["proxmox_hosts"] = merged_hosts
            elif key in current and value is not None:
                current[key] = value
        if skipped:
            logger.error(
                "Config merge dropped %d invalid entries: %s",
                len(skipped),
                ", ".join(skipped),
            )
        return SettingsCls(**current)
