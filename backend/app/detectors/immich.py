"""Immich detector."""

import logging

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class ImmichDetector(BaseDetector):
    name = "immich"
    display_name = "Immich"
    github_repo = "immich-app/immich"
    aliases: list[str] = []
    default_port = 2283
    docker_images = ["immich", "ghcr.io/immich-app/immich-server"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["x-api-key"] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api/server/about",
                headers=headers,
                http_client=http_client,
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                version = data.get("version", "")
                return version.lstrip("v") if version else None
        except Exception:
            logger.debug("Failed to get Immich version from %s:%d", host, port)
        return None
