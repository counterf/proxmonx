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
# Every scalar key belongs to exactly one set.
# ---------------------------------------------------------------------------

_SCALAR_STR_FIELDS: frozenset[str] = frozenset({
    "ssh_username", "ssh_key_path", "ssh_password", "ssh_known_hosts_path",
    "github_token", "log_level", "version_detect_method",
    "auth_mode", "auth_username", "auth_password_hash",
    "ntfy_url", "ntfy_token", "proxmon_api_key",
})
_SCALAR_INT_FIELDS: frozenset[str] = frozenset({
    "poll_interval_seconds", "ntfy_priority",
    "notify_disk_threshold", "notify_disk_cooldown_minutes",
    "pending_updates_interval_seconds",
})
_SCALAR_BOOL_FIELDS: frozenset[str] = frozenset({
    "discover_vms", "ssh_enabled", "notifications_enabled",
    "notify_on_outdated", "trust_proxy_headers",
})

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    id                           INTEGER PRIMARY KEY CHECK (id = 1),
    poll_interval_seconds        INTEGER  DEFAULT 3600,
    pending_updates_interval_seconds INTEGER DEFAULT 3600,
    discover_vms                 INTEGER  DEFAULT 0,
    ssh_enabled                  INTEGER  DEFAULT 1,
    ssh_username                 TEXT     DEFAULT 'root',
    ssh_key_path                 TEXT,
    ssh_password                 TEXT,
    ssh_known_hosts_path         TEXT     DEFAULT '',
    github_token                 TEXT,
    log_level                    TEXT     DEFAULT 'info',
    version_detect_method        TEXT     DEFAULT 'pct_first',
    auth_mode                    TEXT     DEFAULT 'disabled',
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
    updated_at                   TEXT     NOT NULL
                                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_CREATE_PROXMOX_HOSTS = """
CREATE TABLE IF NOT EXISTS proxmox_hosts (
    id              TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    host            TEXT NOT NULL,
    token_id        TEXT NOT NULL DEFAULT '',
    token_secret    TEXT NOT NULL DEFAULT '',
    node            TEXT NOT NULL DEFAULT '',
    ssh_username    TEXT NOT NULL DEFAULT 'root',
    ssh_password    TEXT,
    ssh_key_path    TEXT,
    pct_exec_enabled INTEGER NOT NULL DEFAULT 0,
    backup_storage  TEXT
)
"""

_CREATE_APP_CONFIG = """
CREATE TABLE IF NOT EXISTS app_config (
    app_name        TEXT PRIMARY KEY,
    port            INTEGER,
    api_key         TEXT,
    scheme          TEXT,
    github_repo     TEXT,
    ssh_version_cmd TEXT,
    ssh_username    TEXT,
    ssh_key_path    TEXT,
    ssh_password    TEXT
)
"""

_CREATE_GUEST_CONFIG = """
CREATE TABLE IF NOT EXISTS guest_config (
    guest_id        TEXT PRIMARY KEY,
    port            INTEGER,
    api_key         TEXT,
    scheme          TEXT,
    github_repo     TEXT,
    ssh_version_cmd TEXT,
    ssh_username    TEXT,
    ssh_key_path    TEXT,
    ssh_password    TEXT,
    forced_detector TEXT,
    version_host    TEXT
)
"""

_CREATE_CUSTOM_APP_DEFS = """
CREATE TABLE IF NOT EXISTS custom_app_defs (
    name            TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    default_port    INTEGER NOT NULL,
    scheme          TEXT NOT NULL DEFAULT 'http',
    version_path    TEXT,
    github_repo     TEXT,
    aliases         TEXT NOT NULL DEFAULT '[]',
    docker_images   TEXT NOT NULL DEFAULT '[]',
    accepts_api_key INTEGER NOT NULL DEFAULT 0,
    auth_header     TEXT,
    version_keys    TEXT NOT NULL DEFAULT '["version"]',
    strip_v         INTEGER NOT NULL DEFAULT 0
)
"""

# Registry of all table DDLs for column migration.
_TABLE_DDLS: dict[str, str] = {
    "settings": _CREATE_TABLE,
    "proxmox_hosts": _CREATE_PROXMOX_HOSTS,
    "app_config": _CREATE_APP_CONFIG,
    "guest_config": _CREATE_GUEST_CONFIG,
    "custom_app_defs": _CREATE_CUSTOM_APP_DEFS,
}

