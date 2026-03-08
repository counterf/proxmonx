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

    async def get_installed_version(self, host: str, port: int | None = None) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(
                f"http://{host}:{port}/api/bazarr/api/v1/system/status"
            )
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                return data.get("data", {}).get("bazarr_version") or data.get("bazarr_version")  # type: ignore[union-attr]
        except Exception:
            logger.debug("Failed to get Bazarr version from %s:%d", host, port)
        return None
