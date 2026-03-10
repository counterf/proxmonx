"""Plex Media Server detector."""

import logging
import xml.etree.ElementTree as ET

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class PlexDetector(BaseDetector):
    name = "plex"
    display_name = "Plex"
    github_repo = "plexinc/pms-docker"
    aliases = ["plexmediaserver", "pms"]
    default_port = 32400
    docker_images = ["plex", "linuxserver/plex", "plexinc/pms-docker"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"{scheme}://{host}:{port}/identity", http_client=http_client)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                version = root.get("version")
                if version:
                    # Plex versions look like "1.40.0.7998-c29d4c0c8"
                    return version.split("-")[0] if "-" in version else version
        except Exception:
            logger.debug("Failed to get Plex version from %s:%d", host, port)
        return None
