"""Tests for ConfigStore: SQLite-backed config persistence."""

import sqlite3
from pathlib import Path

import pytest

from app.config import AppConfig, CustomAppDef, ProxmoxHostConfig, Settings
from app.core.config_store import ConfigStore, _ALL_MIGRATABLE, _CREATE_TABLE


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
        store.save_full(original)
        assert store.load() == original

    def test_load_empty_db_returns_empty_dict(self, store: ConfigStore) -> None:
        assert store.load() == {}


class TestIsConfigured:
    def test_false_when_empty(self, store: ConfigStore) -> None:
        assert store.is_configured() is False

    def test_true_when_host_fully_configured(self, store: ConfigStore) -> None:
        store.save_full({}, hosts=[{
            "id": "pve1", "label": "PVE1",
            "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!test",
            "token_secret": "secret-uuid",
            "node": "pve",
        }])
        assert store.is_configured() is True


class TestGetMissingFields:
    def test_returns_all_when_empty(self, store: ConfigStore) -> None:
        assert set(store.get_missing_fields()) == {
            "host", "token_id", "token_secret", "node",
        }


class TestSaveIdempotent:
    def test_second_save_overwrites_first(self, store: ConfigStore) -> None:
        """save_full uses full-replace semantics — omitted scalars revert to NULL."""
        store.save_full({"log_level": "debug"})
        store.save_full({"poll_interval_seconds": 60})
        data = store.load()
        assert "log_level" not in data
        assert data["poll_interval_seconds"] == 60


