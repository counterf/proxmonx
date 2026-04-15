"""Tautulli detector."""

import logging

import httpx

from app.detectors.base import BaseDetector
from app.detectors.http_json import ProbeError
from app.detectors.utils import normalize_version

logger = logging.getLogger(__name__)


class TautulliDetector(BaseDetector):
    name = "tautulli"
    display_name = "Tautulli"
    github_repo = "Tautulli/Tautulli"
    aliases: list[str] = []
    default_port = 8181
    docker_images = ["tautulli", "linuxserver/tautulli"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        params = f"apikey={api_key}&cmd=get_tautulli_info" if api_key else "cmd=get_tautulli_info"
        url = f"{scheme}://{host}:{port}/api/v2?{params}"
        try:
            resp = await self._http_get(url, http_client=http_client)
            if resp.status_code == 200:
                data = resp.json()
                version = (
                    data.get("response", {})
                    .get("data", {})
                    .get("tautulli_version")
                )
                if version:
                    return normalize_version(version, strip_v=True)
                raise ProbeError("Version key not found in response")
            if resp.status_code == 401:
                raise ProbeError("HTTP 401 -- check API key")
            raise ProbeError(f"HTTP {resp.status_code}")
        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeError(f"Connection failed: {exc}") from exc
