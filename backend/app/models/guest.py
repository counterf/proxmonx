"""Pydantic v2 models for guest data."""

from __future__ import annotations

import ipaddress as _ipaddress
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


def _is_valid_ip(ip: str) -> bool:
    """Validate an IP address using the stdlib ``ipaddress`` module."""
    try:
        _ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def _format_host(ip: str) -> str:
    """Return *ip* formatted for use in a URL.

    IPv6 addresses are wrapped in brackets (RFC 2732).
    """
    addr = _ipaddress.ip_address(ip)
    if isinstance(addr, _ipaddress.IPv6Address):
        return f"[{ip}]"
    return ip


def _build_web_url(
    ip: str | None,
    app_name: str | None,
    status: str,
    detector_used: str | None,
    effective_port: int | None,
    scheme: str = "http",
) -> str | None:
    """Construct web URL from guest IP and detected port.

    Returns None when IP is missing, no app detected, or guest is stopped.

    The *scheme* parameter defaults to ``"http"``.  Callers (detectors) may
    override it to ``"https"`` when they know the service uses TLS.  Note that
    the correct scheme **cannot** be reliably inferred from the port number
    alone -- only port 443 is assumed ``https`` by default.
    """
    if not ip or not app_name or status != "running":
        return None
    if not _is_valid_ip(ip):
        return None
    if effective_port is None:
        return None

    host = _format_host(ip)

    # Port 443 always implies https regardless of how the port was set.
    if effective_port == 443:
        return f"https://{host}"
    if effective_port == 80 and scheme == "http":
        return f"http://{host}"

    return f"{scheme}://{host}:{effective_port}"


class VersionCheck(BaseModel):
    """A single version check record."""

    timestamp: datetime
    installed_version: str | None = None
    latest_version: str | None = None
    update_status: Literal["up-to-date", "outdated", "unknown"] = "unknown"


class GuestSummary(BaseModel):
    """Summary view of a Proxmox guest for the dashboard table."""

    id: str
    name: str
    type: Literal["lxc", "vm"]
    status: Literal["running", "stopped"]
    app_name: str | None = None
    installed_version: str | None = None
    latest_version: str | None = None
    update_status: Literal["up-to-date", "outdated", "unknown"] = "unknown"
    last_checked: datetime | None = None
    tags: list[str] = []
    web_url: str | None = None
    host_id: str = "default"
    host_label: str = "Default"
    detection_method: str | None = None
    version_detection_method: str | None = None
    github_repo_queried: str | None = None
    github_lookup_status: str | None = None
    latest_version_source: str | None = None
    disk_used: int | None = None
    disk_total: int | None = None
    os_type: str | None = None


class GuestDetail(GuestSummary):
    """Full detail view of a Proxmox guest."""

    ip: str | None = None
    detector_used: str | None = None
    raw_detection_output: dict[str, str | int | float | bool | None] | None = None
    version_history: list[VersionCheck] = []


class GuestInfo(BaseModel):
    """Internal representation of a discovered guest with all metadata."""

    id: str
    name: str
    type: Literal["lxc", "vm"]
    status: Literal["running", "stopped"]
    ip: str | None = None
    tags: list[str] = []
    app_name: str | None = None
    installed_version: str | None = None
    latest_version: str | None = None
    update_status: Literal["up-to-date", "outdated", "unknown"] = "unknown"
    last_checked: datetime | None = None
    detection_method: str | None = None
    detector_used: str | None = None
    raw_detection_output: dict[str, str | int | float | bool | None] | None = None
    version_history: list[VersionCheck] = []
    # Effective port used during detection (detector default or user override)
    effective_port: int | None = None
    # URL scheme for the web interface.  Defaults to "http"; detectors may set
    # "https" when they know the service uses TLS.  The scheme cannot be
    # reliably inferred from the port number alone.
    scheme: str = "http"
    # Multi-host support
    host_id: str = "default"
    host_label: str = "Default"
    # How the installed version was obtained: "http", "ssh", "pct_exec", or None
    version_detection_method: str | None = None
    # The owner/repo string actually used for the GitHub lookup
    github_repo_queried: str | None = None
    # Outcome of the GitHub lookup: "success", "failed", or "no_repo"
    github_lookup_status: str | None = None
    # Where the latest version came from: "github", "custom", or None
    latest_version_source: str | None = None
    # Disk usage reported by Proxmox (bytes); None when unavailable
    disk_used: int | None = None
    disk_total: int | None = None
    # OS type from Proxmox config (e.g. "debian", "alpine", "ubuntu")
    os_type: str | None = None

    def _web_url(self) -> str | None:
        return _build_web_url(
            self.ip, self.app_name, self.status,
            self.detector_used, self.effective_port,
            self.scheme,
        )

    def to_summary(self) -> GuestSummary:
        return GuestSummary(
            id=self.id,
            name=self.name,
            type=self.type,
            status=self.status,
            app_name=self.app_name,
            installed_version=self.installed_version,
            latest_version=self.latest_version,
            update_status=self.update_status,
            last_checked=self.last_checked,
            tags=self.tags,
            web_url=self._web_url(),
            host_id=self.host_id,
            host_label=self.host_label,
            detection_method=self.detection_method,
            version_detection_method=self.version_detection_method,
            github_repo_queried=self.github_repo_queried,
            github_lookup_status=self.github_lookup_status,
            latest_version_source=self.latest_version_source,
            disk_used=self.disk_used,
            disk_total=self.disk_total,
            os_type=self.os_type,
        )

    def to_detail(self) -> GuestDetail:
        return GuestDetail(
            id=self.id,
            name=self.name,
            type=self.type,
            status=self.status,
            app_name=self.app_name,
            installed_version=self.installed_version,
            latest_version=self.latest_version,
            update_status=self.update_status,
            last_checked=self.last_checked,
            tags=self.tags,
            ip=self.ip,
            detection_method=self.detection_method,
            detector_used=self.detector_used,
            raw_detection_output=self.raw_detection_output,
            version_history=self.version_history,
            web_url=self._web_url(),
            host_id=self.host_id,
            host_label=self.host_label,
            version_detection_method=self.version_detection_method,
            github_repo_queried=self.github_repo_queried,
            github_lookup_status=self.github_lookup_status,
            latest_version_source=self.latest_version_source,
            disk_used=self.disk_used,
            disk_total=self.disk_total,
            os_type=self.os_type,
        )
