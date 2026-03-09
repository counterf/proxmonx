"""Bazarr detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class BazarrDetector(BaseDetector):
    name = "bazarr"
    display_name = "Bazarr"
    github_repo = "morpheus65535/bazarr"
    aliases: list[str] = []
    default_port = 6767
    docker_images = ["bazarr", "linuxserver/bazarr", "hotio/bazarr"]
    accepts_api_key = True

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-KEY"] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api/bazarr/api/v1/system/status",
                headers=headers,
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                return data.get("data", {}).get("bazarr_version") or data.get("bazarr_version")  # type: ignore[union-attr]
            if resp.status_code == 401:
                logger.warning("Auth failed for bazarr on %s:%d -- check API key", host, port)
        except Exception:
            logger.debug("Failed to get Bazarr version from %s:%d", host, port)
        return None
