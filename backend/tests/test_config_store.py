"""Tests for ConfigStore: SQLite-backed config persistence."""

from pathlib import Path

import pytest

from app.config import AppConfig, CustomAppDef, ProxmoxHostConfig, Settings
from app.core.config_store import ConfigStore, _MIGRATABLE_COLUMNS, _CREATE_TABLE


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "proxmon.db"


@pytest.fixture()
def store(db_path: Path) -> ConfigStore:
    return ConfigStore(str(db_path))


_FULL_CONFIG = {
    "proxmox_hosts": [{
        "id": "pve1", "label": "PVE1",
        "host": "https://10.0.0.1:8006",
        "token_id": "root@pam!test",
        "token_secret": "secret-uuid",
        "node": "pve",
    }],
}


class TestSaveLoadRoundTrip:
    def test_roundtrip(self, store: ConfigStore) -> None:
        original = {"poll_interval_seconds": 120, "discover_vms": True}
        store.save(original)
        assert store.load() == original

    def test_load_empty_db_returns_empty_dict(self, store: ConfigStore) -> None:
        assert store.load() == {}


class TestIsConfigured:
    def test_false_when_empty(self, store: ConfigStore) -> None:
        assert store.is_configured() is False

    def test_true_when_host_fully_configured(self, store: ConfigStore) -> None:
        store.save({
            "proxmox_hosts": [{
                "id": "pve1", "label": "PVE1",
                "host": "https://10.0.0.1:8006",
                "token_id": "root@pam!test",
                "token_secret": "secret-uuid",
                "node": "pve",
            }],
        })
        assert store.is_configured() is True


class TestGetMissingFields:
    def test_returns_all_when_empty(self, store: ConfigStore) -> None:
        assert set(store.get_missing_fields()) == {
            "host", "token_id", "token_secret", "node",
        }


class TestSaveIdempotent:
    def test_second_save_overwrites_first(self, store: ConfigStore) -> None:
        store.save({"log_level": "debug"})
        store.save({"poll_interval_seconds": 60})
        data = store.load()
        assert "log_level" not in data
        assert data["poll_interval_seconds"] == 60


class TestMergeIntoSettings:
    def test_merges_basic_fields(self, store: ConfigStore) -> None:
        store.save({"poll_interval_seconds": 120})
        result = store.merge_into_settings(Settings())
        assert result.poll_interval_seconds == 120

    def test_merges_app_config(self, store: ConfigStore) -> None:
        store.save({
            **_FULL_CONFIG,
            "app_config": {"sonarr": {"port": 9999, "api_key": "abc123"}},
        })
        result = store.merge_into_settings(Settings())
        assert "sonarr" in result.app_config
        assert isinstance(result.app_config["sonarr"], AppConfig)
        assert result.app_config["sonarr"].port == 9999
        assert result.app_config["sonarr"].api_key == "abc123"

    def test_merges_guest_config(self, store: ConfigStore) -> None:
        store.save({
            **_FULL_CONFIG,
            "guest_config": {"pve1:100": {"port": 8080, "scheme": "https"}},
        })
        result = store.merge_into_settings(Settings())
        assert "pve1:100" in result.guest_config
        assert isinstance(result.guest_config["pve1:100"], AppConfig)
        assert result.guest_config["pve1:100"].port == 8080
        assert result.guest_config["pve1:100"].scheme == "https"

    def test_merges_proxmox_hosts(self, store: ConfigStore) -> None:
        store.save({
            **_FULL_CONFIG,
            "proxmox_hosts": [{
                "id": "pve1", "label": "PVE1",
                "host": "https://10.0.0.1:8006",
                "token_id": "root@pam!test", "token_secret": "secret",
                "node": "pve",
            }],
        })
        result = store.merge_into_settings(Settings())
        assert len(result.proxmox_hosts) == 1
        assert isinstance(result.proxmox_hosts[0], ProxmoxHostConfig)
        assert result.proxmox_hosts[0].id == "pve1"

    def test_skips_invalid_app_config_entries(self, store: ConfigStore) -> None:
        store.save({
            **_FULL_CONFIG,
            "app_config": {
                "sonarr": {"port": 8989},
                "bad_entry": "not-a-dict",
            },
        })
        result = store.merge_into_settings(Settings())
        assert "sonarr" in result.app_config
        assert result.app_config["sonarr"].port == 8989
        assert "bad_entry" not in result.app_config

    def test_skips_invalid_proxmox_host_entries(self, store: ConfigStore) -> None:
        store.save({
            **_FULL_CONFIG,
            "proxmox_hosts": [
                {"id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
                 "token_id": "root@pam!test", "token_secret": "secret", "node": "pve"},
                "not-a-dict",
            ],
        })
        result = store.merge_into_settings(Settings())
        assert len(result.proxmox_hosts) == 1
        assert result.proxmox_hosts[0].id == "pve1"

    def test_empty_db_returns_original_settings(self, store: ConfigStore) -> None:
        original = Settings()
        result = store.merge_into_settings(original)
        assert result.poll_interval_seconds == original.poll_interval_seconds

    def test_merges_custom_app_defs(self, store: ConfigStore) -> None:
        store.save({
            **_FULL_CONFIG,
            "custom_app_defs": [
                {"name": "mealie", "display_name": "Mealie", "default_port": 9925},
            ],
        })
        result = store.merge_into_settings(Settings())
        assert len(result.custom_app_defs) == 1
        assert isinstance(result.custom_app_defs[0], CustomAppDef)
        assert result.custom_app_defs[0].name == "mealie"
        assert result.custom_app_defs[0].default_port == 9925

    def test_skips_invalid_custom_app_defs(self, store: ConfigStore) -> None:
        store.save({
            **_FULL_CONFIG,
            "custom_app_defs": [
                {"name": "good-app", "display_name": "Good", "default_port": 8080},
                "not-a-dict",
                {"name": "BAD_NAME", "display_name": "Bad", "default_port": 80},
            ],
        })
        result = store.merge_into_settings(Settings())
        assert len(result.custom_app_defs) == 1
        assert result.custom_app_defs[0].name == "good-app"



