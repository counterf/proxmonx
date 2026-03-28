"""TrueNAS SCALE detector.

Installed version: GET /api/v2.0/system/info → .version
Latest version:   GET /api/v2.0/update/status → .status.new_version.version
                  (null new_version means already on the latest for the train)

Auth: Authorization: Bearer <api_key>
"""

from __future__ import annotations

import logging

from app.detectors.base import BaseDetector
from app.detectors.http_json import ProbeError

logger = logging.getLogger(__name__)


class TrueNASDetector(BaseDetector):
    name = "truenas"
    display_name = "TrueNAS"
    github_repo = None  # latest version fetched from update/status, not GitHub
    aliases = ["truenas-scale"]
    default_port = 443
    docker_images: list[str] = []
    accepts_api_key = True

    def __init__(self) -> None:
        super().__init__()
        self._cached_latest: str | None = None

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

        base_url = f"{scheme}://{host}:{port}"

        try:
            # Installed version
            info_resp = await self._http_get(
                f"{base_url}/api/v2.0/system/info",
                headers=headers,
                http_client=http_client,
            )
            if info_resp.status_code == 401:
                raise ProbeError("HTTP 401 -- check API key")
            if info_resp.status_code != 200:
                raise ProbeError(f"HTTP {info_resp.status_code}")
            installed = info_resp.json().get("version")
            if not installed:
                raise ProbeError("version key not found in response")

            # Latest version from TrueNAS update channel (best-effort)
            try:
                status_resp = await self._http_get(
                    f"{base_url}/api/v2.0/update/status",
                    headers=headers,
                    http_client=http_client,
                )
                if status_resp.status_code == 200:
                    new_ver = (
                        status_resp.json()
                        .get("status", {})
                        .get("new_version") or {}
                    )
                    self._cached_latest = new_ver.get("version") or str(installed)
                else:
                    self._cached_latest = str(installed)
            except Exception:
                self._cached_latest = str(installed)

            return str(installed)

        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeError(f"Connection failed: {exc}") from exc

    async def get_latest_version(self, http_client=None) -> str | None:
        """Return the version cached by get_installed_version (from update/status)."""
        return self._cached_latest