class TestMergeIntoSettings:
    def test_merges_basic_fields(self, store: ConfigStore) -> None:
        store.save_full({"poll_interval_seconds": 120})
        result = store.merge_into_settings(Settings())
        assert result.poll_interval_seconds == 120

    def test_merges_app_config(self, store: ConfigStore) -> None:
        store.save_full(
            {},
            hosts=_FULL_CONFIG["proxmox_hosts"],
            app_configs={"sonarr": {"port": 9999, "api_key": "abc123"}},
        )
        result = store.merge_into_settings(Settings())
        assert "sonarr" in result.app_config
        assert isinstance(result.app_config["sonarr"], AppConfig)
        assert result.app_config["sonarr"].port == 9999
        assert result.app_config["sonarr"].api_key == "abc123"

    def test_merges_guest_config(self, store: ConfigStore) -> None:
        store.save_full({}, hosts=_FULL_CONFIG["proxmox_hosts"])
        store.upsert_guest_config("pve1:100", {"port": 8080, "scheme": "https"})
        result = store.merge_into_settings(Settings())
        assert "pve1:100" in result.guest_config
        assert isinstance(result.guest_config["pve1:100"], AppConfig)
        assert result.guest_config["pve1:100"].port == 8080
        assert result.guest_config["pve1:100"].scheme == "https"

    def test_merges_proxmox_hosts(self, store: ConfigStore) -> None:
        store.save_full({}, hosts=[{
            "id": "pve1", "label": "PVE1",
            "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!test", "token_secret": "secret",
            "node": "pve",
        }])
        result = store.merge_into_settings(Settings())
        assert len(result.proxmox_hosts) == 1
        assert isinstance(result.proxmox_hosts[0], ProxmoxHostConfig)
        assert result.proxmox_hosts[0].id == "pve1"

    def test_skips_invalid_app_config_entries(self, store: ConfigStore, db_path: Path) -> None:
        store.save_full(
            {},
            hosts=_FULL_CONFIG["proxmox_hosts"],
            app_configs={"sonarr": {"port": 8989}},
        )
        # Inject a corrupt row: non-numeric string in the INTEGER port column.
        # SQLite allows this (type affinity); merge_into_settings must skip it.
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO app_config (app_name, port) VALUES (?, ?)",
            ("bad_entry", "not-a-number"),
        )
        conn.commit()
        conn.close()
        result = store.merge_into_settings(Settings())
        assert "sonarr" in result.app_config
        assert result.app_config["sonarr"].port == 8989
        # Corrupt row must have been skipped
        assert "bad_entry" not in result.app_config

    def test_skips_invalid_proxmox_host_entries(self, store: ConfigStore, monkeypatch) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!test", "token_secret": "secret", "node": "pve",
        })
        valid_host = store.list_hosts()[0]
        # ProxmoxHostConfig is very permissive (no field validators), so SQL
        # corruption alone cannot trigger a validation error.  Simulate a
        # corrupt row returned by the load layer (e.g. schema mismatch after a
        # failed migration) by injecting a dict missing the required 'id' key.
        corrupt_host = {"label": "bad", "host": "x"}

        def _patched_list_hosts(conn):
            return [valid_host, corrupt_host]

        monkeypatch.setattr(ConfigStore, "_list_hosts_conn", staticmethod(_patched_list_hosts))
        result = store.merge_into_settings(Settings())
        assert len(result.proxmox_hosts) == 1
        assert result.proxmox_hosts[0].id == "pve1"

    def test_empty_db_returns_original_settings(self, store: ConfigStore) -> None:
        original = Settings()
        result = store.merge_into_settings(original)
        assert result.poll_interval_seconds == original.poll_interval_seconds

    def test_merges_custom_app_defs(self, store: ConfigStore) -> None:
        store.save_full({}, hosts=_FULL_CONFIG["proxmox_hosts"])
        store.upsert_custom_app_def(
            {"name": "mealie", "display_name": "Mealie", "default_port": 9925},
        )
        result = store.merge_into_settings(Settings())
        assert len(result.custom_app_defs) == 1
        assert isinstance(result.custom_app_defs[0], CustomAppDef)
        assert result.custom_app_defs[0].name == "mealie"
        assert result.custom_app_defs[0].default_port == 9925

    def test_skips_invalid_custom_app_defs(self, store: ConfigStore, db_path: Path) -> None:
        store.save_full({}, hosts=_FULL_CONFIG["proxmox_hosts"])
        store.upsert_custom_app_def(
            {"name": "good-app", "display_name": "Good", "default_port": 8080},
        )
        # Inject a corrupt row via raw SQL — uppercase name fails CustomAppDef
        # validator (must match ^[a-z][a-z0-9-]{1,31}$).
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO custom_app_defs"
            " (name, display_name, default_port, scheme, aliases,"
            "  docker_images, accepts_api_key, version_keys, strip_v)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("BAD_NAME", "Bad", 80, "http", "[]", "[]", 0, '["version"]', 0),
        )
        conn.commit()
        conn.close()
        result = store.merge_into_settings(Settings())
        # Only the valid entry survives; corrupt row is skipped
        assert len(result.custom_app_defs) == 1
        assert result.custom_app_defs[0].name == "good-app"



class TestGetMissingFieldsMultiHost:
    def test_configured_when_host_has_all_fields(self, store: ConfigStore) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1",
            "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!test",
            "token_secret": "secret",
            "node": "pve",
        })
        assert store.get_missing_fields() == []

    def test_missing_when_host_lacks_fields(self, store: ConfigStore) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1",
            "host": "https://10.0.0.1:8006",
            "token_id": "", "token_secret": "", "node": "",
        })
        missing = store.get_missing_fields()
        assert "token_id" in missing
        assert "token_secret" in missing
        assert "node" in missing

    def test_configured_if_any_host_is_complete(self, store: ConfigStore) -> None:
        store.upsert_host({"id": "bad", "label": "Bad", "host": "", "token_id": "", "token_secret": "", "node": ""})
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!test", "token_secret": "secret", "node": "pve",
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
                         "github_token"):
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
        store.save_full({"poll_interval_seconds": 120, "discover_vms": True, "proxmon_api_key": "abc"})
        data = store.load()
        assert data["poll_interval_seconds"] == 120
        assert data["discover_vms"] is True
        assert data["proxmon_api_key"] == "abc"

    def test_no_op_on_fresh_db(self, db_path: Path) -> None:
        """On a fresh database, migration should be a no-op (no errors)."""
        store = ConfigStore(str(db_path))
        store.save_full({"log_level": "debug"})
        assert store.load()["log_level"] == "debug"


