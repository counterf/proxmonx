"""Seerr detector."""

import logging

import httpx

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class SeerDetector(BaseDetector):
    name = "seerr"
    display_name = "Seerr"
    github_repo = "seerr-team/seerr"
    aliases: list[str] = ["seer"]
    default_port = 5055
    docker_images = ["seerr/seerr"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["X-Api-Key"] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api/v1/status", headers=headers,
                http_client=http_client,
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                version = data.get("version")
                # Strip leading 'v' if present
                return version.lstrip("v") if version else None
            if resp.status_code == 401:
                logger.warning("Auth failed for seer on %s:%d -- check API key", host, port)
        except Exception:
            logger.debug("Failed to get Seer version from %s:%d", host, port)
        return None
