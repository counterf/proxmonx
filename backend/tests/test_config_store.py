"""Tests for ConfigStore: SQLite-backed config persistence."""

import json
import os
from pathlib import Path

import pytest

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
        assert store.load() == _FULL_CONFIG

    def test_migration_skipped_if_settings_row_exists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "proxmon.db"
        store = ConfigStore(str(db_path))
        store.save({"existing": "data"})

        # Now write a config.json — it should NOT be migrated
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(_FULL_CONFIG))

        store2 = ConfigStore(str(db_path))
        assert store2.load() == {"existing": "data"}
