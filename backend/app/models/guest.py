"""Pydantic v2 models for guest data."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# Strict IPv4/IPv6 pattern to prevent injection in constructed URLs
_IP_RE = re.compile(
    r"^(?:\d{1,3}\.){3}\d{1,3}$"  # IPv4
    r"|^[0-9a-fA-F:]+$"  # IPv6 (simplified)
)


def _build_web_url(
    ip: str | None,
    app_name: str | None,
    status: str,
    detector_used: str | None,
    effective_port: int | None,
) -> str | None:
    """Construct web URL from guest IP and detected port.

    Returns None when IP is missing, no app detected, or guest is stopped.
    """
    if not ip or not app_name or status != "running":
        return None
    if not _IP_RE.match(ip):
        return None
    if effective_port is None:
        return None
    if effective_port in (80,):
        return f"http://{ip}"
    if effective_port in (443,):
        return f"https://{ip}"
    return f"http://{ip}:{effective_port}"


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


class GuestDetail(GuestSummary):
    """Full detail view of a Proxmox guest."""

    ip: str | None = None
    detection_method: str | None = None
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

    def _web_url(self) -> str | None:
        return _build_web_url(
            self.ip, self.app_name, self.status,
            self.detector_used, self.effective_port,
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
        )
