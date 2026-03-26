"""Config-driven detector for apps with simple JSON version endpoints."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.detectors.base import BaseDetector
from app.detectors.utils import normalize_version

logger = logging.getLogger(__name__)


class ProbeError(Exception):
    """Raised when a version probe fails with a diagnosable reason."""


@dataclass(frozen=True)
class DetectorConfig:
    """Declarative config for a JSON-based version detector."""

    name: str
    display_name: str
    github_repo: str | None
    default_port: int
    path: str
    docker_images: list[str]
    aliases: list[str] = field(default_factory=list)
    accepts_api_key: bool = False
    auth_header: str | None = None
    version_keys: tuple[str, ...] = ("version",)
    strip_v: bool = False


SIMPLE_DETECTOR_CONFIGS: list[DetectorConfig] = [
    DetectorConfig(
        name="sonarr", display_name="Sonarr", github_repo="Sonarr/Sonarr",
        default_port=8989, path="/api/v3/system/status",
        docker_images=["sonarr", "linuxserver/sonarr", "hotio/sonarr"],
        accepts_api_key=True, auth_header="X-Api-Key",
    ),
    DetectorConfig(
        name="radarr", display_name="Radarr", github_repo="Radarr/Radarr",
        default_port=7878, path="/api/v3/system/status",
        docker_images=["radarr", "linuxserver/radarr", "hotio/radarr"],
        accepts_api_key=True, auth_header="X-Api-Key",
    ),
    DetectorConfig(
        name="bazarr", display_name="Bazarr", github_repo="morpheus65535/bazarr",
        default_port=6767, path="/api/system/status",
        docker_images=["bazarr", "linuxserver/bazarr", "hotio/bazarr"],
        accepts_api_key=True, auth_header="X-API-KEY",
        version_keys=("data.bazarr_version", "bazarr_version"),
    ),
    DetectorConfig(
        name="prowlarr", display_name="Prowlarr", github_repo="Prowlarr/Prowlarr",
        default_port=9696, path="/api/v1/system/status",
        docker_images=["prowlarr", "linuxserver/prowlarr", "hotio/prowlarr"],
        accepts_api_key=True, auth_header="X-Api-Key",
    ),
    DetectorConfig(
        name="lidarr", display_name="Lidarr", github_repo="Lidarr/Lidarr",
        default_port=8686, path="/api/v1/system/status",
        docker_images=["lidarr", "linuxserver/lidarr", "hotio/lidarr"],
        accepts_api_key=True, auth_header="X-Api-Key",
    ),
    DetectorConfig(
        name="readarr", display_name="Readarr", github_repo="Readarr/Readarr",
        default_port=8787, path="/api/v1/system/status",
        docker_images=["readarr", "linuxserver/readarr", "hotio/readarr"],
        accepts_api_key=True, auth_header="X-Api-Key",
    ),
    DetectorConfig(
        name="whisparr", display_name="Whisparr", github_repo="Whisparr/Whisparr",
        default_port=6969, path="/api/v3/system/status",
        docker_images=["whisparr", "linuxserver/whisparr", "hotio/whisparr"],
        accepts_api_key=True, auth_header="X-Api-Key",
    ),
    DetectorConfig(
        name="immich", display_name="Immich", github_repo="immich-app/immich",
        default_port=2283, path="/api/server/about",
        docker_images=["immich", "ghcr.io/immich-app/immich-server"],
        accepts_api_key=True, auth_header="x-api-key",
        strip_v=True,
    ),
    DetectorConfig(
        name="overseerr", display_name="Overseerr", github_repo="sct/overseerr",
        default_port=5055, path="/api/v1/status",
        docker_images=["sctx/overseerr", "linuxserver/overseerr"],
        accepts_api_key=True, auth_header="X-Api-Key",
    ),
    DetectorConfig(
        name="seerr", display_name="Seerr", github_repo="seerr-team/seerr",
        default_port=5055, path="/api/v1/status",
        docker_images=["seerr/seerr"],
        aliases=["seer"],
        accepts_api_key=True, auth_header="X-Api-Key",
        strip_v=True,
    ),
    DetectorConfig(
        name="gitea", display_name="Gitea", github_repo="go-gitea/gitea",
        default_port=3000, path="/api/v1/version",
        docker_images=["gitea", "gitea/gitea"],
        strip_v=True,
    ),
    DetectorConfig(
        name="traefik", display_name="Traefik", github_repo="traefik/traefik",
        default_port=8080, path="/api/version",
        docker_images=["traefik", "traefik/traefik"],
        version_keys=("Version",),
        strip_v=True,
    ),
    DetectorConfig(
        name="ntfy", display_name="ntfy", github_repo="binwiederhier/ntfy",
        default_port=80, path="/v1/info",
        docker_images=["ntfy", "binwiederhier/ntfy"],
        strip_v=True,
    ),
]

_CONFIG_MAP: dict[str, DetectorConfig] = {c.name: c for c in SIMPLE_DETECTOR_CONFIGS}


def make_detector(name: str) -> HttpJsonDetector:
    """Create a detector instance from the config table by name."""
    return HttpJsonDetector(_CONFIG_MAP[name])


class HttpJsonDetector(BaseDetector):
    """Generic detector for apps exposing version via a JSON HTTP endpoint."""

    def __init__(self, config: DetectorConfig) -> None:
        super().__init__()
        self.name = config.name
        self.display_name = config.display_name
        self.github_repo = config.github_repo
        self.aliases = list(config.aliases)
        self.default_port = config.default_port
        self.docker_images = list(config.docker_images)
        self.accepts_api_key = config.accepts_api_key
        self._path = config.path
        self._auth_header = config.auth_header
        self._version_keys = config.version_keys
        self._strip_v = config.strip_v

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        port = port or self.default_port
        headers: dict[str, str] = {}
        if api_key and self._auth_header:
            headers[self._auth_header] = api_key
        try:
            resp = await self._http_get(
                f"{scheme}://{host}:{port}{self._path}",
                headers=headers,
                http_client=http_client,
            )
            if resp.status_code == 200:
                data = resp.json()
                version = self._extract_version(data)
                if version and self._strip_v:
                    version = normalize_version(version, strip_v=True)
                if version:
                    return version
                raise ProbeError("Version key not found in response")
            if resp.status_code == 401:
                raise ProbeError("HTTP 401 -- check API key")
            raise ProbeError(f"HTTP {resp.status_code}")
        except ProbeError:
            raise
        except Exception as exc:
            raise ProbeError(f"Connection failed: {exc}") from exc

    def _extract_version(self, data: dict) -> str | None:
        """Walk version_keys (dot-separated paths) and return first match."""
        for key_path in self._version_keys:
            obj: object = data
            for part in key_path.split("."):
                if isinstance(obj, dict):
                    obj = obj.get(part)
                else:
                    obj = None
                    break
            if isinstance(obj, str) and obj:
                return obj
        return None
