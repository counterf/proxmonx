"""Tests for Custom App Definitions feature."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.config import CustomAppDef, Settings


class TestCustomAppDefModel:
    """Validation tests for the CustomAppDef Pydantic model."""

    def test_valid_minimal(self) -> None:
        d = CustomAppDef(name="mealie", display_name="Mealie", default_port=9925)
        assert d.name == "mealie"
        assert d.scheme == "http"
        assert d.version_keys == ["version"]

    def test_valid_full(self) -> None:
        d = CustomAppDef(
            name="my-app",
            display_name="My App",
            default_port=8080,
            scheme="https",
            version_path="/api/version",
            github_repo="owner/repo",
            aliases=["myapp"],
            docker_images=["ghcr.io/owner/myapp"],
            accepts_api_key=True,
            auth_header="X-Api-Key",
            version_keys=["info.version"],
            strip_v=True,
        )
        assert d.version_path == "/api/version"

    def test_name_must_start_with_letter(self) -> None:
        with pytest.raises(ValidationError, match="name must be"):
            CustomAppDef(name="1bad", display_name="Bad", default_port=80)

    def test_name_no_uppercase(self) -> None:
        with pytest.raises(ValidationError, match="name must be"):
            CustomAppDef(name="BadName", display_name="Bad", default_port=80)

    def test_name_no_spaces(self) -> None:
        with pytest.raises(ValidationError, match="name must be"):
            CustomAppDef(name="bad name", display_name="Bad", default_port=80)

    def test_name_single_char_too_short(self) -> None:
        with pytest.raises(ValidationError, match="name must be"):
            CustomAppDef(name="a", display_name="A", default_port=80)

    def test_name_max_length(self) -> None:
        name = "a" * 32
        d = CustomAppDef(name=name, display_name="Long", default_port=80)
        assert d.name == name

    def test_name_over_max_length(self) -> None:
        with pytest.raises(ValidationError, match="name must be"):
            CustomAppDef(name="a" * 33, display_name="Long", default_port=80)

    def test_port_too_low(self) -> None:
        with pytest.raises(ValidationError, match="default_port must be"):
            CustomAppDef(name="ab", display_name="Ab", default_port=0)

    def test_port_too_high(self) -> None:
        with pytest.raises(ValidationError, match="default_port must be"):
            CustomAppDef(name="ab", display_name="Ab", default_port=70000)

    def test_port_boundary_valid(self) -> None:
        d1 = CustomAppDef(name="ab", display_name="Ab", default_port=1)
        d2 = CustomAppDef(name="cd", display_name="Cd", default_port=65535)
        assert d1.default_port == 1
        assert d2.default_port == 65535


class TestLoadCustomDetectors:
    """Tests for load_custom_detectors in registry.py."""

    def test_custom_detector_appears_in_globals(self) -> None:
        from app.detectors.registry import ALL_DETECTORS, DETECTOR_MAP, load_custom_detectors

        defn = CustomAppDef(name="testapp-one", display_name="TestApp1", default_port=9999)
        load_custom_detectors([defn])

        assert "testapp-one" in DETECTOR_MAP
        assert any(d.name == "testapp-one" for d in ALL_DETECTORS)

        # Cleanup
        load_custom_detectors([])
        assert "testapp-one" not in DETECTOR_MAP

    def test_reload_with_empty_removes_custom(self) -> None:
        from app.detectors.registry import ALL_DETECTORS, DETECTOR_MAP, load_custom_detectors

        defn = CustomAppDef(name="testapp-two", display_name="TestApp2", default_port=8888)
        load_custom_detectors([defn])
        assert "testapp-two" in DETECTOR_MAP

        load_custom_detectors([])
        assert "testapp-two" not in DETECTOR_MAP
        assert not any(d.name == "testapp-two" for d in ALL_DETECTORS)

    def test_idempotent(self) -> None:
        from app.detectors.registry import ALL_DETECTORS, DETECTOR_MAP, load_custom_detectors

        defn = CustomAppDef(name="testapp-idem", display_name="Idem", default_port=7777)
        load_custom_detectors([defn])
        count1 = sum(1 for d in ALL_DETECTORS if d.name == "testapp-idem")

        load_custom_detectors([defn])
        count2 = sum(1 for d in ALL_DETECTORS if d.name == "testapp-idem")

        assert count1 == 1
        assert count2 == 1

        # Cleanup
        load_custom_detectors([])

    def test_builtin_collision_skipped(self) -> None:
        from app.detectors.registry import DETECTOR_MAP, load_custom_detectors

        # "sonarr" is a built-in
        defn = CustomAppDef(name="sonarr", display_name="Fake Sonarr", default_port=1234)
        original_detector = DETECTOR_MAP.get("sonarr")
        load_custom_detectors([defn])

        # Built-in should be preserved
        assert DETECTOR_MAP.get("sonarr") is original_detector

        # Cleanup
        load_custom_detectors([])


class TestCustomAppRoutes:
    """Integration tests for custom app CRUD endpoints."""

    @pytest.fixture()
    def client(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from app.api.routes import _get_config_store, _get_settings, router
        from app.core.config_store import ConfigStore
        from app.detectors.registry import load_custom_detectors

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        store = ConfigStore(str(tmp_path / "test.db"))
        settings = Settings()
        app.state.config_store = store
        app.state.settings = settings

        app.dependency_overrides[_get_config_store] = lambda: store
        app.dependency_overrides[_get_settings] = lambda: settings

        # Ensure clean state
        load_custom_detectors([])

        yield TestClient(app)

        # Cleanup
        load_custom_detectors([])

    def test_create_returns_201(self, client) -> None:
        resp = client.post("/api/custom-apps", json={
            "name": "myapp",
            "display_name": "My App",
            "default_port": 8080,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "myapp"
        assert data["display_name"] == "My App"

    def test_duplicate_returns_409(self, client) -> None:
        payload = {
            "name": "dupapp",
            "display_name": "Dup App",
            "default_port": 8080,
        }
        resp1 = client.post("/api/custom-apps", json=payload)
        assert resp1.status_code == 201

        resp2 = client.post("/api/custom-apps", json=payload)
        assert resp2.status_code == 409

    def test_list(self, client) -> None:
        client.post("/api/custom-apps", json={
            "name": "listapp",
            "display_name": "List App",
            "default_port": 9090,
        })
        resp = client.get("/api/custom-apps")
        assert resp.status_code == 200
        apps = resp.json()
        assert any(a["name"] == "listapp" for a in apps)

    def test_update(self, client) -> None:
        client.post("/api/custom-apps", json={
            "name": "updapp",
            "display_name": "Upd App",
            "default_port": 3000,
        })
        resp = client.put("/api/custom-apps/updapp", json={
            "name": "updapp",
            "display_name": "Updated App",
            "default_port": 3001,
        })
        assert resp.status_code == 200
        assert resp.json()["default_port"] == 3001

    def test_update_not_found(self, client) -> None:
        resp = client.put("/api/custom-apps/nonexistent", json={
            "name": "nonexistent",
            "display_name": "No",
            "default_port": 80,
        })
        assert resp.status_code == 404

    def test_delete(self, client) -> None:
        client.post("/api/custom-apps", json={
            "name": "delapp",
            "display_name": "Del App",
            "default_port": 4000,
        })
        resp = client.delete("/api/custom-apps/delapp")
        assert resp.status_code == 200

        resp2 = client.get("/api/custom-apps")
        assert not any(a["name"] == "delapp" for a in resp2.json())

    def test_delete_not_found(self, client) -> None:
        resp = client.delete("/api/custom-apps/nonexistent")
        assert resp.status_code == 404

    def test_delete_clears_forced_detector(self, client, tmp_path: Path) -> None:
        from app.core.config_store import ConfigStore
        from app.api.routes import _get_config_store

        store = client.app.dependency_overrides[_get_config_store]()

        # Create custom app
        client.post("/api/custom-apps", json={
            "name": "clearapp",
            "display_name": "Clear App",
            "default_port": 5000,
        })

        # Manually set guest_config with forced_detector
        store.upsert_guest_config("pve1:100", {"forced_detector": "clearapp", "port": 5000})
        store.upsert_guest_config("pve1:101", {"forced_detector": "sonarr", "port": 8989})

        # Delete the custom app
        resp = client.delete("/api/custom-apps/clearapp")
        assert resp.status_code == 200

        # Verify forced_detector was cleared for the guest that used it
        data = store.load()
        gc = data.get("guest_config", {})
        assert "forced_detector" not in gc.get("pve1:100", {})
        # Other guest's forced_detector should be preserved
        assert gc.get("pve1:101", {}).get("forced_detector") == "sonarr"

    def test_builtin_name_rejected(self, client) -> None:
        resp = client.post("/api/custom-apps", json={
            "name": "sonarr",
            "display_name": "Fake Sonarr",
            "default_port": 1234,
        })
        assert resp.status_code == 422
