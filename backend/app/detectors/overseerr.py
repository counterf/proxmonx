"""Overseerr detector."""

import logging

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class OverseerrDetector(BaseDetector):
    name = "overseerr"
    display_name = "Overseerr"
    github_repo = "sct/overseerr"
    aliases: list[str] = []
    default_port = 5055
    docker_images = ["sctx/overseerr", "linuxserver/overseerr"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["X-Api-Key"] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api/v1/status", headers=headers,
                http_client=http_client,
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                return data.get("version")
            if resp.status_code == 401:
                logger.warning("Auth failed for overseerr on %s:%d -- check API key", host, port)
        except Exception:
            logger.debug("Failed to get Overseerr version from %s:%d", host, port)
        return None