class TestMigratableColumnsDrift:
    """Guard against _ALL_MIGRATABLE['settings'] drifting from _CREATE_TABLE."""

    def test_covers_all_ddl_columns(self, db_path: Path) -> None:
        """Every column in a fresh table (except id, updated_at) must appear in _ALL_MIGRATABLE['settings']."""
        import sqlite3
        # Use SQLite itself as the authoritative DDL parser.
        conn = sqlite3.connect(str(db_path))
        conn.execute(_CREATE_TABLE)
        conn.commit()
        actual_cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
        conn.close()
        actual_cols -= {"id", "updated_at"}
        migratable_names = {col for col, _ in _ALL_MIGRATABLE["settings"]}
        assert actual_cols == migratable_names, (
            f"Drift: in DDL only={actual_cols - migratable_names}, "
            f"in migration only={migratable_names - actual_cols}"
        )


class TestLoadAuth:
    def test_load_auth_fast_path(self, store: ConfigStore) -> None:
        store.save_full({
            "auth_mode": "forms",
            "auth_password_hash": "$bcrypt$somehash",
        })
        auth = store.load_auth()
        assert auth == {
            "auth_mode": "forms",
            "auth_password_hash": "$bcrypt$somehash",
            "auth_username": "root",
        }


# ======================================================================
# New tests for normalized CRUD methods
# ======================================================================


class TestHostsCRUD:
    def test_upsert_and_list(self, store: ConfigStore) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!t1", "token_secret": "sec1", "node": "pve1",
        })
        store.upsert_host({
            "id": "pve2", "label": "PVE2", "host": "https://10.0.0.2:8006",
            "token_id": "root@pam!t2", "token_secret": "sec2", "node": "pve2",
            "pct_exec_enabled": True,
        })
        hosts = store.list_hosts()
        assert len(hosts) == 2
        ids = {h["id"] for h in hosts}
        assert ids == {"pve1", "pve2"}
        pve2 = [h for h in hosts if h["id"] == "pve2"][0]
        assert pve2["pct_exec_enabled"] is True

    def test_get(self, store: ConfigStore) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!t1", "token_secret": "sec1", "node": "pve1",
            "ssh_username": "admin", "backup_storage": "local-zfs",
        })
        h = store.get_host("pve1")
        assert h is not None
        assert h["label"] == "PVE1"
        assert h["ssh_username"] == "admin"
        assert h["backup_storage"] == "local-zfs"
        assert h["pct_exec_enabled"] is False

    def test_delete(self, store: ConfigStore) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "t", "token_secret": "s", "node": "n",
        })
        store.delete_host("pve1")
        assert store.get_host("pve1") is None
        assert store.list_hosts() == []

    def test_upsert_preserves_secrets(self, store: ConfigStore) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!t1", "token_secret": "real-secret",
            "node": "pve1", "ssh_password": "real-ssh-pass",
        })
        # Update with masked secrets
        store.upsert_host({
            "id": "pve1", "label": "PVE1-Updated", "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!t1", "token_secret": "***",
            "node": "pve1", "ssh_password": "***",
        })
        h = store.get_host("pve1")
        assert h["label"] == "PVE1-Updated"
        assert h["token_secret"] == "real-secret"
        assert h["ssh_password"] == "real-ssh-pass"

    def test_upsert_preserves_secrets_on_none(self, store: ConfigStore) -> None:
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "t", "token_secret": "real-secret", "node": "n",
        })
        store.upsert_host({
            "id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
            "token_id": "t", "node": "n",
            # token_secret omitted (None)
        })
        h = store.get_host("pve1")
        assert h["token_secret"] == "real-secret"


