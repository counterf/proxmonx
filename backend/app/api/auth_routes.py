"""Authentication API routes."""

from __future__ import annotations

import hmac
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.auth import hash_password, verify_password

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/auth")

# --- Simple in-memory rate limiter (IP-keyed, sliding window) ---
_login_attempts: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60  # seconds

# Dummy hash used to normalise timing when username is wrong
_DUMMY_HASH = "scrypt:" + "0" * 32 + ":" + "0" * 128


def _client_ip(request: Request) -> str:
    """Extract client IP, only trusting X-Forwarded-For when explicitly enabled."""
    settings = getattr(request.app.state, "settings", None)
    trust_proxy = settings.trust_proxy_headers if settings else False
    forwarded = request.headers.get("x-forwarded-for")
    if trust_proxy and forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_secure_request(request: Request) -> bool:
    """Return True if the original client request used HTTPS.

    Only trusts x-forwarded-proto when trust_proxy_headers is enabled,
    consistent with _client_ip().
    """
    settings = getattr(request.app.state, "settings", None)
    trust_proxy = settings.trust_proxy_headers if settings else False
    if trust_proxy:
        proto = request.headers.get("x-forwarded-proto", "").lower()
        if proto:
            return proto == "https"
    return request.url.scheme == "https"


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is within the allowed rate limit."""
    now = time.monotonic()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < _RATE_LIMIT_WINDOW]
    _login_attempts[ip] = attempts
    if len(attempts) >= _RATE_LIMIT_MAX:
        return False
    _login_attempts[ip].append(now)
    return True


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=256)
    password: str = Field(..., max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=1024)
    new_password: str = Field(..., min_length=8, max_length=1024)


@auth_router.post("/login")
async def login(body: LoginRequest, request: Request):
    """Validate credentials and set a session cookie."""
    client_ip = _client_ip(request)
    if not _check_rate_limit(client_ip):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    config_store = request.app.state.config_store
    session_store = request.app.state.session_store
    data = config_store.load_auth()

    stored_username = data.get("auth_username", "root")
    stored_hash = data.get("auth_password_hash", "")

    # Always run verify_password to normalise response time (prevent username enumeration).
    username_ok = hmac.compare_digest(body.username, stored_username)
    hash_to_check = stored_hash if username_ok and stored_hash else _DUMMY_HASH
    password_ok = verify_password(body.password, hash_to_check)

    if not username_ok or not password_ok:
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    token = session_store.create()
    response = JSONResponse({"success": True})
    response.set_cookie(
        key="proxmon_session",
        value=token,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
        max_age=86400,
    )
    logger.info("User '%s' logged in", body.username)
    return response


@auth_router.post("/logout")
async def logout(request: Request):
    """Revoke the current session and clear the cookie."""
    session_store = request.app.state.session_store
    token = request.cookies.get("proxmon_session")
    if token:
        session_store.revoke(token)
    response = JSONResponse({"success": True})
    response.delete_cookie(
        key="proxmon_session",
        path="/",
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
    )
    return response


@auth_router.get("/status")
async def auth_status(request: Request):
    """Return current auth mode and whether the caller is authenticated."""
    config_store = request.app.state.config_store
    session_store = request.app.state.session_store
    data = config_store.load_auth()
    auth_mode = data.get("auth_mode", "disabled")

    if auth_mode == "disabled":
        # Auth is off — caller is always implicitly authenticated.
        return {"auth_mode": auth_mode, "authenticated": True, "username": None}

    token = request.cookies.get("proxmon_session")
    authenticated = bool(token and session_store.is_valid(token))
    username = data.get("auth_username", "root") if authenticated else None
    return {"auth_mode": auth_mode, "authenticated": authenticated, "username": username}


@auth_router.post("/change-password")
async def change_password(body: ChangePasswordRequest, request: Request):
    """Change the auth password (requires active session + current password)."""
    client_ip = _client_ip(request)
    if not _check_rate_limit(client_ip):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    session_store = request.app.state.session_store
    token = request.cookies.get("proxmon_session")
    if not token or not session_store.is_valid(token):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    config_store = request.app.state.config_store
    data = config_store.load_auth()

    stored_hash = data.get("auth_password_hash", "")
    # Allow recovery from an empty-hash state (e.g. migration/older config); in that
    # case the active authenticated session may set a first password directly.
    if stored_hash and not verify_password(body.current_password, stored_hash):
        return JSONResponse({"detail": "Current password is incorrect"}, status_code=400)

    config_store.update_scalar("auth_password_hash", hash_password(body.new_password))
    # Invalidate every other active session after password rotation.
    session_store.revoke_all(except_token=token)
    logger.info("Auth password changed")
    return {"success": True}
