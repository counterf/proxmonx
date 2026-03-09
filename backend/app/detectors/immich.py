"""Immich detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class ImmichDetector(BaseDetector):
    name = "immich"
    display_name = "Immich"
    github_repo = "immich-app/immich"
    aliases: list[str] = []
    default_port = 2283
    docker_images = ["immich", "ghcr.io/immich-app/immich-server"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
    ) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"{scheme}://{host}:{port}/api/server/about")
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                version = data.get("version", "")
                return version.lstrip("v") if version else None
        except Exception:
            logger.debug("Failed to get Immich version from %s:%d", host, port)
        return None