class TestAppConfigCRUD:
    def test_upsert_and_list(self, store: ConfigStore) -> None:
        store.upsert_app_config("sonarr", {"port": 8989, "api_key": "abc"})
        store.upsert_app_config("radarr", {"port": 7878})
        configs = store.list_app_configs()
        assert "sonarr" in configs
        assert configs["sonarr"]["port"] == 8989
        assert configs["sonarr"]["api_key"] == "abc"
        assert "radarr" in configs
        assert configs["radarr"]["port"] == 7878

    def test_delete(self, store: ConfigStore) -> None:
        store.upsert_app_config("sonarr", {"port": 8989})
        store.delete_app_config("sonarr")
        assert store.get_app_config("sonarr") is None
        assert store.list_app_configs() == {}

    def test_upsert_preserves_secrets(self, store: ConfigStore) -> None:
        store.upsert_app_config("sonarr", {"port": 8989, "api_key": "real-key", "ssh_password": "real-pw"})
        store.upsert_app_config("sonarr", {"port": 9999, "api_key": "***", "ssh_password": "***"})
        cfg = store.get_app_config("sonarr")
        assert cfg["port"] == 9999
        assert cfg["api_key"] == "real-key"
        assert cfg["ssh_password"] == "real-pw"

    def test_empty_string_secret_clears_to_null(self, store: ConfigStore) -> None:
        store.upsert_app_config("sonarr", {"api_key": "real-key", "ssh_password": "real-pw"})
        store.upsert_app_config("sonarr", {"api_key": "", "ssh_password": ""})
        cfg = store.get_app_config("sonarr")
        # "" is normalized to NULL; _row_to_app_config strips None keys
        assert cfg is None or cfg.get("api_key") is None
        assert cfg is None or cfg.get("ssh_password") is None

    def test_port_zero_stored_as_zero(self, store: ConfigStore) -> None:
        """ConfigStore stores port 0 as-is; the route layer maps 0→None."""
        store.upsert_app_config("sonarr", {"port": 8989})
        store.upsert_app_config("sonarr", {"port": 0})
        cfg = store.get_app_config("sonarr")
        assert cfg is not None and cfg.get("port") == 0


class TestGuestConfigCRUD:
    def test_upsert_and_list(self, store: ConfigStore) -> None:
        store.upsert_guest_config("pve1:100", {"port": 8080, "scheme": "https"})
        store.upsert_guest_config("pve1:101", {"forced_detector": "sonarr"})
        configs = store.list_guest_configs()
        assert "pve1:100" in configs
        assert configs["pve1:100"]["port"] == 8080
        assert configs["pve1:100"]["scheme"] == "https"
        assert "pve1:101" in configs
        assert configs["pve1:101"]["forced_detector"] == "sonarr"

    def test_delete(self, store: ConfigStore) -> None:
        store.upsert_guest_config("pve1:100", {"port": 8080})
        store.delete_guest_config("pve1:100")
        assert store.get_guest_config("pve1:100") is None
        assert store.list_guest_configs() == {}

    def test_upsert_preserves_secrets(self, store: ConfigStore) -> None:
        store.upsert_guest_config("pve1:100", {"api_key": "real-key", "ssh_password": "real-pw"})
        store.upsert_guest_config("pve1:100", {"api_key": "***", "ssh_password": None})
        cfg = store.get_guest_config("pve1:100")
        assert cfg["api_key"] == "real-key"
        assert cfg["ssh_password"] == "real-pw"

    def test_empty_string_secret_clears_to_null(self, store: ConfigStore) -> None:
        store.upsert_guest_config("pve1:100", {"api_key": "real-key", "ssh_password": "real-pw"})
        store.upsert_guest_config("pve1:100", {"api_key": "", "ssh_password": ""})
        cfg = store.get_guest_config("pve1:100")
        assert cfg is None or cfg.get("api_key") is None
        assert cfg is None or cfg.get("ssh_password") is None

    def test_port_zero_stored_as_zero(self, store: ConfigStore) -> None:
        """ConfigStore stores port 0 as-is; the route layer maps 0→None."""
        store.upsert_guest_config("pve1:100", {"port": 8080})
        store.upsert_guest_config("pve1:100", {"port": 0})
        cfg = store.get_guest_config("pve1:100")
        assert cfg is not None and cfg.get("port") == 0


