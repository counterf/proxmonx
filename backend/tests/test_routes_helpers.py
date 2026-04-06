"""Tests for API route helper functions."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.helpers import _AppConfigBase, _keep_or_replace
from app.api.routes.guests import GuestConfigSaveRequest
from app.api.helpers import _get_scheduler, _get_settings, _get_config_store
from app.core.config_store import ConfigStore
from app.config import Settings


class TestKeepOrReplace:
    def test_none_incoming_keeps_existing(self) -> None:
        assert _keep_or_replace(None, "existing-secret") == "existing-secret"

    def test_empty_incoming_clears_existing(self) -> None:
        # Empty string is an explicit "clear" — removes a previously set secret
        assert _keep_or_replace("", "existing-secret") is None

    def test_masked_sentinel_keeps_existing(self) -> None:
        assert _keep_or_replace("***", "existing-secret") == "existing-secret"

    def test_new_value_replaces_existing(self) -> None:
        assert _keep_or_replace("new-secret", "old-secret") == "new-secret"

    def test_new_value_replaces_none(self) -> None:
        assert _keep_or_replace("new-secret", None) == "new-secret"

    def test_none_incoming_with_none_existing_returns_none(self) -> None:
        assert _keep_or_replace(None, None) is None

    def test_empty_incoming_with_none_existing_returns_none(self) -> None:
        assert _keep_or_replace("", None) is None

    def test_masked_sentinel_with_none_existing_returns_none(self) -> None:
        assert _keep_or_replace("***", None) is None

    def test_masked_sentinel_with_empty_existing_returns_none(self) -> None:
        assert _keep_or_replace("***", "") is None

    def test_whitespace_only_replaces(self) -> None:
        assert _keep_or_replace("  ", "old") == "  "


class TestAppConfigGithubRepo:
    def test_normalizes_https_url(self) -> None:
        m = _AppConfigBase(github_repo="https://github.com/owner/repo")
        assert m.github_repo == "owner/repo"

    def test_passthrough_owner_repo(self) -> None:
        m = _AppConfigBase(github_repo="owner/repo")
        assert m.github_repo == "owner/repo"

    def test_garbage_raises(self) -> None:
        with pytest.raises(ValidationError):
            _AppConfigBase(github_repo="not-a-valid-repo")


class TestGuestConfigForcedDetector:
    def test_valid_forced_detector(self) -> None:
        m = GuestConfigSaveRequest(forced_detector="sonarr")
        assert m.forced_detector == "sonarr"

    def test_empty_normalized_to_none(self) -> None:
        m = GuestConfigSaveRequest(forced_detector="")
        assert m.forced_detector is None

    def test_unknown_detector_raises(self) -> None:
        with pytest.raises(ValidationError):
            GuestConfigSaveRequest(forced_detector="not-a-detector")


def _make_guest_config_app(tmp_path):
    """Create a minimal FastAPI app with guest routes for testing."""
    from app.api.routes import router

    db_path = str(tmp_path / "test.db")
    config_store = ConfigStore(db_path)
    config_store.save({})

    app = FastAPI()
    settings = config_store.merge_into_settings(Settings())
    app.state.config_store = config_store
    app.state.settings = settings
    app.dependency_overrides[_get_scheduler] = lambda: None
    app.dependency_overrides[_get_settings] = lambda: settings
    app.dependency_overrides[_get_config_store] = lambda: config_store
    app.include_router(router)
    return app


class TestSaveGuestConfigVersionCmdValidation:
    """Validate that save_guest_config rejects unsafe ssh_version_cmd."""

    def test_safe_version_cmd_accepted(self, tmp_path) -> None:
        app = _make_guest_config_app(tmp_path)
        client = TestClient(app)
        resp = client.put(
            "/api/guests/test-guest/config",
            json={"ssh_version_cmd": "cat /etc/version"},
        )
        assert resp.status_code == 200

    def test_unsafe_version_cmd_rejected(self, tmp_path) -> None:
        app = _make_guest_config_app(tmp_path)
        client = TestClient(app)
        resp = client.put(
            "/api/guests/test-guest/config",
            json={"ssh_version_cmd": "cat /etc/version; rm -rf /"},
        )
        assert resp.status_code == 422
        assert "unsafe shell patterns" in resp.text

    def test_unsafe_backtick_cmd_rejected(self, tmp_path) -> None:
        app = _make_guest_config_app(tmp_path)
        client = TestClient(app)
        resp = client.put(
            "/api/guests/test-guest/config",
            json={"ssh_version_cmd": "echo `whoami`"},
        )
        assert resp.status_code == 422

    def test_unsafe_subshell_cmd_rejected(self, tmp_path) -> None:
        app = _make_guest_config_app(tmp_path)
        client = TestClient(app)
        resp = client.put(
            "/api/guests/test-guest/config",
            json={"ssh_version_cmd": "echo $(whoami)"},
        )
        assert resp.status_code == 422

    def test_safe_pipe_accepted(self, tmp_path) -> None:
        app = _make_guest_config_app(tmp_path)
        client = TestClient(app)
        resp = client.put(
            "/api/guests/test-guest/config",
            json={"ssh_version_cmd": "dpkg -l sonarr | grep sonarr | awk '{print $3}'"},
        )
        assert resp.status_code == 200

    def test_none_version_cmd_accepted(self, tmp_path) -> None:
        app = _make_guest_config_app(tmp_path)
        client = TestClient(app)
        resp = client.put(
            "/api/guests/test-guest/config",
            json={},
        )
        assert resp.status_code == 200
