"""Caddy detector."""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class CaddyDetector(BaseDetector):
    name = "caddy"
    display_name = "Caddy"
    github_repo = "caddyserver/caddy"
    aliases: list[str] = []
    default_port = 2019
    docker_images = ["caddy", "caddy/caddy"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
    ) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"http://{host}:{port}/config/")
            if resp.status_code == 200:
                # Caddy admin API returns config; version is in Server header
                server_header = resp.headers.get("Server", "")
                # Header format: "Caddy/2.7.6"
                if "/" in server_header:
                    return server_header.split("/", 1)[1].strip()
        except Exception:
            logger.debug("Failed to get Caddy version from %s:%d", host, port)
        return None