# Columns that can be added via ALTER TABLE ADD COLUMN on upgrade.
# Derived automatically from DDLs so there is a single source of truth.
# DEFAULT is included to skip the continuation line of the multi-line updated_at definition.
_CONSTRAINT_PREFIXES = ("PRIMARY", "CHECK", "UNIQUE", "CONSTRAINT", "CREATE", ")", "DEFAULT")

# Primary key column name per table (excluded from migration).
_TABLE_PK: dict[str, str] = {
    "settings": "id",
    "proxmox_hosts": "id",
    "app_config": "app_name",
    "guest_config": "guest_id",
    "custom_app_defs": "name",
}


def _parse_migratable_columns(ddl: str, *, skip: frozenset[str] | None = None) -> list[tuple[str, str]]:
    """Extract ``(column_name, type_and_default)`` from a CREATE TABLE DDL.

    Skips columns in *skip* (and always skips ``updated_at``) because
    SQLite's ALTER TABLE ADD COLUMN does not support those constraints.
    """
    if skip is None:
        skip = frozenset()
    skip = skip | {"updated_at"}
    result: list[tuple[str, str]] = []
    for raw in ddl.splitlines():
        line = raw.strip().rstrip(",")
        if not line:
            continue
        parts = line.split()
        if not parts:
            continue
        col_name = parts[0]
        if col_name.upper().startswith(_CONSTRAINT_PREFIXES):
            continue
        if col_name in skip:
            continue
        # Everything after the column name is the type + default clause
        typedef = " ".join(parts[1:])
        if typedef:
            result.append((col_name, typedef))
    return result


# Pre-compute migratable columns for every table.
_ALL_MIGRATABLE: dict[str, list[tuple[str, str]]] = {}
for _tbl_name, _tbl_ddl in _TABLE_DDLS.items():
    _pk = _TABLE_PK.get(_tbl_name)
    _skip = frozenset({_pk}) if _pk else frozenset()
    _ALL_MIGRATABLE[_tbl_name] = _parse_migratable_columns(_tbl_ddl, skip=_skip)



