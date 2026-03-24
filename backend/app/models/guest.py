"""Pydantic v2 models for guest data."""

from __future__ import annotations

import ipaddress as _ipaddress
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field


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
    version_host: str | None = None,
) -> str | None:
    """Construct web URL from guest IP (or version_host override) and detected port.

    Returns None when IP is missing, no app detected, or guest is stopped.
    """
    if not app_name or status != "running":
        return None
    if effective_port is None:
        return None

    if version_host:
        host = version_host
    elif ip and _is_valid_ip(ip):
        host = _format_host(ip)
    else:
        return None

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


class GuestInfo(BaseModel):
    """Representation of a discovered Proxmox guest with all metadata."""

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
    effective_port: int | None = None
    scheme: str = "http"
    host_id: str = "default"
    host_label: str = "Default"
    version_detection_method: str | None = None
    github_repo_queried: str | None = None
    github_lookup_status: str | None = None
    latest_version_source: str | None = None
    disk_used: int | None = None
    disk_total: int | None = None
    os_type: str | None = None
    probe_url: str | None = None
    probe_error: str | None = None
    version_host: str | None = None  # override hostname/IP used for version probe and web URL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def web_url(self) -> str | None:
        return _build_web_url(
            self.ip, self.app_name, self.status,
            self.detector_used, self.effective_port,
            self.scheme, self.version_host,
        )
