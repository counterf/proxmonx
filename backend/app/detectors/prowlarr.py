"""Prowlarr detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class ProwlarrDetector(BaseDetector):
    name = "prowlarr"
    display_name = "Prowlarr"
    github_repo = "Prowlarr/Prowlarr"
    aliases: list[str] = []
    default_port = 9696
    docker_images = ["prowlarr", "linuxserver/prowlarr", "hotio/prowlarr"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["X-Api-Key"] = api_key
        try:
            resp = await self._http_get(
                f"http://{host}:{port}/api/v1/system/status", headers=headers,
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                return data.get("version")
            if resp.status_code == 401:
                logger.warning("Auth failed for prowlarr on %s:%d -- check API key", host, port)
        except Exception:
            logger.debug("Failed to get Prowlarr version from %s:%d", host, port)
        return None