class TestCustomAppDefsCRUD:
    def test_upsert_and_list(self, store: ConfigStore) -> None:
        store.upsert_custom_app_def({
            "name": "mealie", "display_name": "Mealie", "default_port": 9925,
        })
        store.upsert_custom_app_def({
            "name": "ha", "display_name": "Home Assistant", "default_port": 8123,
            "scheme": "https",
        })
        defs = store.list_custom_app_defs()
        assert len(defs) == 2
        names = {d["name"] for d in defs}
        assert names == {"mealie", "ha"}

    def test_delete(self, store: ConfigStore) -> None:
        store.upsert_custom_app_def({
            "name": "mealie", "display_name": "Mealie", "default_port": 9925,
        })
        store.delete_custom_app_def("mealie")
        assert store.get_custom_app_def("mealie") is None
        assert store.list_custom_app_defs() == []

    def test_json_list_fields_round_trip(self, store: ConfigStore) -> None:
        store.upsert_custom_app_def({
            "name": "myapp", "display_name": "My App", "default_port": 5000,
            "aliases": ["myapp-alt", "ma"],
            "docker_images": ["ghcr.io/org/myapp"],
            "version_keys": ["info", "version"],
            "accepts_api_key": True,
            "strip_v": True,
        })
        d = store.get_custom_app_def("myapp")
        assert d is not None
        assert d["aliases"] == ["myapp-alt", "ma"]
        assert d["docker_images"] == ["ghcr.io/org/myapp"]
        assert d["version_keys"] == ["info", "version"]
        assert d["accepts_api_key"] is True
        assert d["strip_v"] is True


class TestLoadFromTables:
    def test_load_assembles_from_tables(self, store: ConfigStore) -> None:
        """Use CRUD to insert data, call load(), verify dict shape."""
        # Insert scalar settings
        store.save_full({"poll_interval_seconds": 300, "ssh_enabled": True})

        # Insert hosts via CRUD
        store.upsert_host({
            "id": "default", "label": "Minisforum",
            "host": "https://192.168.1.10:8006",
            "token_id": "root@pam!proxmon", "token_secret": "uuid-secret",
            "node": "pve",
        })

        # Insert app config via CRUD
        store.upsert_app_config("sonarr", {"port": 8989, "api_key": "sonarr-key"})

        # Insert guest config via CRUD
        store.upsert_guest_config("default:103", {"port": 8090, "forced_detector": "plex"})

        # Insert custom app def via CRUD
        store.upsert_custom_app_def({
            "name": "homeassistant", "display_name": "Home Assistant",
            "default_port": 8123, "scheme": "https",
            "aliases": ["ha", "hass"],
        })

        data = store.load()

        # Scalar fields
        assert data["poll_interval_seconds"] == 300
        assert data["ssh_enabled"] is True

        # proxmox_hosts
        assert len(data["proxmox_hosts"]) == 1
        assert data["proxmox_hosts"][0]["id"] == "default"
        assert data["proxmox_hosts"][0]["label"] == "Minisforum"
        assert data["proxmox_hosts"][0]["token_secret"] == "uuid-secret"

        # app_config
        assert "sonarr" in data["app_config"]
        assert data["app_config"]["sonarr"]["port"] == 8989
        assert data["app_config"]["sonarr"]["api_key"] == "sonarr-key"

        # guest_config
        assert "default:103" in data["guest_config"]
        assert data["guest_config"]["default:103"]["port"] == 8090
        assert data["guest_config"]["default:103"]["forced_detector"] == "plex"

        # custom_app_defs
        assert len(data["custom_app_defs"]) == 1
        assert data["custom_app_defs"][0]["name"] == "homeassistant"
        assert data["custom_app_defs"][0]["aliases"] == ["ha", "hass"]
        assert data["custom_app_defs"][0]["scheme"] == "https"
