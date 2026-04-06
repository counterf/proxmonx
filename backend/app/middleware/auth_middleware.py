"""Authentication middleware for protected routes."""

from __future__ import annotations

import hmac
import ipaddress

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class AuthMiddleware(BaseHTTPMiddleware):
    """Gate requests behind session authentication when auth is enabled."""

    EXEMPT_PATHS = {
        "/health",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/status",
        "/api/setup/status",
    }
    SETUP_EXEMPT_PATHS = {
        "/api/settings",
        "/api/settings/test-connection",
    }

    @staticmethod
    def _is_addr_local(addr_str: str) -> bool:
        """Return True if *addr_str* is a loopback or RFC-1918 private address.

        Non-IP hostnames (e.g. ``"localhost"``, ASGI test transports) are
        treated as local because real ASGI servers always provide socket-level
        IP addresses.
        """
        try:
            addr = ipaddress.ip_address(addr_str)
            return addr.is_loopback or addr.is_private
        except ValueError:
            return addr_str.lower() in {"localhost", "testclient", ""}

    @classmethod
    def _is_local_network(cls, request: Request) -> bool:
        """Return True if the request originates from loopback or a private network.

        In Docker Compose or behind a reverse proxy, the backend may see
        requests from an internal bridge network (172.x), which qualifies as
        private.
        """
        client_host = request.client.host if request.client else None
        if not client_host:
            return True
        if cls._is_addr_local(client_host):
            return True
        settings = getattr(request.app.state, "settings", None)
        trust_proxy = settings.trust_proxy_headers if settings else False
        if trust_proxy:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return cls._is_addr_local(forwarded.split(",")[0].strip())
        return False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 1. Always pass OPTIONS through so CORS preflight is never blocked.
        if request.method == "OPTIONS":
            return await call_next(request)

        # 2. Exempt paths pass through unconditionally
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        # 2b. Static frontend assets (non-API paths) pass through
        if not path.startswith("/api/"):
            return await call_next(request)

        # 3. Load auth settings from config store
        config_store = getattr(request.app.state, "config_store", None)
        if config_store is None:
            return await call_next(request)

        # Allow setup endpoints before proxmon is configured, but only from
        # loopback / private-network addresses to prevent a remote attacker
        # from racing to configure the instance first.
        if not config_store.is_configured() and path in self.SETUP_EXEMPT_PATHS:
            if self._is_local_network(request):
                return await call_next(request)
            return JSONResponse(
                {"detail": "Setup is only allowed from a local network"},
                status_code=403,
            )

        data = config_store.load_auth()
        auth_mode = data.get("auth_mode", "disabled")

        # 4. Auth disabled -> pass through
        if auth_mode == "disabled":
            return await call_next(request)

        # 5. Check X-Api-Key / Authorization header
        settings = getattr(request.app.state, "settings", None)
        expected_api_key = settings.proxmon_api_key if settings else None
        if expected_api_key:
            token = request.headers.get("x-api-key")
            if not token:
                auth_header = request.headers.get("authorization", "")
                if auth_header.lower().startswith("bearer "):
                    token = auth_header[7:].strip()
            if token and hmac.compare_digest(token, expected_api_key):
                return await call_next(request)

        # 6. Check session cookie
        session_store = getattr(request.app.state, "session_store", None)
        if session_store is not None:
            session_token = request.cookies.get("proxmon_session")
            if session_token and session_store.is_valid(session_token):
                return await call_next(request)

        # 7. Unauthorized
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
