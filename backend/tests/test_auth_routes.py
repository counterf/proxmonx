"""Tests for authentication API routes."""

import pytest
from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.core.config_store import ConfigStore
from app.core.session_store import SessionStore


def _make_app(tmp_path, auth_mode="forms", password="proxmon!"):
    """Create a minimal FastAPI app with auth routes and middleware for testing."""
    import app.api.auth_routes as _auth_routes_mod
    # Reset module-level rate limiter so tests are independent of each other.
    _auth_routes_mod._login_attempts.clear()

    from fastapi import FastAPI
    from app.api.auth_routes import auth_router
    from app.api.routes import router, _get_scheduler, _get_settings, _get_config_store
    from app.middleware.auth_middleware import AuthMiddleware
    from app.config import Settings

    db_path = str(tmp_path / "test.db")
    config_store = ConfigStore(db_path)
    session_store = SessionStore(db_path)

    # Seed config
    data = {
        "auth_mode": auth_mode,
        "auth_username": "root",
        "auth_password_hash": hash_password(password) if password else "",
    }
    config_store.save(data)

    app = FastAPI()
    app.state.config_store = config_store
    app.state.session_store = session_store

    # Wire up dependency overrides for routes that use them
    settings = config_store.merge_into_settings(Settings())
    app.dependency_overrides[_get_scheduler] = lambda: None
    app.dependency_overrides[_get_settings] = lambda: settings
    app.dependency_overrides[_get_config_store] = lambda: config_store

    app.add_middleware(AuthMiddleware)
    app.include_router(auth_router)
    app.include_router(router)
    return app


class TestLogin:
    def test_login_success(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "proxmon_session" in resp.cookies

    def test_login_wrong_password(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"username": "root", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_wrong_username(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "proxmon!"})
        assert resp.status_code == 401


class TestLogout:
    def test_logout(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        # Login first
        login_resp = client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        assert login_resp.status_code == 200
        # Logout
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestAuthStatus:
    def test_auth_status_disabled(self, tmp_path) -> None:
        app = _make_app(tmp_path, auth_mode="disabled")
        client = TestClient(app)
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_mode"] == "disabled"
        # When auth is disabled the caller is always implicitly authenticated.
        assert data["authenticated"] is True

    def test_auth_status_forms_not_logged_in(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_mode"] == "forms"
        assert data["authenticated"] is False

    def test_auth_status_forms_logged_in(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True


class TestProtectedRoutes:
    def test_protected_route_without_session(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.get("/api/guests")
        assert resp.status_code == 401

    def test_protected_route_with_valid_session(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        resp = client.get("/api/guests")
        assert resp.status_code == 200

    def test_protected_route_auth_disabled(self, tmp_path) -> None:
        app = _make_app(tmp_path, auth_mode="disabled")
        client = TestClient(app)
        resp = client.get("/api/guests")
        assert resp.status_code == 200


class TestDefaultPassword:
    def test_default_password_bootstrapped(self, tmp_path) -> None:
        """When auth_mode=forms and hash is set to 'proxmon!', login should work."""
        app = _make_app(tmp_path, password="proxmon!")
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestChangePassword:
    def test_change_password(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        # Login
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        # Change password (must be >= 8 chars)
        resp = client.post("/api/auth/change-password", json={"new_password": "newpass1"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Old password should fail
        resp2 = client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        assert resp2.status_code == 401
        # New password should work
        resp3 = client.post("/api/auth/login", json={"username": "root", "password": "newpass1"})
        assert resp3.status_code == 200

    def test_change_password_without_session_returns_401(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        # No login — change-password must reject unauthenticated callers
        resp = client.post("/api/auth/change-password", json={"new_password": "newpass1"})
        assert resp.status_code == 401

    def test_change_password_too_short_returns_400(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        resp = client.post("/api/auth/change-password", json={"new_password": "short"})
        assert resp.status_code == 400

    def test_api_key_cannot_change_password(self, tmp_path) -> None:
        """PROXMON_API_KEY bypass must not allow changing the UI password."""
        import os
        app = _make_app(tmp_path)
        client = TestClient(app)
        # Send a valid API key header but no session cookie
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("PROXMON_API_KEY", "test-api-key")
            resp = client.post(
                "/api/auth/change-password",
                json={"new_password": "newpass12"},
                headers={"x-api-key": "test-api-key"},
            )
        # Must be 401 — API key does not satisfy the session-only check
        assert resp.status_code == 401


class TestApiKeyBypass:
    def test_api_key_reaches_protected_route(self, tmp_path) -> None:
        """A valid PROXMON_API_KEY should bypass session auth for regular routes."""
        import os
        app = _make_app(tmp_path)
        client = TestClient(app)
        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("PROXMON_API_KEY", "test-api-key")
            resp = client.get("/api/guests", headers={"x-api-key": "test-api-key"})
        assert resp.status_code == 200
