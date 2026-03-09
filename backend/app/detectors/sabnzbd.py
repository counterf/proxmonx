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
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["X-Api-Key"] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api?mode=version&output=json",
                headers=headers,
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                return data.get("version")
        except Exception:
            logger.debug("Failed to get SABnzbd version from %s:%d", host, port)
        return None
