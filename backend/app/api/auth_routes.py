"""Authentication API routes."""

from __future__ import annotations

import hmac
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.auth import hash_password, verify_password

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/auth")

# --- Simple in-memory rate limiter (IP-keyed, sliding window) ---
_login_attempts: dict[str, list[float]] = {}
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60  # seconds

# Dummy hash used to normalise timing when username is wrong
_DUMMY_HASH = "scrypt:00" + "0" * 62 + ":" + "0" * 128


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
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    new_password: str


@auth_router.post("/login")
async def login(body: LoginRequest, request: Request):
    """Validate credentials and set a session cookie."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    config_store = request.app.state.config_store
    session_store = request.app.state.session_store
    data = config_store.load()

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
        samesite="lax",
        path="/",
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
    response.delete_cookie(key="proxmon_session", path="/")
    return response


@auth_router.get("/status")
async def auth_status(request: Request):
    """Return current auth mode and whether the caller is authenticated."""
    config_store = request.app.state.config_store
    session_store = request.app.state.session_store
    data = config_store.load()
    auth_mode = data.get("auth_mode", "forms")

    if auth_mode == "disabled":
        # Auth is off — caller is always implicitly authenticated.
        return {"auth_mode": auth_mode, "authenticated": True}

    token = request.cookies.get("proxmon_session")
    authenticated = bool(token and session_store.is_valid(token))
    return {"auth_mode": auth_mode, "authenticated": authenticated}


@auth_router.post("/change-password")
async def change_password(body: ChangePasswordRequest, request: Request):
    """Change the auth password (requires active session)."""
    # Explicit session check — API-key holders must not be able to change the UI password.
    session_store = request.app.state.session_store
    token = request.cookies.get("proxmon_session")
    if not token or not session_store.is_valid(token):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    if len(body.new_password) < 8:
        return JSONResponse(
            {"detail": "Password must be at least 8 characters"}, status_code=400
        )

    config_store = request.app.state.config_store
    data = config_store.load()
    data["auth_password_hash"] = hash_password(body.new_password)
    config_store.save(data)
    logger.info("Auth password changed")
    return {"success": True}
