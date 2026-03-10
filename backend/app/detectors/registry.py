"""Detector plugin registry."""

from app.detectors.base import BaseDetector
from app.detectors.bazarr import BazarrDetector
from app.detectors.caddy import CaddyDetector
from app.detectors.docker_generic import DockerGenericDetector
from app.detectors.gitea import GiteaDetector
from app.detectors.immich import ImmichDetector
from app.detectors.ntfy import NtfyDetector
from app.detectors.overseerr import OverseerrDetector
from app.detectors.seer import SeerDetector
from app.detectors.plex import PlexDetector
from app.detectors.prowlarr import ProwlarrDetector
from app.detectors.qbittorrent import QBittorrentDetector
from app.detectors.radarr import RadarrDetector
from app.detectors.sabnzbd import SABnzbdDetector
from app.detectors.sonarr import SonarrDetector
from app.detectors.traefik import TraefikDetector

# All registered detectors (order matters for priority)
ALL_DETECTORS: list[BaseDetector] = [
    SonarrDetector(),
    RadarrDetector(),
    BazarrDetector(),
    ProwlarrDetector(),
    PlexDetector(),
    ImmichDetector(),
    OverseerrDetector(),
    SeerDetector(),
    GiteaDetector(),
    QBittorrentDetector(),
    SABnzbdDetector(),
    TraefikDetector(),
    CaddyDetector(),
    NtfyDetector(),
]

# Docker generic detector is separate (fallback)
DOCKER_DETECTOR = DockerGenericDetector()

# Lookup by name
DETECTOR_MAP: dict[str, BaseDetector] = {d.name: d for d in ALL_DETECTORS}


def get_detector(name: str) -> BaseDetector | None:
    """Get a detector by name."""
    return DETECTOR_MAP.get(name)


def get_all_detectors() -> list[BaseDetector]:
    """Return all registered detectors."""
    return ALL_DETECTORS
