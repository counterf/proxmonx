"""Plex Media Server detector."""

import gzip
import logging
import xml.etree.ElementTree as ET

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)

_PLEX_PACKAGES_URL = (
    "https://repo.plex.tv/deb/dists/public/main/binary-amd64/Packages.gz"
)


class PlexDetector(BaseDetector):
    name = "plex"
    display_name = "Plex"
    github_repo = "plexinc/pms-docker"
    aliases = ["plexmediaserver", "pms"]
    default_port = 32400
    docker_images = ["plex", "linuxserver/plex", "plexinc/pms-docker"]

    async def get_latest_version(
        self,
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        """Fetch latest Plex version from the official deb repository."""
        try:
            resp = await self._http_get(
                _PLEX_PACKAGES_URL,
                timeout=10.0,
                http_client=http_client,
            )
            if resp.status_code != 200:
                logger.warning("Plex Packages.gz returned HTTP %d", resp.status_code)
                return None
            content = gzip.decompress(resp.content).decode("utf-8", errors="replace")
            # Debian Packages format: stanzas separated by blank lines.
            # Find the plexmediaserver stanza and extract Version:.
            in_plex = False
            for line in content.splitlines():
                if line.startswith("Package:"):
                    in_plex = line.split(":", 1)[1].strip() == "plexmediaserver"
                elif in_plex and line.startswith("Version:"):
                    raw = line.split(":", 1)[1].strip()
                    # Strip build hash suffix: "1.40.0.7998-c29d4c0c8" → "1.40.0.7998"
                    return raw.split("-")[0] if "-" in raw else raw
        except Exception:
            logger.warning("Failed to fetch latest Plex version from deb repo")
        return None

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
