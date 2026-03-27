"""TrueNAS SCALE detector."""

from __future__ import annotations

import logging

from app.detectors.base import BaseDetector
from app.detectors.http_json import ProbeError

logger = logging.getLogger(__name__)


class TrueNASDetector(BaseDetector):
    name = "truenas"
    display_name = "TrueNAS"
    github_repo = "truenas/truenas-scale"
    aliases = ["truenas-scale"]
    default_port = 443
    docker_images: list[str] = []
    accepts_api_key = True

    async def get_installed_version(
        self,
        host: str,
        port: int | None = None,
        api_key: str | None = None,
        scheme: str = "https",
        http_client=None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api/v2.0/system/info",
                headers=headers,
                http_client=http_client,
            )
            if resp.status_code == 200:
                data = resp.json()
                version = data.get("version")
                if version:
                    return str(version)
                raise ProbeError("version key not found in response")
            if resp.status_code == 401:
                raise ProbeError("HTTP 401 -- check API key")
            raise ProbeError(f"HTTP {resp.status_code}")
        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeError(f"Connection failed: {exc}") from exc