def _dict_to_params(data: dict) -> dict:
    """Convert a settings dict to a column-name -> SQLite-value mapping.

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
    return params


# Secret fields per table that should be preserved when "***" is sent.
_HOST_SECRETS = ("token_secret", "ssh_password")
_CONFIG_SECRETS = ("api_key", "ssh_password")

# Custom app defs: JSON list fields that need ser/deser.
_CUSTOM_APP_JSON_FIELDS = ("aliases", "docker_images", "version_keys")
_CUSTOM_APP_BOOL_FIELDS = ("accepts_api_key", "strip_v")


class ConfigStore:
    """Manages reading/writing of settings in a SQLite database."""

    def __init__(self, path: str = "/app/data/proxmon.db") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cached_auth: dict | None = None
        self._cached_is_configured: bool | None = None
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
            for ddl in _TABLE_DDLS.values():
                conn.execute(ddl)
            self._migrate_columns(conn)

    @staticmethod
    def _migrate_columns(conn: sqlite3.Connection) -> None:
        """Add any columns present in the schema but missing from the DB.

        Runs on every startup for all managed tables.
        """
        for table_name, columns in _ALL_MIGRATABLE.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
            for col, typedef in columns:
                if col not in existing:
                    logger.info("Migrating %s table: adding column '%s'", table_name, col)
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {typedef}")

    # ------------------------------------------------------------------
    # load / save (settings scalars + assembled complex fields)
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """Read settings from SQLite, return as dict.

        Assembles the full settings dict from the settings table (scalars)
        and the four normalized tables.
        """
        with self._connect() as conn:
            result: dict = {}
            row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
            if row is not None:
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

            # proxmox_hosts
            hosts = self._list_hosts_conn(conn)
            if hosts:
                result["proxmox_hosts"] = hosts

            # app_config
            app_cfgs = self._list_app_configs_conn(conn)
            if app_cfgs:
                result["app_config"] = app_cfgs

            # guest_config
            guest_cfgs = self._list_guest_configs_conn(conn)
            if guest_cfgs:
                result["guest_config"] = guest_cfgs

            # custom_app_defs
            custom_defs = self._list_custom_app_defs_conn(conn)
            if custom_defs:
                result["custom_app_defs"] = custom_defs

            return result

    def _invalidate_caches(self) -> None:
        """Clear in-memory caches so next access re-reads from SQLite."""
        self._cached_auth = None
        self._cached_is_configured = None

    def load_auth(self) -> dict:
        """Fast-path read of auth fields only (used by middleware + auth routes)."""
        if self._cached_auth is not None:
            return self._cached_auth
        with self._connect() as conn:
            row = conn.execute(
                "SELECT auth_mode, auth_password_hash, auth_username"
                " FROM settings WHERE id = 1"
            ).fetchone()
            if row is None:
                return {}
            result = {
                "auth_mode": row["auth_mode"] or "disabled",
                "auth_password_hash": row["auth_password_hash"] or "",
                "auth_username": row["auth_username"] or "root",
            }
            self._cached_auth = result
            return result

    def save_full(
        self,
        scalars: dict,
        hosts: list[dict] | None = None,
        app_configs: dict[str, dict] | None = None,
    ) -> None:
        """Atomically save scalars, hosts, and app configs in one transaction.

        *hosts*: if not None, replaces all hosts (deletes removed, upserts incoming).
        *app_configs*: if not None, upserts each entry (preserves entries not in payload).
        Secret fields ("***" / None) are preserved from existing rows.
        """
        params = _dict_to_params(scalars)
        cols = list(params.keys())

        with self._connect() as conn:
            # 1) Scalar settings
            conn.execute(
                "INSERT OR IGNORE INTO settings (id, updated_at) "
                "VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
            )
            update_parts = ", ".join(f"{c} = :{c}" for c in cols)
            update_parts += ", updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            conn.execute(f"UPDATE settings SET {update_parts} WHERE id = 1", params)

            # 2) Proxmox hosts
            if hosts is not None:
                incoming_ids = {h["id"] for h in hosts}
                existing_ids = {
                    dict(r)["id"]
                    for r in conn.execute("SELECT id FROM proxmox_hosts").fetchall()
                }
                for removed_id in existing_ids - incoming_ids:
                    conn.execute("DELETE FROM proxmox_hosts WHERE id = ?", (removed_id,))
                for h in hosts:
                    self._upsert_host_conn(conn, h, preserve_secrets=True)

            # 3) App configs (upsert, not replace-all)
            if app_configs is not None:
                for app_name, app_data in app_configs.items():
                    self._upsert_app_config_conn(conn, app_name, app_data, preserve_secrets=True)

        self._invalidate_caches()
        logger.info("Settings saved via UI (atomic)")

    # ------------------------------------------------------------------
    # proxmox_hosts CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_host(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["pct_exec_enabled"] = bool(d.get("pct_exec_enabled", 0))
        return d

    @staticmethod
    def _list_hosts_conn(conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute("SELECT * FROM proxmox_hosts").fetchall()
        return [ConfigStore._row_to_host(r) for r in rows]

    def list_hosts(self) -> list[dict]:
        with self._connect() as conn:
            return self._list_hosts_conn(conn)

    def get_host(self, host_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proxmox_hosts WHERE id = ?", (host_id,)).fetchone()
            return self._row_to_host(row) if row else None

    @staticmethod
    def _upsert_host_conn(conn: sqlite3.Connection, data: dict, *, preserve_secrets: bool = False) -> None:
        host_id = data.get("id", "")
        if preserve_secrets:
            existing = conn.execute("SELECT * FROM proxmox_hosts WHERE id = ?", (host_id,)).fetchone()
            if existing:
                existing = dict(existing)
                for secret in _HOST_SECRETS:
                    val = data.get(secret)
                    if val is None or val == "***":
                        data[secret] = existing.get(secret)

        conn.execute(
            "INSERT OR REPLACE INTO proxmox_hosts "
            "(id, label, host, token_id, token_secret, node, ssh_username, "
            "ssh_password, ssh_key_path, pct_exec_enabled, backup_storage) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.get("id", ""),
                data.get("label", ""),
                data.get("host", ""),
                data.get("token_id", ""),
                data.get("token_secret", ""),
                data.get("node", ""),
                data.get("ssh_username", "root"),
                data.get("ssh_password"),
                data.get("ssh_key_path"),
                int(bool(data.get("pct_exec_enabled", False))),
                data.get("backup_storage"),
            ),
        )

    def upsert_host(self, data: dict) -> None:
        with self._connect() as conn:
            self._upsert_host_conn(conn, data, preserve_secrets=True)
        self._invalidate_caches()

    def delete_host(self, host_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM proxmox_hosts WHERE id = ?", (host_id,))
        self._invalidate_caches()

    # ------------------------------------------------------------------
    # app_config CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_app_config(row: sqlite3.Row) -> dict:
        """Convert a row to a dict, omitting None-valued fields and the PK."""
        d = dict(row)
        d.pop("app_name", None)
        return {k: v for k, v in d.items() if v is not None}

    @staticmethod
    def _list_app_configs_conn(conn: sqlite3.Connection) -> dict[str, dict]:
        rows = conn.execute("SELECT * FROM app_config").fetchall()
        result: dict[str, dict] = {}
        for r in rows:
            d = dict(r)
            name = d.pop("app_name")
            clean = {k: v for k, v in d.items() if v is not None}
            if clean:
                result[name] = clean
        return result

    def list_app_configs(self) -> dict[str, dict]:
        with self._connect() as conn:
            return self._list_app_configs_conn(conn)

    def get_app_config(self, app_name: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM app_config WHERE app_name = ?", (app_name,)).fetchone()
            return self._row_to_app_config(row) if row else None

    @staticmethod
    def _upsert_app_config_conn(
        conn: sqlite3.Connection, app_name: str, data: dict, *, preserve_secrets: bool = False,
    ) -> None:
        if preserve_secrets:
            existing = conn.execute("SELECT * FROM app_config WHERE app_name = ?", (app_name,)).fetchone()
            if existing:
                existing = dict(existing)
                for secret in _CONFIG_SECRETS:
                    val = data.get(secret)
                    if val is None or val == "***":
                        data[secret] = existing.get(secret)

        conn.execute(
            "INSERT OR REPLACE INTO app_config "
            "(app_name, port, api_key, scheme, github_repo, ssh_version_cmd, "
            "ssh_username, ssh_key_path, ssh_password) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                app_name,
                data.get("port"),
                data.get("api_key"),
                data.get("scheme"),
                data.get("github_repo"),
                data.get("ssh_version_cmd"),
                data.get("ssh_username"),
                data.get("ssh_key_path"),
                data.get("ssh_password"),
            ),
        )

    def upsert_app_config(self, app_name: str, data: dict) -> None:
        with self._connect() as conn:
            self._upsert_app_config_conn(conn, app_name, data, preserve_secrets=True)
        self._invalidate_caches()

    def delete_app_config(self, app_name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM app_config WHERE app_name = ?", (app_name,))
        self._invalidate_caches()

    # ------------------------------------------------------------------
    # guest_config CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_guest_config(row: sqlite3.Row) -> dict:
        d = dict(row)
        d.pop("guest_id", None)
        return {k: v for k, v in d.items() if v is not None}

    @staticmethod
    def _list_guest_configs_conn(conn: sqlite3.Connection) -> dict[str, dict]:
        rows = conn.execute("SELECT * FROM guest_config").fetchall()
        result: dict[str, dict] = {}
        for r in rows:
            d = dict(r)
            gid = d.pop("guest_id")
            clean = {k: v for k, v in d.items() if v is not None}
            if clean:
                result[gid] = clean
        return result

    def list_guest_configs(self) -> dict[str, dict]:
        with self._connect() as conn:
            return self._list_guest_configs_conn(conn)

    def get_guest_config(self, guest_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM guest_config WHERE guest_id = ?", (guest_id,)).fetchone()
            return self._row_to_guest_config(row) if row else None

    @staticmethod
    def _upsert_guest_config_conn(
        conn: sqlite3.Connection, guest_id: str, data: dict, *, preserve_secrets: bool = False,
    ) -> None:
        if preserve_secrets:
            existing = conn.execute("SELECT * FROM guest_config WHERE guest_id = ?", (guest_id,)).fetchone()
            if existing:
                existing = dict(existing)
                for secret in _CONFIG_SECRETS:
                    val = data.get(secret)
                    if val is None or val == "***":
                        data[secret] = existing.get(secret)

        conn.execute(
            "INSERT OR REPLACE INTO guest_config "
            "(guest_id, port, api_key, scheme, github_repo, ssh_version_cmd, "
            "ssh_username, ssh_key_path, ssh_password, forced_detector, version_host) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guest_id,
                data.get("port"),
                data.get("api_key"),
                data.get("scheme"),
                data.get("github_repo"),
                data.get("ssh_version_cmd"),
                data.get("ssh_username"),
                data.get("ssh_key_path"),
                data.get("ssh_password"),
                data.get("forced_detector"),
                data.get("version_host"),
            ),
        )

    def upsert_guest_config(self, guest_id: str, data: dict) -> None:
        with self._connect() as conn:
            self._upsert_guest_config_conn(conn, guest_id, data, preserve_secrets=True)
        self._invalidate_caches()

    def delete_guest_config(self, guest_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM guest_config WHERE guest_id = ?", (guest_id,))
        self._invalidate_caches()

    # ------------------------------------------------------------------
    # custom_app_defs CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_custom_app_def(row: sqlite3.Row) -> dict:
        d = dict(row)
        for f in _CUSTOM_APP_JSON_FIELDS:
            raw = d.get(f)
            if isinstance(raw, str):
                try:
                    d[f] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d[f] = []
        for f in _CUSTOM_APP_BOOL_FIELDS:
            d[f] = bool(d.get(f, 0))
        return d

    @staticmethod
    def _list_custom_app_defs_conn(conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute("SELECT * FROM custom_app_defs").fetchall()
        return [ConfigStore._row_to_custom_app_def(r) for r in rows]

    def list_custom_app_defs(self) -> list[dict]:
        with self._connect() as conn:
            return self._list_custom_app_defs_conn(conn)

    def get_custom_app_def(self, name: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM custom_app_defs WHERE name = ?", (name,)).fetchone()
            return self._row_to_custom_app_def(row) if row else None

    @staticmethod
    def _upsert_custom_app_def_conn(conn: sqlite3.Connection, data: dict) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO custom_app_defs "
            "(name, display_name, default_port, scheme, version_path, github_repo, "
            "aliases, docker_images, accepts_api_key, auth_header, version_keys, strip_v) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.get("name", ""),
                data.get("display_name", ""),
                data.get("default_port", 0),
                data.get("scheme", "http"),
                data.get("version_path"),
                data.get("github_repo"),
                json.dumps(data.get("aliases", []), default=str),
                json.dumps(data.get("docker_images", []), default=str),
                int(bool(data.get("accepts_api_key", False))),
                data.get("auth_header"),
                json.dumps(data.get("version_keys", ["version"]), default=str),
                int(bool(data.get("strip_v", False))),
            ),
        )

    def upsert_custom_app_def(self, data: dict) -> None:
        with self._connect() as conn:
            self._upsert_custom_app_def_conn(conn, data)
        self._invalidate_caches()

    def delete_custom_app_def(self, name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM custom_app_defs WHERE name = ?", (name,))
        self._invalidate_caches()

    def update_scalar(self, key: str, value) -> None:
        """Update a single scalar field in the settings table.

        Only touches the one column -- no DELETE/INSERT on normalized tables.
        """
        all_fields = _SCALAR_STR_FIELDS | _SCALAR_INT_FIELDS | _SCALAR_BOOL_FIELDS
        if key not in all_fields:
            raise ValueError(f"Unknown scalar field: {key!r}")
        if key in _SCALAR_BOOL_FIELDS:
            db_val = int(bool(value)) if value is not None else None
        elif key in _SCALAR_INT_FIELDS:
            db_val = int(value) if value is not None else None
        else:
            db_val = str(value) if value is not None else None
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO settings (id, updated_at) "
                "VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
            )
            # safe: `key` validated against known column set above
            conn.execute(
                f"UPDATE settings SET {key} = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = 1",
                (db_val,),
            )
        self._invalidate_caches()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """True if at least one host has all required fields in the DB."""
        if self._cached_is_configured is not None:
            return self._cached_is_configured
        result = len(self.get_missing_fields()) == 0
        self._cached_is_configured = result
        return result

    def get_missing_fields(self) -> list[str]:
        """Return names of required fields that are missing or empty."""
        hosts = self.list_hosts()
        if not isinstance(hosts, list) or not hosts:
            return list(_HOST_REQUIRED_KEYS)
        for host in hosts:
            if isinstance(host, dict) and all(host.get(k) for k in _HOST_REQUIRED_KEYS):
                return []
        best = max(
            (h for h in hosts if isinstance(h, dict)),
            key=lambda h: sum(1 for k in _HOST_REQUIRED_KEYS if h.get(k)),
            default={},
        )
        return [k for k in _HOST_REQUIRED_KEYS if not best.get(k)]

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
