"""Authentication middleware for protected routes."""

from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class AuthMiddleware(BaseHTTPMiddleware):
    """Gate requests behind session authentication when auth is enabled."""

    EXEMPT_PATHS = {
        "/health",
        "/api/auth/login",
        "/api/auth/status",
        "/api/setup/status",
    }

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 1. Always pass OPTIONS through so CORS preflight is never blocked.
        if request.method == "OPTIONS":
            return await call_next(request)

        # 2. Exempt paths pass through unconditionally
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        # 2. Load auth settings from config store
        config_store = getattr(request.app.state, "config_store", None)
        if config_store is None:
            return await call_next(request)

        data = config_store.load()
        auth_mode = data.get("auth_mode", "forms")

        # 3. Auth disabled -> pass through
        if auth_mode == "disabled":
            return await call_next(request)

        # 4. Check X-Api-Key / Authorization header (backward compat with PROXMON_API_KEY)
        expected_api_key = os.environ.get("PROXMON_API_KEY")
        if expected_api_key:
            token = request.headers.get("x-api-key")
            if not token:
                auth_header = request.headers.get("authorization", "")
                if auth_header.lower().startswith("bearer "):
                    token = auth_header[7:].strip()
            if token and hmac.compare_digest(token, expected_api_key):
                return await call_next(request)

        # 5. Check session cookie
        session_store = getattr(request.app.state, "session_store", None)
        if session_store is not None:
            session_token = request.cookies.get("proxmon_session")
            if session_token and session_store.is_valid(session_token):
                return await call_next(request)

        # 6. Unauthorized
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
