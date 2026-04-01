"""Jackett detector — admin config JSON requires API key."""

import logging

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class JackettDetector(BaseDetector):
    """Jackett exposes ``app_version`` on ``GET /api/v2.0/server/config`` with ``X-Api-Key`` header."""

    name = "jackett"
    display_name = "Jackett"
    github_repo = "Jackett/Jackett"
    aliases = []
    default_port = 9117
    docker_images = ["jackett", "linuxserver/jackett", "hotio/jackett"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        url = f"{scheme}://{host}:{port}/api/v2.0/server/config"
        if not api_key:
            return None
        headers = {"X-Api-Key": api_key}
        try:
            resp = await self._http_get(url, headers=headers, http_client=http_client)
            if resp.status_code == 200:
                ct = (resp.headers.get("content-type") or "").lower()
                if "json" in ct:
                    data = resp.json()
                    v = data.get("app_version")
                    if isinstance(v, str) and v:
                        return v.lstrip("v")
        except Exception:
            logger.debug("Failed to get Jackett version from %s:%d", host, port)
        return None
