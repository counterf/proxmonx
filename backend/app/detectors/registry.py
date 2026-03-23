"""Detector plugin registry."""

from app.detectors.base import BaseDetector
from app.detectors.caddy import CaddyDetector
from app.detectors.docker_generic import DockerGenericDetector
from app.detectors.http_json import make_detector
from app.detectors.plex import PlexDetector
from app.detectors.qbittorrent import QBittorrentDetector
from app.detectors.sabnzbd import SABnzbdDetector

# All registered detectors (order matters for priority)
ALL_DETECTORS: list[BaseDetector] = [
    make_detector("sonarr"),
    make_detector("radarr"),
    make_detector("bazarr"),
    make_detector("prowlarr"),
    PlexDetector(),
    make_detector("immich"),
    make_detector("overseerr"),
    make_detector("seerr"),
    make_detector("gitea"),
    QBittorrentDetector(),
    SABnzbdDetector(),
    make_detector("traefik"),
    CaddyDetector(),
    make_detector("ntfy"),
]

# Docker generic detector is separate (fallback)
DOCKER_DETECTOR = DockerGenericDetector()

# Lookup by name
DETECTOR_MAP: dict[str, BaseDetector] = {d.name: d for d in ALL_DETECTORS}
