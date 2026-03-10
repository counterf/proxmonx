"""Guest discovery and app detection orchestrator."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import ProxmoxHostConfig, Settings
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

    async def run_full_cycle(
        self,
        existing_guests: dict[str, GuestInfo],
    ) -> dict[str, GuestInfo]:
        """Run a complete discovery + detection + version check cycle.

        When multiple Proxmox hosts are configured, discovery runs against
        each host in parallel and the results are merged.  Guest IDs are
        namespaced as ``{host_id}:{vmid}`` to avoid collisions.
        """
        hosts = self._settings.get_hosts() if self._settings else []

        if not hosts:
            # Legacy single-host path (no proxmox_hosts configured)
            return await self._run_single_host_cycle(existing_guests)

        if len(hosts) == 1:
            return await self._run_host_cycle(
                hosts[0], existing_guests,
            )

        # Multi-host: parallel discovery
        logger.info("Starting multi-host discovery across %d hosts", len(hosts))
        start = datetime.now(timezone.utc)

        tasks = [
            self._run_host_cycle(host, existing_guests)
            for host in hosts
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: dict[str, GuestInfo] = {}
        for i, result in enumerate(results):
            if isinstance(result, dict):
                merged.update(result)
            elif isinstance(result, Exception):
                logger.error(
                    "Discovery failed for host %s: %s", hosts[i].label, result,
                )

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(
            "Multi-host discovery complete: %d guests from %d hosts in %.1fs",
            len(merged), len(hosts), elapsed,
        )
        return merged

    async def _run_single_host_cycle(
        self,
        existing_guests: dict[str, GuestInfo],
    ) -> dict[str, GuestInfo]:
        """Legacy single-host discovery cycle (no host namespacing)."""
        logger.info("Starting full discovery cycle")
        start = datetime.now(timezone.utc)

        guests = await self._proxmox.list_guests()
        logger.info("Discovered %d guests", len(guests))

        tasks = [
            self._process_guest(guest, existing_guests.get(guest.id))
            for guest in guests
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

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

    async def _run_host_cycle(
        self,
        host_config: ProxmoxHostConfig,
        existing_guests: dict[str, GuestInfo],
    ) -> dict[str, GuestInfo]:
        """Run discovery for a single Proxmox host, namespacing guest IDs."""
        logger.info("Starting discovery for host %s (%s)", host_config.label, host_config.host)
        start = datetime.now(timezone.utc)

        # Build a per-host ProxmoxClient using a temporary Settings-like config
        settings = self._build_host_settings(host_config)
        proxmox = ProxmoxClient(settings, http_client=self._http_client)

        guests = await proxmox.list_guests()
        logger.info("Host %s: discovered %d guests", host_config.label, len(guests))

        # Namespace guest IDs and set host fields
        for guest in guests:
            guest.id = f"{host_config.id}:{guest.id}"
            guest.host_id = host_config.id
            guest.host_label = host_config.label

        tasks = [
            self._process_guest(
                guest,
                existing_guests.get(guest.id),
                host_config=host_config,
            )
            for guest in guests
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        updated: dict[str, GuestInfo] = {}
        for result in results:
            if isinstance(result, GuestInfo):
                updated[result.id] = result
            elif isinstance(result, Exception):
                logger.error("Guest processing failed on host %s: %s", host_config.label, result)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(
            "Host %s discovery complete: %d guests in %.1fs",
            host_config.label, len(updated), elapsed,
        )
        return updated

    def _build_host_settings(self, host_config: ProxmoxHostConfig) -> Settings:
        """Build a Settings instance from a ProxmoxHostConfig for ProxmoxClient."""
        return Settings(
            proxmox_host=host_config.host,
            proxmox_token_id=host_config.token_id,
            proxmox_token_secret=host_config.token_secret,
            proxmox_node=host_config.node,
            verify_ssl=host_config.verify_ssl,
            discover_vms=self._settings.discover_vms if self._settings else False,
            ssh_enabled=self._settings.ssh_enabled if self._settings else True,
            ssh_username=host_config.ssh_username or (self._settings.ssh_username if self._settings else "root"),
            ssh_key_path=host_config.ssh_key_path or (self._settings.ssh_key_path if self._settings else None),
            ssh_password=host_config.ssh_password or (self._settings.ssh_password if self._settings else None),
        )

    async def _process_guest(
        self,
        guest: GuestInfo,
        previous: GuestInfo | None,
        host_config: ProxmoxHostConfig | None = None,
    ) -> GuestInfo:
        """Process a single guest: resolve IP, detect app, check versions."""
        async with self._semaphore:
            try:
                # Resolve IP -- need the correct proxmox client for this host
                if not guest.ip:
                    if host_config:
                        settings = self._build_host_settings(host_config)
                        proxmox = ProxmoxClient(settings, http_client=self._http_client)
                    else:
                        proxmox = self._proxmox
                    # Extract raw vmid from namespaced ID
                    raw_vmid = guest.id.split(":")[-1] if ":" in guest.id else guest.id
                    guest.ip = await proxmox.get_guest_network(
                        raw_vmid, guest.type
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
                await self._detect_app(guest, host_config=host_config)

                # Get installed version
                if guest.detector_used and guest.ip:
                    await self._check_version(guest, host_config=host_config)

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

    async def _detect_app(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig | None = None,
    ) -> None:
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

    async def _check_version(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig | None = None,
    ) -> None:
        """Check installed and latest versions for a detected app."""
        from app.detectors.registry import DETECTOR_MAP

        detector: BaseDetector | None = DETECTOR_MAP.get(guest.detector_used or "")
        if not detector or not guest.ip:
            return

        # Look up per-app overrides from settings
        port_override: int | None = None
        api_key: str | None = None
        scheme: str = "http"
        github_repo_override: str | None = None
        ssh_version_cmd: str | None = None
        ssh_username: str | None = None
        ssh_key_path: str | None = None
        ssh_password: str | None = None
        if self._settings and self._settings.app_config:
            app_cfg = self._settings.app_config.get(detector.name)
            if app_cfg:
                port_override = app_cfg.port
                api_key = app_cfg.api_key
                if app_cfg.scheme:
                    scheme = app_cfg.scheme
                github_repo_override = app_cfg.github_repo
                ssh_version_cmd = app_cfg.ssh_version_cmd
                ssh_username = app_cfg.ssh_username
                ssh_key_path = app_cfg.ssh_key_path
                ssh_password = app_cfg.ssh_password
                logger.debug(
                    "Using overrides for %s: port=%s, api_key=%s, scheme=%s, github_repo=%s",
                    detector.name,
                    port_override or "default",
                    "set" if api_key else "none",
                    scheme,
                    github_repo_override or "default",
                )

        # Store the effective port so GuestInfo._web_url() (in guest.py) can
        # build the correct URL including scheme and port.
        guest.effective_port = port_override or detector.default_port

        # Get installed version via HTTP probe
        try:
            guest.installed_version = await detector.get_installed_version(
                guest.ip, port=port_override, api_key=api_key, scheme=scheme,
                http_client=self._http_client,
            )
            if guest.installed_version:
                guest.version_detection_method = "http"
        except Exception:
            logger.warning(
                "Version probe failed for %s on %s", detector.name, guest.name
            )

        # pct exec: try if enabled for this host, guest is LXC, and version cmd exists
        pct_exec_tried = False
        if (
            host_config
            and host_config.pct_exec_enabled
            and guest.type == "lxc"
            and ssh_version_cmd
        ):
            pct_exec_tried = True
            raw_vmid = guest.id.split(":")[-1] if ":" in guest.id else guest.id
            proxmox_ip = _extract_host_ip(host_config.host)
            if proxmox_ip:
                try:
                    pct_output = await self._ssh.run_pct_exec(
                        proxmox_ip,
                        raw_vmid,
                        ssh_version_cmd,
                        ssh_username=host_config.ssh_username,
                        ssh_key_path=host_config.ssh_key_path,
                        ssh_password=host_config.ssh_password,
                    )
                    if pct_output:
                        guest.installed_version = pct_output.strip().splitlines()[0]
                        guest.version_detection_method = "pct_exec"
                except Exception:
                    logger.warning(
                        "pct exec failed for %s on %s, will try SSH",
                        detector.name, guest.name,
                    )

        # SSH version command: try if pct exec did not succeed
        if ssh_version_cmd and guest.ip and guest.version_detection_method != "pct_exec":
            try:
                ssh_output = await self._ssh.execute_version_cmd(
                    guest.ip,
                    ssh_version_cmd,
                    username=ssh_username,
                    key_path=ssh_key_path,
                    password=ssh_password,
                )
                if ssh_output:
                    guest.installed_version = ssh_output.strip().splitlines()[0]
                    guest.version_detection_method = "ssh"
            except Exception:
                logger.warning(
                    "SSH version cmd failed for %s on %s",
                    detector.name,
                    guest.name,
                )

        # Get latest version: try detector's custom source first, then GitHub
        custom_latest = await detector.get_latest_version(http_client=self._http_client)
        if custom_latest:
            guest.latest_version = custom_latest
            guest.github_lookup_status = "success"
            logger.debug(
                "Latest version for %s from custom source: %s", detector.name, custom_latest
            )
        else:
            effective_repo = github_repo_override or detector.github_repo
            if effective_repo:
                guest.github_repo_queried = effective_repo
                try:
                    guest.latest_version = await self._github.get_latest_version(
                        effective_repo
                    )
                    guest.github_lookup_status = "success" if guest.latest_version else "failed"
                except Exception:
                    logger.warning(
                        "GitHub version lookup failed for %s", effective_repo
                    )
                    guest.github_lookup_status = "failed"
            else:
                guest.github_lookup_status = "no_repo"

        # Determine update status
        guest.update_status = _determine_update_status(
            guest.installed_version, guest.latest_version
        )

        # Append version fields to raw_detection_output for transparency
        if guest.raw_detection_output is not None:
            guest.raw_detection_output.update({
                "version_detection_method": guest.version_detection_method,
                "github_repo_queried": guest.github_repo_queried,
                "github_lookup_status": guest.github_lookup_status,
            })


def _extract_host_ip(host_url: str) -> str | None:
    """Extract hostname/IP from a Proxmox host URL.

    Handles formats like ``https://192.168.1.10:8006`` or bare ``192.168.1.10``.
    """
    if not host_url:
        return None
    if "://" in host_url:
        parsed = urlparse(host_url)
        return parsed.hostname
    # Bare hostname/IP, possibly with port
    return host_url.split(":")[0]


def _normalize_version_string(version: str) -> str:
    """Strip v prefix and build-hash suffixes (e.g. '1.40.0.7998-c29d4c0c8' -> '1.40.0.7998').

    Preserves legitimate pre-release suffixes like '1.0.0-beta.1'.
    Only strips suffixes that look like build hashes (7+ hex chars after a hyphen).
    """
    version = version.lstrip("v")
    # Only strip suffixes that look like build hashes (7+ hex chars)
    version = re.sub(r'-[0-9a-f]{7,}$', '', version)
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
