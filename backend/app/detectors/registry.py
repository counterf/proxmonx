"""Detector plugin registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.detectors.base import BaseDetector
from app.detectors.caddy import CaddyDetector
from app.detectors.docker_generic import DockerGenericDetector
from app.detectors.http_json import DetectorConfig, HttpJsonDetector, make_detector
from app.detectors.jackett import JackettDetector
from app.detectors.librespeed_rust import LibreSpeedRustDetector
from app.detectors.plex import PlexDetector
from app.detectors.qbittorrent import QBittorrentDetector
from app.detectors.sabnzbd import SABnzbdDetector

if TYPE_CHECKING:
    from app.config import CustomAppDef

logger = logging.getLogger(__name__)

# All registered detectors (order matters for priority)
ALL_DETECTORS: list[BaseDetector] = [
    make_detector("sonarr"),
    make_detector("radarr"),
    make_detector("bazarr"),
    make_detector("prowlarr"),
    make_detector("lidarr"),
    make_detector("readarr"),
    make_detector("whisparr"),
    PlexDetector(),
    make_detector("immich"),
    make_detector("overseerr"),
    make_detector("seerr"),
    make_detector("gitea"),
    QBittorrentDetector(),
    SABnzbdDetector(),
    JackettDetector(),
    LibreSpeedRustDetector(),
    make_detector("traefik"),
    CaddyDetector(),
    make_detector("ntfy"),
]

# Docker generic detector is separate (fallback)
DOCKER_DETECTOR = DockerGenericDetector()

# Lookup by name
DETECTOR_MAP: dict[str, BaseDetector] = {d.name: d for d in ALL_DETECTORS}

# Built-in names (frozen at import time) -- used to prevent custom app collisions
_BUILTIN_NAMES: frozenset[str] = frozenset(DETECTOR_MAP.keys())

# Custom detectors injected at runtime
_CUSTOM_DETECTORS: list[BaseDetector] = []


def load_custom_detectors(custom_defs: list[CustomAppDef]) -> None:
    """Rebuild custom detectors and sync into ALL_DETECTORS / DETECTOR_MAP.

    Idempotent: removes stale custom entries before adding new ones.
    Skips entries whose name collides with a built-in detector.
    """
    global _CUSTOM_DETECTORS
    # Remove previous custom detectors
    for d in _CUSTOM_DETECTORS:
        DETECTOR_MAP.pop(d.name, None)
        if d in ALL_DETECTORS:
            ALL_DETECTORS.remove(d)
    _CUSTOM_DETECTORS = []

    for defn in custom_defs:
        if defn.name in _BUILTIN_NAMES:
            logger.warning("Custom app '%s' conflicts with built-in -- skipped", defn.name)
            continue
        cfg = DetectorConfig(
            name=defn.name,
            display_name=defn.display_name,
            github_repo=defn.github_repo,
            default_port=defn.default_port,
            path=defn.version_path or "",
            docker_images=list(defn.docker_images),
            aliases=list(defn.aliases),
            accepts_api_key=defn.accepts_api_key,
            auth_header=defn.auth_header,
            version_keys=tuple(defn.version_keys),
            strip_v=defn.strip_v,
        )
        detector = HttpJsonDetector(cfg)
        _CUSTOM_DETECTORS.append(detector)
        ALL_DETECTORS.append(detector)
        DETECTOR_MAP[detector.name] = detector
