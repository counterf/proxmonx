"""Gitea detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class GiteaDetector(BaseDetector):
    name = "gitea"
    display_name = "Gitea"
    github_repo = "go-gitea/gitea"
    aliases: list[str] = []
    default_port = 3000
    docker_images = ["gitea", "gitea/gitea"]

    async def get_installed_version(self, host: str, port: int | None = None) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"http://{host}:{port}/api/v1/version")
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                version = data.get("version", "")
                return version.lstrip("v") if version else None
        except Exception:
            logger.debug("Failed to get Gitea version from %s:%d", host, port)
        return None
