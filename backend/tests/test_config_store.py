"""Tests for ConfigStore: SQLite-backed config persistence."""

import json
import os
from pathlib import Path

import pytest

from app.config import AppConfig, ProxmoxHostConfig, Settings
from app.core.config_store import ConfigStore


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "proxmon.db"


@pytest.fixture()
def store(db_path: Path) -> ConfigStore:
    return ConfigStore(str(db_path))


_FULL_CONFIG = {
    "proxmox_host": "https://10.0.0.1:8006",
    "proxmox_token_id": "root@pam!test",
    "proxmox_token_secret": "secret-uuid",
    "proxmox_node": "pve",
}


class TestSaveLoadRoundTrip:
    def test_roundtrip(self, store: ConfigStore) -> None:
        original = {**_FULL_CONFIG, "poll_interval_seconds": 120, "discover_vms": True}
        store.save(original)
        assert store.load() == original

    def test_load_empty_db_returns_empty_dict(self, store: ConfigStore) -> None:
        assert store.load() == {}


class TestIsConfigured:
    def test_false_when_empty(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
        assert store.is_configured() is False

    def test_true_when_required_fields_present(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
        store.save(_FULL_CONFIG)
        assert store.is_configured() is True


class TestGetMissingFields:
    def test_returns_all_when_empty(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
        assert set(store.get_missing_fields()) == {
            "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node",
        }


class TestSaveIdempotent:
    def test_second_save_overwrites_first(self, store: ConfigStore) -> None:
        store.save({"a": 1})
        store.save({"b": 2})
        data = store.load()
        assert "a" not in data
        assert data["b"] == 2


class TestMigration:
    def test_migrates_config_json_if_db_empty(self, tmp_path: Path) -> None:
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(_FULL_CONFIG))

        db_path = tmp_path / "proxmon.db"
        store = ConfigStore(str(db_path))
        loaded = store.load()
        # config.json flat fields are preserved; multi-host migration also runs
        for key, value in _FULL_CONFIG.items():
            assert loaded[key] == value
        # multi-host migration wraps the single host into proxmox_hosts
        assert "proxmox_hosts" in loaded
        assert loaded["proxmox_hosts"][0]["host"] == _FULL_CONFIG["proxmox_host"]
        assert loaded["proxmox_hosts"][0]["id"] == "default"

    def test_migration_skipped_if_settings_row_exists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "proxmon.db"
        store = ConfigStore(str(db_path))
        store.save({"existing": "data"})

        # Now write a config.json — it should NOT be migrated
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(_FULL_CONFIG))

        store2 = ConfigStore(str(db_path))
        assert store2.load() == {"existing": "data"}


class TestMergeIntoSettings:
    def test_merges_basic_fields(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
        store.save({**_FULL_CONFIG, "poll_interval_seconds": 120})
        result = store.merge_into_settings(Settings())
        assert result.proxmox_host == "https://10.0.0.1:8006"
        assert result.poll_interval_seconds == 120

    def test_merges_app_config(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
        store.save({
            **_FULL_CONFIG,
            "app_config": {"sonarr": {"port": 9999, "api_key": "abc123"}},
        })
        result = store.merge_into_settings(Settings())
        assert "sonarr" in result.app_config
        assert isinstance(result.app_config["sonarr"], AppConfig)
        assert result.app_config["sonarr"].port == 9999
        assert result.app_config["sonarr"].api_key == "abc123"

    def test_merges_guest_config(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
        store.save({
            **_FULL_CONFIG,
            "guest_config": {"pve1:100": {"port": 8080, "scheme": "https"}},
        })
        result = store.merge_into_settings(Settings())
        assert "pve1:100" in result.guest_config
        assert isinstance(result.guest_config["pve1:100"], AppConfig)
        assert result.guest_config["pve1:100"].port == 8080
        assert result.guest_config["pve1:100"].scheme == "https"

    def test_merges_proxmox_hosts(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
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

    def test_skips_invalid_app_config_entries(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
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
        # Non-dict entry is dropped, does not crash
        assert "bad_entry" not in result.app_config

    def test_skips_invalid_proxmox_host_entries(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for f in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                   "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(f, raising=False)
        store.save({
            **_FULL_CONFIG,
            "proxmox_hosts": [
                {"id": "pve1", "label": "PVE1", "host": "https://10.0.0.1:8006",
                 "token_id": "root@pam!test", "token_secret": "secret", "node": "pve"},
                "not-a-dict",
            ],
        })
        result = store.merge_into_settings(Settings())
        # Valid host is included, non-dict is dropped
        assert len(result.proxmox_hosts) == 1
        assert result.proxmox_hosts[0].id == "pve1"

    def test_empty_db_returns_original_settings(self, store: ConfigStore) -> None:
        original = Settings()
        result = store.merge_into_settings(original)
        assert result.poll_interval_seconds == original.poll_interval_seconds


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
