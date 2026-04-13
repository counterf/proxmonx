"""Tests for authentication API routes."""

from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.core.config_store import ConfigStore
from app.core.session_store import SessionStore


def _make_app(tmp_path, auth_mode="forms", password="proxmon!", **extra_config):
    """Create a minimal FastAPI app with auth routes and middleware for testing."""
    import app.api.auth_routes as _auth_routes_mod
    _auth_routes_mod._login_attempts.clear()

    from fastapi import FastAPI
    from app.api.auth_routes import auth_router
    from app.api.routes import router, _get_scheduler, _get_settings, _get_config_store
    from app.middleware.auth_middleware import AuthMiddleware
    from app.config import Settings

    db_path = str(tmp_path / "test.db")
    config_store = ConfigStore(db_path)
    session_store = SessionStore(db_path)

    data = {
        "auth_mode": auth_mode,
        "auth_username": "root",
        "auth_password_hash": hash_password(password) if password else "",
        **extra_config,
    }
    config_store.save(data)

    app = FastAPI()
    app.state.config_store = config_store
    app.state.session_store = session_store

    settings = config_store.merge_into_settings(Settings())
    app.state.settings = settings
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

    def test_logout_without_valid_session_still_clears_cookie(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
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
        assert data["username"] is None

    def test_auth_status_forms_not_logged_in(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_mode"] == "forms"
        assert data["authenticated"] is False
        assert data["username"] is None

    def test_auth_status_forms_logged_in(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["username"] == "root"


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
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        resp = client.post(
            "/api/auth/change-password",
            json={"current_password": "proxmon!", "new_password": "newpass12"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Old password should fail
        resp2 = client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        assert resp2.status_code == 401
        # New password should work
        resp3 = client.post("/api/auth/login", json={"username": "root", "password": "newpass12"})
        assert resp3.status_code == 200

    def test_change_password_wrong_current_returns_400(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        resp = client.post(
            "/api/auth/change-password",
            json={"current_password": "wrongpass", "new_password": "newpass12"},
        )
        assert resp.status_code == 400
        assert "incorrect" in resp.json()["detail"].lower()

    def test_change_password_revokes_other_sessions(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        login_resp = client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        assert login_resp.status_code == 200
        current_token = login_resp.cookies.get("proxmon_session")
        assert current_token is not None

        other_token = app.state.session_store.create()
        assert app.state.session_store.is_valid(other_token) is True

        resp = client.post(
            "/api/auth/change-password",
            json={"current_password": "proxmon!", "new_password": "newpass12"},
        )
        assert resp.status_code == 200
        assert app.state.session_store.is_valid(current_token) is True
        assert app.state.session_store.is_valid(other_token) is False

    def test_change_password_without_session_returns_401(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post(
            "/api/auth/change-password",
            json={"current_password": "proxmon!", "new_password": "newpass12"},
        )
        assert resp.status_code == 401

    def test_change_password_too_short_returns_422(self, tmp_path) -> None:
        """Pydantic min_length=8 rejects short passwords with 422."""
        app = _make_app(tmp_path)
        client = TestClient(app)
        client.post("/api/auth/login", json={"username": "root", "password": "proxmon!"})
        resp = client.post(
            "/api/auth/change-password",
            json={"current_password": "proxmon!", "new_password": "short"},
        )
        assert resp.status_code == 422

    def test_change_password_allows_empty_hash_recovery(self, tmp_path) -> None:
        app = _make_app(tmp_path, password="")
        client = TestClient(app)
        token = app.state.session_store.create()
        client.cookies.set("proxmon_session", token)

        resp = client.post(
            "/api/auth/change-password",
            json={"current_password": "", "new_password": "newpass12"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_api_key_cannot_change_password(self, tmp_path) -> None:
        """proxmon_api_key bypass must not allow changing the UI password."""
        app = _make_app(tmp_path, proxmon_api_key="test-api-key")
        client = TestClient(app)
        resp = client.post(
            "/api/auth/change-password",
            json={"current_password": "proxmon!", "new_password": "newpass12"},
            headers={"x-api-key": "test-api-key"},
        )
        assert resp.status_code == 401


class TestApiKeyBypass:
    def test_api_key_reaches_protected_route(self, tmp_path) -> None:
        """A valid proxmon_api_key should bypass session auth for regular routes."""
        app = _make_app(tmp_path, proxmon_api_key="test-api-key")
        client = TestClient(app)
        resp = client.get("/api/guests", headers={"x-api-key": "test-api-key"})
        assert resp.status_code == 200


class TestRateLimiting:
    def test_rate_limit_blocks_after_max_attempts(self, tmp_path) -> None:
        """After 10 failed login attempts, the 11th should return 429."""
        app = _make_app(tmp_path)
        client = TestClient(app)
        for _ in range(10):
            client.post("/api/auth/login", json={"username": "root", "password": "wrong"})
        resp = client.post("/api/auth/login", json={"username": "root", "password": "wrong"})
        assert resp.status_code == 429

    def test_rate_limit_uses_forwarded_ip(self, tmp_path) -> None:
        """X-Forwarded-For should be used for rate limiting, not the socket peer."""
        app = _make_app(tmp_path, trust_proxy_headers=True)
        client = TestClient(app)
        for _ in range(10):
            client.post(
                "/api/auth/login",
                json={"username": "root", "password": "wrong"},
                headers={"x-forwarded-for": "203.0.113.42"},
            )
        resp = client.post(
            "/api/auth/login",
            json={"username": "root", "password": "wrong"},
            headers={"x-forwarded-for": "203.0.113.42"},
        )
        assert resp.status_code == 429
        resp2 = client.post(
            "/api/auth/login",
            json={"username": "root", "password": "wrong"},
            headers={"x-forwarded-for": "198.51.100.1"},
        )
        assert resp2.status_code == 401

    def test_rate_limit_ignores_forwarded_ip_by_default(self, tmp_path) -> None:
        """Without trust_proxy_headers, spoofed XFF values must not bypass limits."""
        app = _make_app(tmp_path)  # trust_proxy_headers defaults to False
        client = TestClient(app)
        for i in range(10):
            client.post(
                "/api/auth/login",
                json={"username": "root", "password": "wrong"},
                headers={"x-forwarded-for": f"198.51.100.{i}"},
            )
        resp = client.post(
            "/api/auth/login",
            json={"username": "root", "password": "wrong"},
            headers={"x-forwarded-for": "203.0.113.99"},
        )
        assert resp.status_code == 429


class TestSetupFlowAuthExemptions:
    def test_setup_test_connection_allowed_while_unconfigured(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        # Unconfigured setup calls should not be blocked by auth middleware.
        resp = client.post(
            "/api/settings/test-connection",
            json={
                "host": "http://127.0.0.1:65535",
                "token_id": "root@pam!token",
                "token_secret": "secret",
                "node": "pve",
            },
        )
        assert resp.status_code == 200
        assert "success" in resp.json()

    def test_setup_test_connection_ignores_api_key_requirement_when_unconfigured(self, tmp_path) -> None:
        app = _make_app(tmp_path, proxmon_api_key="required")
        client = TestClient(app)
        resp = client.post(
            "/api/settings/test-connection",
            json={
                "host": "http://127.0.0.1:65535",
                "token_id": "root@pam!token",
                "token_secret": "secret",
                "node": "pve",
            },
        )
        assert resp.status_code == 200


class TestInputLimits:
    def test_oversized_username_rejected(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post(
            "/api/auth/login",
            json={"username": "a" * 257, "password": "password"},
        )
        assert resp.status_code == 422

    def test_oversized_password_rejected(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post(
            "/api/auth/login",
            json={"username": "root", "password": "a" * 1025},
        )
        assert resp.status_code == 422
