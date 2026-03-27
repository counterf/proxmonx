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

# ---------------------------------------------------------------------------
# Field-type mappings
# Every key that config_store.save() persists belongs to exactly one set.
# ---------------------------------------------------------------------------

_SCALAR_STR_FIELDS: frozenset[str] = frozenset({
    "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node",
    "ssh_username", "ssh_key_path", "ssh_password", "ssh_known_hosts_path",
    "github_token", "log_level", "version_detect_method",
    "auth_mode", "auth_username", "auth_password_hash",
    "ntfy_url", "ntfy_token", "proxmon_api_key",
})
_SCALAR_INT_FIELDS: frozenset[str] = frozenset({
    "poll_interval_seconds", "ntfy_priority",
    "notify_disk_threshold", "notify_disk_cooldown_minutes",
})
_SCALAR_BOOL_FIELDS: frozenset[str] = frozenset({
    "discover_vms", "verify_ssl", "ssh_enabled", "notifications_enabled",
    "notify_on_outdated", "trust_proxy_headers",
})
_JSON_FIELDS: frozenset[str] = frozenset({
    "proxmox_hosts", "app_config", "guest_config", "custom_app_defs",
})

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    id                           INTEGER PRIMARY KEY CHECK (id = 1),
    proxmox_host                 TEXT,
    proxmox_token_id             TEXT,
    proxmox_token_secret         TEXT,
    proxmox_node                 TEXT,
    poll_interval_seconds        INTEGER  DEFAULT 300,
    discover_vms                 INTEGER  DEFAULT 0,
    verify_ssl                   INTEGER  DEFAULT 0,
    ssh_enabled                  INTEGER  DEFAULT 1,
    ssh_username                 TEXT     DEFAULT 'root',
    ssh_key_path                 TEXT,
    ssh_password                 TEXT,
    ssh_known_hosts_path         TEXT     DEFAULT '',
    github_token                 TEXT,
    log_level                    TEXT     DEFAULT 'info',
    version_detect_method        TEXT     DEFAULT 'pct_first',
    auth_mode                    TEXT     DEFAULT 'forms',
    auth_username                TEXT     DEFAULT 'root',
    auth_password_hash           TEXT,
    notifications_enabled        INTEGER  DEFAULT 0,
    ntfy_url                     TEXT     DEFAULT '',
    ntfy_token                   TEXT     DEFAULT '',
    ntfy_priority                INTEGER  DEFAULT 3,
    notify_disk_threshold        INTEGER  DEFAULT 95,
    notify_disk_cooldown_minutes INTEGER  DEFAULT 60,
    notify_on_outdated           INTEGER  DEFAULT 1,
    proxmon_api_key              TEXT,
    trust_proxy_headers          INTEGER  DEFAULT 0,
    proxmox_hosts                TEXT     DEFAULT '[]',
    app_config                   TEXT     DEFAULT '{}',
    guest_config                 TEXT     DEFAULT '{}',
    custom_app_defs              TEXT     DEFAULT '[]',
    updated_at                   TEXT     NOT NULL
                                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""


def _dict_to_params(data: dict) -> dict:
    """Convert a settings dict to a column-name → SQLite-value mapping.

    Keys not in the known field sets are silently ignored.
    None values result in SQL NULL (omitting a key from the save dict clears it).
    """
    params: dict = {}
    for key in _SCALAR_STR_FIELDS:
        v = data.get(key)
        params[key] = str(v) if v is not None else None
    for key in _SCALAR_INT_FIELDS:
        v = data.get(key)
        params[key] = int(v) if v is not None else None
    for key in _SCALAR_BOOL_FIELDS:
        v = data.get(key)
        params[key] = int(bool(v)) if v is not None else None
    for key in _JSON_FIELDS:
        v = data.get(key)
        params[key] = json.dumps(v, default=str) if v is not None else None
    return params


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
        """Read settings from SQLite, return as dict.

        None-valued columns are omitted from the result so callers using
        ``.get()`` with defaults continue to work correctly.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
            if row is None:
                return {}
            result: dict = {}
            for key in _SCALAR_STR_FIELDS:
                v = row[key]
                if v is not None:
                    result[key] = v
            for key in _SCALAR_INT_FIELDS:
                v = row[key]
                if v is not None:
                    result[key] = int(v)
            for key in _SCALAR_BOOL_FIELDS:
                v = row[key]
                if v is not None:
                    result[key] = bool(v)
            for key in _JSON_FIELDS:
                raw = row[key]
                if raw is not None:
                    try:
                        result[key] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError) as exc:
                        logger.error("Failed to parse JSON column '%s': %s", key, exc)
            return result

    def load_auth(self) -> dict:
        """Fast-path read of auth fields only (used by auth middleware hot path).

        Avoids loading and JSON-parsing the full settings row on every request.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT auth_mode, auth_password_hash FROM settings WHERE id = 1"
            ).fetchone()
            if row is None:
                return {}
            return {
                "auth_mode": row["auth_mode"] or "forms",
                "auth_password_hash": row["auth_password_hash"] or "",
            }

    def save(self, data: dict) -> None:
        """Write settings to SQLite.

        Every save fully replaces all columns — keys absent from *data* are
        written as NULL, so a subsequent load() will not return them.
        Unknown keys (not in any field-type set) are silently ignored.
        Callers must supply the full settings dict, not a partial patch.
        """
        params = _dict_to_params(data)
        cols = list(params.keys())
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO settings (id, updated_at) "
                "VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
            )
            update_parts = ", ".join(f"{c} = :{c}" for c in cols)
            update_parts += ", updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            conn.execute(f"UPDATE settings SET {update_parts} WHERE id = 1", params)
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
