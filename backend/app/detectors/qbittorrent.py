"""qBittorrent detector."""

import logging

import httpx

from app.detectors.base import BaseDetector
from app.detectors.utils import normalize_version

logger = logging.getLogger(__name__)


class QBittorrentDetector(BaseDetector):
    name = "qbittorrent"
    display_name = "qBittorrent"
    github_repo = "qbittorrent/qBittorrent"
    aliases = ["qbt"]
    default_port = 8080
    docker_images = ["qbittorrent", "linuxserver/qbittorrent"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"{scheme}://{host}:{port}/api/v2/app/version", http_client=http_client)
            if resp.status_code == 200:
                # Returns plain text like "v4.6.3"
                version = resp.text.strip()
                return normalize_version(version, strip_v=True) if version else None
        except Exception:
            logger.debug("Failed to get qBittorrent version from %s:%d", host, port)
        return None