class TestGetMissingFieldsMultiHost:
    def test_configured_when_host_has_all_fields(self, store: ConfigStore) -> None:
        store.save({
            "proxmox_hosts": [{
                "id": "pve1", "label": "PVE1",
                "host": "https://10.0.0.1:8006",
                "token_id": "root@pam!test",
                "token_secret": "secret",
                "node": "pve",
            }],
        })
        assert store.get_missing_fields() == []

    def test_missing_when_host_lacks_fields(self, store: ConfigStore) -> None:
        store.save({
            "proxmox_hosts": [{
                "id": "pve1", "label": "PVE1",
                "host": "https://10.0.0.1:8006",
                "token_id": "", "token_secret": "", "node": "",
            }],
        })
        missing = store.get_missing_fields()
        assert "token_id" in missing
        assert "token_secret" in missing
        assert "node" in missing

    def test_configured_if_any_host_is_complete(self, store: ConfigStore) -> None:
        store.save({
            "proxmox_hosts": [
                {"id": "bad", "label": "Bad", "host": "", "token_id": "", "token_secret": "", "node": ""},
                {"id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
                 "token_id": "root@pam!test", "token_secret": "secret", "node": "pve"},
            ],
        })
        assert store.get_missing_fields() == []


class TestColumnMigration:
    """Verify that _init_db adds missing columns to an existing settings table."""

    def test_adds_missing_columns(self, db_path: Path) -> None:
        """A table created with only a few columns should gain the rest on init."""
        import sqlite3

        # Create a minimal table missing several columns.
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE settings ("
            "  id INTEGER PRIMARY KEY CHECK (id = 1),"
            "  poll_interval_seconds INTEGER DEFAULT 3600,"
            "  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
            ")"
        )
        conn.commit()
        conn.close()

        # ConfigStore.__init__ should migrate the missing columns.
        store = ConfigStore(str(db_path))

        conn = sqlite3.connect(str(db_path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
        conn.close()

        # Spot-check several columns that were missing.
        for expected in ("proxmon_api_key", "trust_proxy_headers", "discover_vms",
                         "github_token", "proxmox_hosts", "custom_app_defs"):
            assert expected in cols, f"Column '{expected}' was not added by migration"

    def test_save_load_after_migration(self, db_path: Path) -> None:
        """After migration, save and load should work normally."""
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE settings ("
            "  id INTEGER PRIMARY KEY CHECK (id = 1),"
            "  poll_interval_seconds INTEGER DEFAULT 3600,"
            "  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
            ")"
        )
        conn.commit()
        conn.close()

        store = ConfigStore(str(db_path))
        store.save({"poll_interval_seconds": 120, "discover_vms": True, "proxmon_api_key": "abc"})
        data = store.load()
        assert data["poll_interval_seconds"] == 120
        assert data["discover_vms"] is True
        assert data["proxmon_api_key"] == "abc"

    def test_no_op_on_fresh_db(self, db_path: Path) -> None:
        """On a fresh database, migration should be a no-op (no errors)."""
        store = ConfigStore(str(db_path))
        store.save({"log_level": "debug"})
        assert store.load()["log_level"] == "debug"


class TestMigratableColumnsDrift:
    """Guard against _MIGRATABLE_COLUMNS drifting from _CREATE_TABLE."""

    def test_covers_all_ddl_columns(self, db_path: Path) -> None:
        """Every column in a fresh table (except id, updated_at) must appear in _MIGRATABLE_COLUMNS."""
        import sqlite3
        # Use SQLite itself as the authoritative DDL parser.
        conn = sqlite3.connect(str(db_path))
        conn.execute(_CREATE_TABLE)
        conn.commit()
        actual_cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
        conn.close()
        actual_cols -= {"id", "updated_at"}
        migratable_names = {col for col, _ in _MIGRATABLE_COLUMNS}
        assert actual_cols == migratable_names, (
            f"Drift: in DDL only={actual_cols - migratable_names}, "
            f"in migration only={migratable_names - actual_cols}"
        )


class TestLoadAuth:
    def test_load_auth_fast_path(self, store: ConfigStore) -> None:
        store.save({
            "auth_mode": "forms",
            "auth_password_hash": "$bcrypt$somehash",
        })
        auth = store.load_auth()
        assert auth == {
            "auth_mode": "forms",
            "auth_password_hash": "$bcrypt$somehash",
        }
