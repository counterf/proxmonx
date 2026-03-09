"""Guest discovery and app detection orchestrator."""

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.core.github import GitHubClient
from app.core.proxmox import ProxmoxClient
from app.core.ssh import SSHClient
from app.detectors.base import BaseDetector
from app.detectors.registry import ALL_DETECTORS, DOCKER_DETECTOR
from app.models.guest import GuestInfo, VersionCheck

logger = logging.getLogger(__name__)

# Limit concurrent probes to avoid overwhelming the network
MAX_CONCURRENT_PROBES = 10

# Maximum number of version history entries to retain per guest
MAX_VERSION_HISTORY = 10


class DiscoveryEngine:
    """Orchestrates guest discovery, app detection, and version checking."""

    def __init__(
        self,
        proxmox: ProxmoxClient,
        github: GitHubClient,
        ssh: SSHClient,
        http_client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._proxmox = proxmox
        self._github = github
        self._ssh = ssh
        self._http_client = http_client
        self._settings = settings
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)
        # Share the HTTP client with all detectors
        if http_client:
            for detector in ALL_DETECTORS:
                detector.http_client = http_client

    async def run_full_cycle(
        self,
        existing_guests: dict[str, GuestInfo],
    ) -> dict[str, GuestInfo]:
        """Run a complete discovery + detection + version check cycle.

        Returns updated guest map.
        """
        logger.info("Starting full discovery cycle")
        start = datetime.now(timezone.utc)

        # Step 1: Discover guests from Proxmox
        guests = await self._proxmox.list_guests()
        logger.info("Discovered %d guests", len(guests))

        # Step 2: Resolve IPs and detect apps concurrently
        tasks = [
            self._process_guest(guest, existing_guests.get(guest.id))
            for guest in guests
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Step 3: Build updated guest map
        updated: dict[str, GuestInfo] = {}
        for result in results:
            if isinstance(result, GuestInfo):
                updated[result.id] = result
            elif isinstance(result, Exception):
                logger.error("Guest processing failed: %s", result)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(
            "Discovery cycle complete: %d guests in %.1fs", len(updated), elapsed
        )
        return updated

    async def _process_guest(
        self,
        guest: GuestInfo,
        previous: GuestInfo | None,
    ) -> GuestInfo:
        """Process a single guest: resolve IP, detect app, check versions."""
        async with self._semaphore:
            try:
                # Resolve IP
                if not guest.ip:
                    guest.ip = await self._proxmox.get_guest_network(
                        guest.id, guest.type
                    )

                # Skip stopped guests for app detection
                if guest.status != "running":
                    guest.update_status = "unknown"
                    guest.last_checked = datetime.now(timezone.utc)
                    if previous:
                        guest.version_history = list(previous.version_history)
                    guest.version_history.append(
                        VersionCheck(
                            timestamp=guest.last_checked,
                            installed_version=None,
                            latest_version=None,
                            update_status="unknown",
                        )
                    )
                    guest.version_history = guest.version_history[-MAX_VERSION_HISTORY:]
                    return guest

                # Detect app
                await self._detect_app(guest)

                # Get installed version
                if guest.detector_used and guest.ip:
                    await self._check_version(guest)

                # Preserve version history from previous checks
                if previous:
                    guest.version_history = list(previous.version_history)

                # Record this check, then truncate
                guest.last_checked = datetime.now(timezone.utc)
                guest.version_history.append(
                    VersionCheck(
                        timestamp=guest.last_checked,
                        installed_version=guest.installed_version,
                        latest_version=guest.latest_version,
                        update_status=guest.update_status,
                    )
                )
                guest.version_history = guest.version_history[-MAX_VERSION_HISTORY:]

                return guest
            except Exception:
                logger.exception("Error processing guest %s (%s)", guest.name, guest.id)
                guest.update_status = "unknown"
                guest.last_checked = datetime.now(timezone.utc)
                return guest

    async def _detect_app(self, guest: GuestInfo) -> None:
        """Attempt to detect which app a guest is running."""
        # Strategy 1 & 2: Name and tag matching
        for detector in ALL_DETECTORS:
            method = detector.detect(guest)
            if method:
                guest.app_name = detector.display_name
                guest.detector_used = detector.name
                guest.detection_method = method
                guest.raw_detection_output = {
                    "detector": detector.name,
                    "method": method,
                    "matched_name": guest.name,
                    "matched_tags": ", ".join(guest.tags),
                }
                logger.debug(
                    "Detected %s on %s via %s", detector.name, guest.name, method
                )
                return

        # Strategy 3: Docker container inspection via SSH
        if guest.ip:
            await self._detect_via_docker(guest)

    async def _detect_via_docker(self, guest: GuestInfo) -> None:
        """Detect app by inspecting Docker containers on the guest."""
        output = await self._ssh.execute(
            guest.ip,  # type: ignore[arg-type]  # ip is checked before call
            'docker ps --format "{{.Image}}"',
        )
        if not output:
            return

        images = [line.strip() for line in output.splitlines() if line.strip()]
        for image in images:
            for detector in ALL_DETECTORS:
                if detector.match_docker_image(image):
                    guest.app_name = detector.display_name
                    guest.detector_used = detector.name
                    guest.detection_method = "docker"
                    guest.raw_detection_output = {
                        "detector": detector.name,
                        "method": "docker",
                        "docker_image": image,
                    }
                    logger.debug(
                        "Detected %s on %s via Docker image %s",
                        detector.name,
                        guest.name,
                        image,
                    )
                    return

            # Generic Docker fallback: record the image but no version check
            version = DOCKER_DETECTOR.parse_image_version(image)
            if version:
                guest.app_name = image.split(":")[0].split("/")[-1]
                guest.detector_used = "docker"
                guest.detection_method = "docker"
                guest.installed_version = version
                guest.raw_detection_output = {
                    "detector": "docker_generic",
                    "method": "docker",
                    "docker_image": image,
                    "parsed_version": version,
                }
                return

    async def _check_version(self, guest: GuestInfo) -> None:
        """Check installed and latest versions for a detected app."""
        from app.detectors.registry import DETECTOR_MAP

        detector: BaseDetector | None = DETECTOR_MAP.get(guest.detector_used or "")
        if not detector or not guest.ip:
            return

        # Look up per-app overrides from settings
        port_override: int | None = None
        api_key: str | None = None
        if self._settings and self._settings.app_config:
            app_cfg = self._settings.app_config.get(detector.name)
            if app_cfg:
                port_override = app_cfg.port
                api_key = app_cfg.api_key
                logger.debug(
                    "Using overrides for %s: port=%s, api_key=%s",
                    detector.name,
                    port_override or "default",
                    "set" if api_key else "none",
                )

        # Get installed version
        try:
            guest.installed_version = await detector.get_installed_version(
                guest.ip, port=port_override, api_key=api_key,
            )
        except Exception:
            logger.debug(
                "Version probe failed for %s on %s", detector.name, guest.name
            )

        # Get latest version from GitHub
        if detector.github_repo:
            try:
                guest.latest_version = await self._github.get_latest_version(
                    detector.github_repo
                )
            except Exception:
                logger.debug(
                    "GitHub version lookup failed for %s", detector.github_repo
                )

        # Determine update status
        guest.update_status = _determine_update_status(
            guest.installed_version, guest.latest_version
        )


def _normalize_version_string(version: str) -> str:
    """Strip v prefix and build-hash suffixes (e.g. '1.40.0.7998-c29d4c0c8' -> '1.40.0.7998')."""
    version = version.lstrip("v")
    # Strip everything after a hyphen (build hashes like -c29d4c0c8)
    if "-" in version:
        version = version.split("-")[0]
    return version


def _determine_update_status(
    installed: str | None, latest: str | None
) -> str:
    """Compare installed vs latest version, handling build-hash suffixes."""
    if not installed or not latest:
        return "unknown"

    from packaging.version import Version, InvalidVersion

    norm_installed = _normalize_version_string(installed)
    norm_latest = _normalize_version_string(latest)

    try:
        return "up-to-date" if Version(norm_installed) >= Version(norm_latest) else "outdated"
    except InvalidVersion:
        # Fall back to normalized string equality
        return "up-to-date" if norm_installed == norm_latest else "outdated"
