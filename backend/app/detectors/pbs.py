"""Proxmox Backup Server detector."""

import gzip
import logging
import re

import httpx
from packaging.version import InvalidVersion, Version

from app.detectors.base import BaseDetector
from app.detectors.http_json import ProbeError
from app.detectors.utils import normalize_version

logger = logging.getLogger(__name__)

# Hardcoded to 'trixie' (Debian 13 / PBS 4.x / Proxmox 9).  For older
# installations on bookworm the reported latest version may be newer
# than what is available in the user's configured repository.
_PBS_PACKAGES_URL = (
    "http://download.proxmox.com/debian/pbs/dists/trixie/"
    "pbs-no-subscription/binary-amd64/Packages.gz"
)


class PBSDetector(BaseDetector):
    name = "pbs"
    display_name = "Proxmox Backup Server"
    github_repo = None
    aliases = ["proxmox-backup", "proxmox-backup-server"]
    default_port = 8007
    docker_images = ["proxmox-backup-server"]
    accepts_api_key = True
    scheme = "https"

    def _name_matches(self, guest_name: str) -> bool:
        tokens = set(re.split(r"[-_.\s]+", guest_name.lower()))
        if "pbs" in tokens:
            return True
        if "proxmox" in tokens and "backup" in tokens:
            return True
        return super()._name_matches(guest_name)

    async def get_latest_version(
        self,
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        """Fetch latest PBS version from the Proxmox apt repository."""
        try:
            resp = await self._http_get(
                _PBS_PACKAGES_URL,
                timeout=10.0,
                http_client=http_client,
            )
            if resp.status_code != 200:
                logger.warning("PBS Packages.gz returned HTTP %d", resp.status_code)
                return None
            content = gzip.decompress(resp.content).decode("utf-8", errors="replace")
            best: Version | None = None
            best_raw: str | None = None
            in_pbs = False
            for line in content.splitlines():
                if line.startswith("Package:"):
                    in_pbs = line.split(":", 1)[1].strip() == "proxmox-backup-server"
                elif in_pbs and line.startswith("Version:"):
                    raw = line.split(":", 1)[1].strip()
                    # Strip Debian revision suffix (-2, -1+trixie1) so the
                    # version matches the bare semver from the PBS JSON API.
                    clean = re.sub(r"-\d+(\+.*)?$", "", raw)
                    try:
                        parsed = Version(normalize_version(clean))
                    except InvalidVersion:
                        continue
                    if best is None or parsed > best:
                        best = parsed
                        best_raw = clean
            if best_raw:
                return normalize_version(best_raw)
        except Exception:
            logger.warning("Failed to fetch latest PBS version from apt repo")
        return None

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "https",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}/api2/json/version",
                headers=headers,
                http_client=http_client,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                version = data.get("version")
                if version:
                    return normalize_version(version)
                raise ProbeError("Version key not found in response")
            if resp.status_code == 401:
                raise ProbeError("HTTP 401 -- check API key")
            raise ProbeError(f"HTTP {resp.status_code}")
        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeError(f"Connection failed: {exc}") from exc
