"""Sonarr detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class SonarrDetector(BaseDetector):
    name = "sonarr"
    display_name = "Sonarr"
    github_repo = "Sonarr/Sonarr"
    aliases: list[str] = []
    default_port = 8989
    docker_images = ["sonarr", "linuxserver/sonarr", "hotio/sonarr"]

    async def get_installed_version(self, host: str, port: int | None = None) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"http://{host}:{port}/api/v3/system/status")
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                return data.get("version")
        except Exception:
            logger.debug("Failed to get Sonarr version from %s:%d", host, port)
        return None
