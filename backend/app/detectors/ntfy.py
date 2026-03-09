"""ntfy detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class NtfyDetector(BaseDetector):
    name = "ntfy"
    display_name = "ntfy"
    github_repo = "binwiederhier/ntfy"
    aliases: list[str] = []
    default_port = 80
    docker_images = ["ntfy", "binwiederhier/ntfy"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
    ) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"{scheme}://{host}:{port}/v1/info")
            if resp.status_code == 200:
                data: dict[str, str] = resp.json()
                version = data.get("version", "")
                return version.lstrip("v") if version else None
        except Exception:
            logger.debug("Failed to get ntfy version from %s:%d", host, port)
        return None
