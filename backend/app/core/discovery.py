"""Guest discovery and app detection orchestrator."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import NamedTuple
from urllib.parse import urlparse

import httpx

from app.config import ProxmoxHostConfig, Settings  # Settings kept for DiscoveryEngine type hint
from app.core.github import GitHubClient
from app.core.proxmox import ProxmoxClient
from app.core.ssh import SSHClient, _extract_ssh_host
from app.detectors.base import BaseDetector
from app.detectors.registry import ALL_DETECTORS, DETECTOR_MAP, DOCKER_DETECTOR
from app.detectors.utils import normalize_version
from app.models.guest import GuestInfo, VersionCheck

logger = logging.getLogger(__name__)

# Limit concurrent probes to avoid overwhelming the network
MAX_CONCURRENT_PROBES = 10

# Maximum number of version history entries to retain per guest
MAX_VERSION_HISTORY = 10


class ResolvedConfig(NamedTuple):
    """Effective config for a guest after layered resolution.

    NOTE: NamedTuple is used instead of @dataclass(frozen=True, slots=True)
    because existing tests use positional destructuring (e.g. port, api_key, *_ = ...).
    Do not convert without updating those tests first.
    """

    port: int | None
    api_key: str | None
    scheme: str
    github_repo: str | None
    ssh_version_cmd: str | None
    ssh_username: str | None
    ssh_key_path: str | None
    ssh_password: str | None
    version_host: str | None


class DiscoveryEngine:
    """Orchestrates guest discovery, app detection, and version checking."""

    def __init__(
        self,
        github: GitHubClient,
        ssh: SSHClient,
        http_client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._github = github
        self._ssh = ssh
        self._http_client = http_client
        self._settings = settings
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

    async def run_full_cycle(
        self,
        existing_guests: dict[str, GuestInfo],
        is_manual: bool = False,
    ) -> dict[str, GuestInfo]:
        """Run a complete discovery + detection + version check cycle.

        Discovery runs against each configured host in parallel and the
        results are merged.  Guest IDs are namespaced as
        ``{host_id}:{vmid}`` to avoid collisions.
        """
        hosts = list(self._settings.proxmox_hosts) if self._settings else []

        if not hosts:
            logger.warning("No Proxmox hosts configured -- skipping discovery")
            return {}

        if len(hosts) == 1:
            return await self._run_host_cycle(hosts[0], existing_guests, is_manual=is_manual)

        logger.info("Starting multi-host discovery across %d hosts", len(hosts))
        start = datetime.now(timezone.utc)

        tasks = [
            self._run_host_cycle(host, existing_guests, is_manual=is_manual)
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

    async def _run_host_cycle(
        self,
        host_config: ProxmoxHostConfig,
        existing_guests: dict[str, GuestInfo],
        is_manual: bool = False,
    ) -> dict[str, GuestInfo]:
        """Run discovery for a single Proxmox host, namespacing guest IDs."""
        logger.info("Starting discovery for host %s (%s)", host_config.label, host_config.host)
        start = datetime.now(timezone.utc)

        host_client = httpx.AsyncClient(
            timeout=10.0,
            verify=False,
            follow_redirects=True,
        )
        updated: dict[str, GuestInfo] = {}
        try:
            proxmox = ProxmoxClient(
                host_config,
                discover_vms=self._settings.discover_vms if self._settings else False,
                http_client=host_client,
            )

            guests = await proxmox.list_guests()
            logger.info("Host %s: discovered %d guests", host_config.label, len(guests))

            for guest in guests:
                guest.id = f"{host_config.id}:{guest.id}"
                guest.host_id = host_config.id
                guest.host_label = host_config.label

            tasks = [
                self._process_guest(
                    guest,
                    existing_guests.get(guest.id),
                    host_config=host_config,
                    host_http_client=host_client,
                    is_manual=is_manual,
                )
                for guest in guests
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, GuestInfo):
                    updated[result.id] = result
                elif isinstance(result, Exception):
                    logger.error("Guest processing failed on host %s: %s", host_config.label, result)
        finally:
            await host_client.aclose()

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(
            "Host %s discovery complete: %d guests in %.1fs",
            host_config.label, len(updated), elapsed,
        )
        return updated

    async def _process_guest(
        self,
        guest: GuestInfo,
        previous: GuestInfo | None,
        host_config: ProxmoxHostConfig | None = None,
        host_http_client: httpx.AsyncClient | None = None,
        is_manual: bool = False,
    ) -> GuestInfo:
        """Process a single guest: resolve IP, detect app, check versions."""
        async with self._semaphore:
            try:
                # Resolve IP -- need the correct proxmox client for this host.
                # VMs always need the client (also used for disk usage via guest agent).
                raw_vmid = guest.id.split(":")[-1] if ":" in guest.id else guest.id
                proxmox: ProxmoxClient | None = None
                if not guest.ip or guest.type == "vm":
                    if host_config:
                        proxmox = ProxmoxClient(
                            host_config,
                            discover_vms=self._settings.discover_vms if self._settings else False,
                            http_client=host_http_client,
                        )
                    else:
                        proxmox = None

                if proxmox and not guest.ip:
                    guest.ip, guest.os_type = await proxmox.get_guest_network(
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

                # Fetch disk usage for VMs via guest agent (LXCs get it from the list endpoint)
                if proxmox and guest.type == "vm":
                    guest.disk_used, guest.disk_total = await proxmox.get_vm_disk_usage(raw_vmid)

                # Detect app
                await self._detect_app(guest, host_config=host_config)

                # Get installed version
                if guest.detector_used and guest.ip:
                    await self._check_version(guest, host_config=host_config, http_client=host_http_client)

                # Check pending OS package updates and reboot status (LXC only)
                if previous:
                    guest.pending_updates = previous.pending_updates
                    guest.pending_update_packages = previous.pending_update_packages
                    guest.reboot_required = previous.reboot_required
                    guest.pending_updates_checked_at = previous.pending_updates_checked_at
                if host_config:
                    await self._check_pending_updates(guest, host_config, previous=previous, is_manual=is_manual)

                # Check community-script presence (once per session; preserved if already known)
                if previous and previous.has_community_script is not None:
                    guest.has_community_script = previous.has_community_script
                elif host_config:
                    await self._check_community_script(guest, host_config)

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
        if self._settings and self._settings.guest_config:
            guest_cfg = self._settings.guest_config.get(guest.id)
            forced = guest_cfg.forced_detector if guest_cfg else None
            if forced and forced in DETECTOR_MAP:
                detector = DETECTOR_MAP[forced]
                guest.app_name = detector.display_name
                guest.detector_used = detector.name
                guest.detection_method = "manual"
                guest.raw_detection_output = {
                    "detector": detector.name,
                    "method": "manual",
                }
                logger.debug(
                    "Forced detector %s for guest %s (manual override)",
                    detector.name,
                    guest.name,
                )
                return

        # Pass 1: tag-only sweep — an explicit container tag always beats a name heuristic.
        # Iterates all detectors before name matching so a late-ordered detector
        # with a matching tag wins over an early-ordered detector with a name match.
        for detector in ALL_DETECTORS:
            for tag in guest.tags:
                key = tag.lower().removeprefix("app:")
                if key == detector.name or key in detector.aliases:
                    guest.app_name = detector.display_name
                    guest.detector_used = detector.name
                    guest.detection_method = "tag_match"
                    guest.raw_detection_output = {
                        "detector": detector.name,
                        "method": "tag_match",
                        "matched_tag": tag,
                        "matched_tags": ", ".join(guest.tags),
                    }
                    logger.debug("Tag match: %s on %s via tag %r", detector.name, guest.name, tag)
                    return

        # Pass 2: name matching
        for detector in ALL_DETECTORS:
            if detector._name_matches(guest.name):
                guest.app_name = detector.display_name
                guest.detector_used = detector.name
                guest.detection_method = "name_match"
                guest.raw_detection_output = {
                    "detector": detector.name,
                    "method": "name_match",
                    "matched_name": guest.name,
                    "matched_tags": ", ".join(guest.tags),
                }
                logger.debug("Name match: %s on %s", detector.name, guest.name)
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

        # Pass 1: scan all images for a known named detector match first.
        # This prevents a generic-parseable image (e.g. "python:3.12") that
        # appears before a known app image (e.g. "sonarr:4.0") from shadowing it.
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

        # Pass 2: no named detector matched — fall back to generic image tag parsing.
        for image in images:
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

    def _resolve_config(
        self, detector_name: str, guest_id: str,
    ) -> ResolvedConfig:
        """Resolve effective config: guest_config -> app_config -> defaults."""
        port: int | None = None
        api_key: str | None = None
        scheme: str = "http"
        github_repo: str | None = None
        ssh_cmd: str | None = None
        ssh_user: str | None = None
        ssh_key: str | None = None
        ssh_pass: str | None = None
        version_host: str | None = None

        # Layer 1: app-level defaults
        if self._settings and self._settings.app_config:
            app_cfg = self._settings.app_config.get(detector_name)
            if app_cfg:
                port = app_cfg.port
                api_key = app_cfg.api_key
                if app_cfg.scheme:
                    scheme = app_cfg.scheme
                github_repo = app_cfg.github_repo
                ssh_cmd = app_cfg.ssh_version_cmd
                ssh_user = app_cfg.ssh_username
                ssh_key = app_cfg.ssh_key_path
                ssh_pass = app_cfg.ssh_password

        # Layer 2: guest-level overrides (non-null fields win)
        if self._settings and self._settings.guest_config:
            guest_cfg = self._settings.guest_config.get(guest_id)
            if guest_cfg:
                if guest_cfg.port is not None:
                    port = guest_cfg.port
                if guest_cfg.api_key is not None:
                    api_key = guest_cfg.api_key
                if guest_cfg.scheme is not None:
                    scheme = guest_cfg.scheme
                if guest_cfg.github_repo is not None:
                    github_repo = guest_cfg.github_repo
                if guest_cfg.ssh_version_cmd is not None:
                    ssh_cmd = guest_cfg.ssh_version_cmd
                if guest_cfg.ssh_username is not None:
                    ssh_user = guest_cfg.ssh_username
                if guest_cfg.ssh_key_path is not None:
                    ssh_key = guest_cfg.ssh_key_path
                if guest_cfg.ssh_password is not None:
                    ssh_pass = guest_cfg.ssh_password
                if guest_cfg.version_host is not None:
                    version_host = guest_cfg.version_host

        logger.debug(
            "Resolved config for %s (guest %s): port=%s, api_key=%s, scheme=%s, version_host=%s",
            detector_name, guest_id,
            port or "default", "set" if api_key else "none", scheme, version_host or "none",
        )
        return ResolvedConfig(port, api_key, scheme, github_repo, ssh_cmd, ssh_user, ssh_key, ssh_pass, version_host)

    async def _check_pending_updates(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig,
        previous: GuestInfo | None = None,
        is_manual: bool = False,
    ) -> None:
        """Check pending OS package updates and reboot status for an LXC container.

        Only runs for running LXC containers with pct_exec_enabled and a known os_type.
        Respects the pending_updates_interval_seconds TTL for automatic cycles; manual
        refreshes always run the SSH check regardless of when it last ran.
        Updates guest.pending_updates, guest.pending_update_packages, guest.reboot_required in place.
        Both checks run in parallel to reduce SSH round-trips.
        """
        if guest.type != "lxc" or guest.status != "running":
            return
        if not guest.os_type or not host_config.pct_exec_enabled:
            return

        # TTL guard: skip SSH check if within the configured interval (automatic cycles only)
        ttl = (self._settings.pending_updates_interval_seconds
               if self._settings else 3600)
        if (
            not is_manual
            and previous
            and previous.pending_updates_checked_at is not None
            and (datetime.now(timezone.utc) - previous.pending_updates_checked_at).total_seconds() < ttl
        ):
            # Cached values already copied by _process_guest — nothing to do
            return

        vmid = guest.id.rsplit(":", 1)[-1]
        ssh_host = _extract_ssh_host(host_config.host)
        ssh_kwargs = dict(
            proxmox_host=ssh_host,
            vmid=vmid,
            ssh_username=host_config.ssh_username,
            ssh_key_path=host_config.ssh_key_path,
            ssh_password=host_config.ssh_password,
        )

        packages, reboot = await asyncio.gather(
            self._ssh.run_pending_updates_list(os_type=guest.os_type, **ssh_kwargs),
            self._ssh.run_reboot_required_check(**ssh_kwargs),
        )

        if packages is not None:
            guest.pending_update_packages = packages
            guest.pending_updates = len(packages)
        if reboot is not None:
            guest.reboot_required = reboot
        # Only record freshness when the primary probe succeeded.
        # If SSH was unreachable (packages is None), leave the timestamp unset
        # so the next cycle retries rather than serving stale counts for the full TTL.
        if packages is not None:
            guest.pending_updates_checked_at = datetime.now(timezone.utc)

    async def _check_community_script(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig,
    ) -> None:
        """Check whether /usr/bin/update exists inside an LXC container.

        Only runs for running LXCs with pct_exec_enabled. Sets guest.has_community_script.
        """
        if guest.type != "lxc" or guest.status != "running":
            return
        if not host_config.pct_exec_enabled:
            return

        vmid = guest.id.rsplit(":", 1)[-1]
        result = await self._ssh.run_community_script_check(
            proxmox_host=host_config.host,
            vmid=vmid,
            ssh_username=host_config.ssh_username,
            ssh_key_path=host_config.ssh_key_path,
            ssh_password=host_config.ssh_password,
        )
        if result is not None:
            guest.has_community_script = result

    async def _check_version(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Check installed and latest versions for a detected app."""
        from app.detectors.registry import DETECTOR_MAP

        detector: BaseDetector | None = DETECTOR_MAP.get(guest.detector_used or "")
        if not detector or not guest.ip:
            return

        # Resolve config: guest-level -> app-level -> detector defaults
        cfg = self._resolve_config(detector.name, guest.id)

        # Store the effective port and scheme so GuestInfo._web_url() (in guest.py)
        # can build the correct URL.
        guest.effective_port = cfg.port or detector.default_port
        guest.scheme = cfg.scheme

        # Determine version detection strategy
        detect_method = "pct_first"
        if self._settings:
            method = self._settings.version_detect_method
            if method in ("pct_first", "ssh_first", "ssh_only", "pct_only"):
                detect_method = method
            elif method:
                logger.warning("Invalid version_detect_method '%s', using pct_first", method)

        # HTTP probe always runs first regardless of method (it's the primary source)
        from app.detectors.http_json import ProbeError

        probe_host = cfg.version_host or guest.ip
        guest.version_host = cfg.version_host or None
        effective_port = cfg.port or detector.default_port
        probe_path = getattr(detector, '_path', '')
        guest.probe_url = f"{cfg.scheme}://{probe_host}:{effective_port}{probe_path}"
        guest.probe_error = None
        # Track TrueNAS latest version from the same probe (avoids race on singleton)
        _truenas_latest: str | None = None
        try:
            result = await detector.get_installed_version(
                probe_host, port=cfg.port, api_key=cfg.api_key, scheme=cfg.scheme,
                http_client=http_client or self._http_client,
            )
            # TrueNAS returns (installed, latest) tuple; others return str|None
            if isinstance(result, tuple):
                guest.installed_version, _truenas_latest = result
            else:
                guest.installed_version = result
            if guest.installed_version:
                guest.version_detection_method = "http"
        except ProbeError as exc:
            guest.probe_error = str(exc)
            logger.warning(
                "Version probe failed for %s on %s: %s", detector.name, guest.name, exc
            )
        except Exception:
            guest.probe_error = "Unexpected error during version probe"
            logger.warning(
                "Version probe failed for %s on %s", detector.name, guest.name
            )

        # CLI fallback: only attempt if API probe did not obtain a version
        if not guest.installed_version and cfg.ssh_version_cmd:
            if detect_method == "pct_first":
                await self._try_pct_then_ssh(
                    guest, host_config, cfg.ssh_version_cmd,
                    cfg.ssh_username, cfg.ssh_key_path, cfg.ssh_password,
                )
            elif detect_method == "ssh_first":
                await self._try_ssh_then_pct(
                    guest, host_config, cfg.ssh_version_cmd,
                    cfg.ssh_username, cfg.ssh_key_path, cfg.ssh_password,
                )
            elif detect_method == "pct_only":
                await self._try_pct_exec(
                    guest, host_config, cfg.ssh_version_cmd,
                )
            elif detect_method == "ssh_only":
                await self._try_ssh(
                    guest, cfg.ssh_version_cmd,
                    cfg.ssh_username, cfg.ssh_key_path, cfg.ssh_password,
                )

        # Get latest version: use TrueNAS probe result if available, then custom, then GitHub
        custom_latest = _truenas_latest or await detector.get_latest_version(http_client=http_client or self._http_client)
        if custom_latest:
            guest.latest_version = custom_latest
            guest.latest_version_source = "custom"
            guest.github_lookup_status = "success"
            logger.debug(
                "Latest version for %s from custom source: %s", detector.name, custom_latest
            )
        else:
            effective_repo = cfg.github_repo or detector.github_repo
            if effective_repo:
                guest.github_repo_queried = effective_repo
                guest.latest_version_source = "github"
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
                "latest_version_source": guest.latest_version_source,
            })


    async def _try_pct_exec(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig | None,
        ssh_version_cmd: str,
    ) -> bool:
        """Attempt pct exec; return True if version was obtained."""
        if (
            not host_config
            or not host_config.pct_exec_enabled
            or guest.type != "lxc"
        ):
            return False
        raw_vmid = guest.id.split(":")[-1] if ":" in guest.id else guest.id
        proxmox_ip = _extract_host_ip(host_config.host)
        if not proxmox_ip:
            return False
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
                return True
        except Exception:
            logger.warning(
                "pct exec failed for %s on %s",
                guest.detector_used, guest.name,
            )
        return False

    async def _try_ssh(
        self,
        guest: GuestInfo,
        ssh_version_cmd: str,
        ssh_username: str | None,
        ssh_key_path: str | None,
        ssh_password: str | None,
    ) -> bool:
        """Attempt SSH version command; return True if version was obtained."""
        if not guest.ip:
            return False
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
                return True
        except Exception:
            logger.warning(
                "SSH version cmd failed for %s on %s",
                guest.detector_used, guest.name,
            )
        return False

    async def _try_pct_then_ssh(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig | None,
        ssh_version_cmd: str,
        ssh_username: str | None,
        ssh_key_path: str | None,
        ssh_password: str | None,
    ) -> None:
        """Try pct exec first, fall back to SSH."""
        if not await self._try_pct_exec(guest, host_config, ssh_version_cmd):
            await self._try_ssh(guest, ssh_version_cmd, ssh_username, ssh_key_path, ssh_password)

    async def _try_ssh_then_pct(
        self,
        guest: GuestInfo,
        host_config: ProxmoxHostConfig | None,
        ssh_version_cmd: str,
        ssh_username: str | None,
        ssh_key_path: str | None,
        ssh_password: str | None,
    ) -> None:
        """Try SSH first, fall back to pct exec."""
        if not await self._try_ssh(guest, ssh_version_cmd, ssh_username, ssh_key_path, ssh_password):
            await self._try_pct_exec(guest, host_config, ssh_version_cmd)


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


def _determine_update_status(
    installed: str | None, latest: str | None
) -> str:
    """Compare installed vs latest version, handling build-hash suffixes."""
    if not installed or not latest:
        return "unknown"

    from packaging.version import Version, InvalidVersion

    norm_installed = normalize_version(installed, strip_v=True)
    norm_latest = normalize_version(latest, strip_v=True)

    try:
        return "up-to-date" if Version(norm_installed) >= Version(norm_latest) else "outdated"
    except InvalidVersion:
        # Fall back to normalized string equality
        return "up-to-date" if norm_installed == norm_latest else "outdated"
