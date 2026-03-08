"""Pydantic v2 models for guest data."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
        )
