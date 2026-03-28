"""TrueNAS SCALE detector — JSON-RPC 2.0 over WebSocket.

Connection flow (per probe):
  1. Open wss://{host}:{port}/api/v2.0/websocket  (ssl verify per config)
  2. auth.login_with_api_key → True / False
  3. system.info              → .version  (installed)
  4. update.status            → .status.new_version.version  (latest, or None)
  5. Close

Auth: api_key passed as first positional param to auth.login_with_api_key.
"""

from __future__ import annotations

import json
import logging
import ssl

from app.detectors.base import BaseDetector
from app.detectors.http_json import ProbeError

logger = logging.getLogger(__name__)

_MSG_ID = 0


def _next_id() -> int:
    global _MSG_ID
    _MSG_ID += 1
    return _MSG_ID


class TrueNASDetector(BaseDetector):
    name = "truenas"
    display_name = "TrueNAS"
    github_repo = None  # latest version fetched from update.status, not GitHub
    aliases = ["truenas-scale"]
    default_port = 443
    docker_images: list[str] = []
    accepts_api_key = True

    def __init__(self) -> None:
        super().__init__()
        self._cached_latest: str | None = None

    async def get_installed_version(
        self,
        host: str,
        port: int | None = None,
        api_key: str | None = None,
        scheme: str = "https",
        http_client=None,
    ) -> str | None:
        port = port or self.default_port
        # wss:// for https (default), ws:// for http
        ws_scheme = "wss" if scheme in ("https", "wss") else "ws"
        uri = f"{ws_scheme}://{host}:{port}/api/v2.0/websocket"

        try:
            import websockets
        except ImportError as exc:
            raise ProbeError("websockets package not installed") from exc

        ssl_ctx: ssl.SSLContext | bool
        if ws_scheme == "wss":
            ssl_ctx = ssl.create_default_context()
            # honour the global verify_ssl setting via the detector's base class
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        else:
            ssl_ctx = False  # type: ignore[assignment]

        try:
            async with websockets.connect(uri, ssl=ssl_ctx, open_timeout=10) as ws:
                # 1. Authenticate
                if api_key:
                    auth_id = _next_id()
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": auth_id,
                        "method": "auth.login_with_api_key",
                        "params": [api_key],
                    }))
                    auth_resp = json.loads(await ws.recv())
                    if auth_resp.get("id") != auth_id or not auth_resp.get("result"):
                        raise ProbeError("Authentication failed — check API key")

                # 2. system.info → installed version
                info_id = _next_id()
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": info_id,
                    "method": "system.info",
                    "params": [],
                }))
                info_resp = json.loads(await ws.recv())
                if "error" in info_resp:
                    raise ProbeError(f"system.info error: {info_resp['error'].get('message', info_resp['error'])}")
                installed = info_resp.get("result", {}).get("version")
                if not installed:
                    raise ProbeError("version field missing from system.info response")

                # 3. update.status → latest available version (best-effort)
                try:
                    upd_id = _next_id()
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": upd_id,
                        "method": "update.status",
                        "params": [],
                    }))
                    upd_resp = json.loads(await ws.recv())
                    if "error" not in upd_resp:
                        result = upd_resp.get("result", {})
                        new_ver = (result.get("status") or {}).get("new_version") or {}
                        self._cached_latest = new_ver.get("version") or str(installed)
                    else:
                        self._cached_latest = str(installed)
                except Exception:
                    self._cached_latest = str(installed)

                return str(installed)

        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeError(f"WebSocket connection failed: {exc}") from exc

    async def get_latest_version(self, http_client=None) -> str | None:
        """Return the version cached by get_installed_version (from update.status)."""
        return self._cached_latest
