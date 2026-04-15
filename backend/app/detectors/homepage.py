"""Homepage (gethomepage.dev) — no HTTP version endpoint."""

import httpx

from app.detectors.base import BaseDetector


class HomepageDetector(BaseDetector):
    """Homepage dashboard; version only available via SSH (package.json)."""

    name = "homepage"
    display_name = "Homepage"
    github_repo = "gethomepage/homepage"
    aliases: list[str] = []
    default_port = 3000
    docker_images = ["gethomepage/homepage"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        return None
