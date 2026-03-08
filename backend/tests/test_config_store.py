"""Tests for ConfigStore: load, save, is_configured, missing_fields, priority."""

import json
import os
import stat
from pathlib import Path

import pytest

from app.core.config_store import ConfigStore


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


@pytest.fixture()
def store(config_path: Path) -> ConfigStore:
    return ConfigStore(str(config_path))


class TestLoad:
    def test_returns_empty_dict_when_file_missing(self, store: ConfigStore) -> None:
        assert store.load() == {}

    def test_returns_parsed_json(self, store: ConfigStore, config_path: Path) -> None:
        config_path.write_text(json.dumps({"proxmox_host": "https://10.0.0.1:8006"}))
        result = store.load()
        assert result == {"proxmox_host": "https://10.0.0.1:8006"}

    def test_returns_empty_dict_on_invalid_json(self, store: ConfigStore, config_path: Path) -> None:
        config_path.write_text("not valid json {{{")
        assert store.load() == {}

    def test_returns_empty_dict_when_json_is_array(self, store: ConfigStore, config_path: Path) -> None:
        config_path.write_text(json.dumps([1, 2, 3]))
        assert store.load() == {}


class TestSave:
    def test_creates_file(self, store: ConfigStore, config_path: Path) -> None:
        store.save({"proxmox_host": "https://10.0.0.1:8006"})
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["proxmox_host"] == "https://10.0.0.1:8006"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "config.json"
        s = ConfigStore(str(nested))
        s.save({"key": "val"})
        assert nested.exists()

    def test_sets_permissions_0600(self, store: ConfigStore, config_path: Path) -> None:
        store.save({"key": "val"})
        mode = stat.S_IMODE(config_path.stat().st_mode)
        assert mode == 0o600

    def test_atomic_write_no_tmp_left(self, store: ConfigStore, config_path: Path) -> None:
        store.save({"key": "val"})
        tmp = config_path.with_suffix(".tmp")
        assert not tmp.exists()

    def test_overwrites_existing(self, store: ConfigStore, config_path: Path) -> None:
        store.save({"a": 1})
        store.save({"b": 2})
        data = json.loads(config_path.read_text())
        assert "a" not in data
        assert data["b"] == 2

    def test_roundtrip(self, store: ConfigStore) -> None:
        original = {
            "proxmox_host": "https://10.0.0.1:8006",
            "proxmox_token_id": "root@pam!test",
            "proxmox_token_secret": "secret-uuid",
            "proxmox_node": "pve",
            "poll_interval_seconds": 120,
            "discover_vms": True,
        }
        store.save(original)
        loaded = store.load()
        assert loaded == original


class TestIsConfigured:
    def test_false_when_no_file_and_no_env(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear any env vars
        for field in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                      "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(field, raising=False)
        assert store.is_configured() is False

    def test_true_when_file_has_all_fields(self, store: ConfigStore, config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for field in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                      "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(field, raising=False)
        config_path.write_text(json.dumps({
            "proxmox_host": "https://10.0.0.1:8006",
            "proxmox_token_id": "root@pam!test",
            "proxmox_token_secret": "secret",
            "proxmox_node": "pve",
        }))
        assert store.is_configured() is True

    def test_false_when_field_is_empty_string(self, store: ConfigStore, config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for field in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                      "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(field, raising=False)
        config_path.write_text(json.dumps({
            "proxmox_host": "https://10.0.0.1:8006",
            "proxmox_token_id": "",
            "proxmox_token_secret": "secret",
            "proxmox_node": "pve",
        }))
        assert store.is_configured() is False


class TestGetMissingFields:
    def test_all_missing_when_empty(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        for field in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                      "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(field, raising=False)
        missing = store.get_missing_fields()
        assert set(missing) == {"proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"}

    def test_partial_missing(self, store: ConfigStore, config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for field in ("PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET", "PROXMOX_NODE",
                      "proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"):
            monkeypatch.delenv(field, raising=False)
        config_path.write_text(json.dumps({
            "proxmox_host": "https://10.0.0.1:8006",
            "proxmox_node": "pve",
        }))
        missing = store.get_missing_fields()
        assert set(missing) == {"proxmox_token_id", "proxmox_token_secret"}


class TestPriorityOrder:
    def test_file_overrides_env(self, store: ConfigStore, config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config file values take priority over environment variables."""
        monkeypatch.setenv("PROXMOX_HOST", "https://env-host:8006")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "env@pam!token")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "env-secret")
        monkeypatch.setenv("PROXMOX_NODE", "env-node")

        config_path.write_text(json.dumps({
            "proxmox_host": "https://file-host:8006",
            "proxmox_token_id": "file@pam!token",
            "proxmox_token_secret": "file-secret",
            "proxmox_node": "file-node",
        }))

        # is_configured should use file values (both present, so True)
        assert store.is_configured() is True
        # The file values are what's in the loaded data
        data = store.load()
        assert data["proxmox_host"] == "https://file-host:8006"

    def test_env_used_when_no_file(self, store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables are used when no config file exists."""
        monkeypatch.setenv("PROXMOX_HOST", "https://env-host:8006")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "env@pam!token")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "env-secret")
        monkeypatch.setenv("PROXMOX_NODE", "env-node")

        assert store.is_configured() is True
