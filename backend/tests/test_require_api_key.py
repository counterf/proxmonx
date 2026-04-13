"""Tests for _require_api_key: session cookies must be accepted alongside API key headers."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.helpers import _require_api_key
from app.core.config_store import ConfigStore
from app.core.session_store import SessionStore


@pytest.fixture()
def app(tmp_path: Path):
    """Minimal FastAPI app with a protected endpoint, API key configured."""
    db_path = str(tmp_path / "test.db")
    config_store = ConfigStore(db_path)
    config_store.save({
        "proxmon_api_key": "test-secret-key",
        "proxmox_hosts": [{
            "id": "pve1", "label": "PVE1",
            "host": "https://10.0.0.1:8006",
            "token_id": "root@pam!test",
            "token_secret": "secret-uuid",
            "node": "pve",
        }],
    })
    session_store = SessionStore(db_path)

    settings = SimpleNamespace(proxmon_api_key="test-secret-key")

    _app = FastAPI()
    _app.state.config_store = config_store
    _app.state.settings = settings
    _app.state.session_store = session_store

    @_app.get("/protected", dependencies=[Depends(_require_api_key)])
    def protected():
        return {"ok": True}

    return _app, session_store


class TestRequireApiKey:
    def test_valid_session_cookie_accepted(self, app):
        """A valid session cookie should bypass the API key check."""
        _app, session_store = app
        token = session_store.create()
        client = TestClient(_app)
        resp = client.get("/protected", cookies={"proxmon_session": token})
        assert resp.status_code == 200

    def test_no_auth_rejected(self, app):
        """No API key header and no session cookie should be rejected."""
        _app, _ = app
        client = TestClient(_app)
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_valid_api_key_header_accepted(self, app):
        """A valid X-Api-Key header should be accepted."""
        _app, _ = app
        client = TestClient(_app)
        resp = client.get("/protected", headers={"X-Api-Key": "test-secret-key"})
        assert resp.status_code == 200

    def test_valid_bearer_token_accepted(self, app):
        """A valid Authorization: Bearer token should be accepted."""
        _app, _ = app
        client = TestClient(_app)
        resp = client.get("/protected", headers={"Authorization": "Bearer test-secret-key"})
        assert resp.status_code == 200

    def test_invalid_session_cookie_rejected(self, app):
        """An invalid session cookie should not bypass the API key check."""
        _app, _ = app
        client = TestClient(_app)
        resp = client.get("/protected", cookies={"proxmon_session": "bogus-token"})
        assert resp.status_code == 401

    def test_wrong_api_key_rejected(self, app):
        """A wrong API key should be rejected even without session."""
        _app, _ = app
        client = TestClient(_app)
        resp = client.get("/protected", headers={"X-Api-Key": "wrong-key"})
        assert resp.status_code == 401
