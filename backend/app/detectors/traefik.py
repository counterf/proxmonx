"""Traefik detector."""

import logging

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class TraefikDetector(BaseDetector):
    name = "traefik"
    display_name = "Traefik"
    github_repo = "traefik/traefik"
    aliases: list[str] = []
    default_port = 8080
    docker_images = ["traefik", "traefik/traefik"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"{scheme}://{host}:{port}/api/version", http_client=http_client)
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                version = data.get("Version", "")
                return version.lstrip("v") if version else None
        except Exception:
            logger.debug("Failed to get Traefik version from %s:%d", host, port)
        return None
