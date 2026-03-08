"""SABnzbd detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class SABnzbdDetector(BaseDetector):
    name = "sabnzbd"
    display_name = "SABnzbd"
    github_repo = "sabnzbd/sabnzbd"
    aliases = ["sab"]
    default_port = 8085
    docker_images = ["sabnzbd", "linuxserver/sabnzbd"]

    async def get_installed_version(self, host: str, port: int | None = None) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(
                f"http://{host}:{port}/api?mode=version&output=json"
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                return data.get("version")
        except Exception:
            logger.debug("Failed to get SABnzbd version from %s:%d", host, port)
        return None
