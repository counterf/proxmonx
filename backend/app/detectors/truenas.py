"""TrueNAS SCALE detector — JSON-RPC 2.0 over WebSocket.

Connection flow (per probe):
  1. Open wss://{host}:{port}/api/current  (ssl verify per config)
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

class TrueNASDetector(BaseDetector):
    name = "truenas"
    display_name = "TrueNAS"
    github_repo = None  # latest version fetched from update.status, not GitHub
    aliases = ["truenas-scale"]
    default_port = 443
    docker_images: list[str] = []
    accepts_api_key = True

    async def get_installed_version(
        self,
        host: str,
        port: int | None = None,
        api_key: str | None = None,
        scheme: str = "https",
        http_client=None,
    ) -> tuple[str, str | None]:
        port = port or self.default_port
        # wss:// for https (default), ws:// for http
        ws_scheme = "wss" if scheme in ("https", "wss") else "ws"
        uri = f"{ws_scheme}://{host}:{port}/api/current"

        try:
            import websockets
        except ImportError as exc:
            raise ProbeError("websockets package not installed") from exc

        ssl_ctx: ssl.SSLContext | bool
        if ws_scheme == "wss":
            # TrueNAS commonly uses self-signed certificates; skip verification.
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        else:
            ssl_ctx = False  # type: ignore[assignment]

        # Local message ID counter — avoids shared state across concurrent probes
        # (e.g. two TrueNAS hosts probed simultaneously via asyncio.gather).
        _msg_id = 0

        def next_id() -> int:
            nonlocal _msg_id
            _msg_id += 1
            return _msg_id

        logger.debug("TrueNAS WSS probe starting: %s", uri)
        try:
            async with websockets.connect(uri, ssl=ssl_ctx, open_timeout=10) as ws:
                # 1. Authenticate
                if api_key:
                    auth_id = next_id()
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": auth_id,
                        "method": "auth.login_with_api_key",
                        "params": [api_key],
                    }))
                    auth_resp = json.loads(await ws.recv())
                    if auth_resp.get("id") != auth_id or not auth_resp.get("result"):
                        raise ProbeError("Authentication failed — check API key")
                    logger.debug("TrueNAS WSS auth OK: %s", host)

                # 2. system.info → installed version
                info_id = next_id()
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
                    upd_id = next_id()
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
                        latest = new_ver.get("version")
                        cached_latest = latest or str(installed)
                        if latest and latest != str(installed):
                            logger.info("TrueNAS update available on %s: %s → %s", host, installed, latest)
                        else:
                            logger.info("TrueNAS probe OK: %s installed=%s up-to-date", host, installed)
                    else:
                        cached_latest = str(installed)
                        logger.warning("TrueNAS update.status error on %s: %s", host, upd_resp.get("error"))
                except Exception as exc:
                    cached_latest = str(installed)
                    logger.warning("TrueNAS update.status failed on %s: %s", host, exc)

                return str(installed), cached_latest

        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeError(f"WebSocket connection failed: {exc}") from exc

    async def get_latest_version(self, http_client=None) -> str | None:
        """TrueNAS latest version is returned as the second element of the tuple
        from get_installed_version(). This method should not be called directly
        for TrueNAS guests; discovery.py handles the tuple unpacking."""
        return None
