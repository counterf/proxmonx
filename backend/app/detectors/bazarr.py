"""Bazarr detector."""

import logging
from typing import Any

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class BazarrDetector(BaseDetector):
    name = "bazarr"
    display_name = "Bazarr"
    github_repo = "morpheus65535/bazarr"
    aliases: list[str] = []
    default_port = 6767
    docker_images = ["bazarr", "linuxserver/bazarr", "hotio/bazarr"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-KEY"] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api/system/status",
                headers=headers,
                http_client=http_client,
            )
            if resp.status_code == 200:
                data: dict[str, Any] = resp.json()
                nested = data.get("data")
                if isinstance(nested, dict):
                    version = nested.get("bazarr_version")
                    if version:
                        return version
                return data.get("bazarr_version")
            if resp.status_code == 401:
                logger.warning("Auth failed for bazarr on %s:%d -- check API key", host, port)
        except Exception:
            logger.debug("Failed to get Bazarr version from %s:%d", host, port)
        return None
