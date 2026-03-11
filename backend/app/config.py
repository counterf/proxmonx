"""Application configuration via environment variables and config file."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

VersionDetectMethod = Literal["pct_first", "ssh_first", "ssh_only", "pct_only"]


class AppConfig(BaseModel):
    """Per-app configuration override (port and/or API key)."""

    port: int | None = None
    api_key: str | None = None
    scheme: str | None = None
    github_repo: str | None = None
    ssh_version_cmd: str | None = None
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None


class ProxmoxHostConfig(BaseModel):
    """Configuration for a single Proxmox host."""

    id: str  # unique identifier, e.g. "pve1"
    label: str  # display name
    host: str  # URL, e.g. "https://192.168.1.10:8006"
    token_id: str = ""
    token_secret: str = ""
    node: str = ""
    verify_ssl: bool = False
    ssh_username: str = "root"
    ssh_password: str | None = None
    ssh_key_path: str | None = None
    pct_exec_enabled: bool = False


class Settings(BaseSettings):
    """All settings configurable via environment variables or config file."""

    # Proxmox connection -- legacy flat fields (kept for backward compat)
    proxmox_host: str | None = None
    proxmox_token_id: str | None = None
    proxmox_token_secret: str | None = None
    proxmox_node: str | None = None

    # Multi-host configuration
    proxmox_hosts: list[ProxmoxHostConfig] = []

    # Discovery
    poll_interval_seconds: int = 300
    discover_vms: bool = False
    verify_ssl: bool = False

    # SSH
    ssh_username: str = "root"
    ssh_key_path: str | None = None
    ssh_password: str | None = None

    # GitHub
    github_token: str | None = None

    # SSH host key verification
    ssh_known_hosts_path: str = ""

    # Version detection strategy
    version_detect_method: VersionDetectMethod = "pct_first"

    @field_validator("version_detect_method", mode="before")
    @classmethod
    def coerce_detect_method(cls, v: str) -> str:
        allowed = {"pct_first", "ssh_first", "ssh_only", "pct_only"}
        if v not in allowed:
            return "pct_first"
        return v

    # Application
    log_level: str = "info"
    proxmon_enabled: bool = True
    ssh_enabled: bool = True

    # Config file path
    config_db_path: str = "/app/data/proxmon.db"

    # Per-app overrides (port and API key)
    app_config: dict[str, AppConfig] = {}

    # Per-guest overrides keyed by guest ID (e.g. "1773123726644:100")
    guest_config: dict[str, AppConfig] = {}

    # Notifications
    notifications_enabled: bool = False
    ntfy_url: str = ""
    ntfy_token: str = ""
    ntfy_priority: int = 3
    notify_disk_threshold: int = 95
    notify_disk_cooldown_minutes: int = 60
    notify_on_outdated: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_hosts(self) -> list[ProxmoxHostConfig]:
        """Return the list of configured hosts.

        If ``proxmox_hosts`` is populated, return it directly.
        Otherwise fall back to the legacy flat fields and wrap them
        in a single-entry list for backward compatibility.
        """
        if self.proxmox_hosts:
            return list(self.proxmox_hosts)
        # Fallback: legacy flat fields
        if self.proxmox_host and self.proxmox_token_id:
            return [
                ProxmoxHostConfig(
                    id="default",
                    label="Default",
                    host=self.proxmox_host,
                    token_id=self.proxmox_token_id,
                    token_secret=self.proxmox_token_secret or "",
                    node=self.proxmox_node or "",
                    verify_ssl=self.verify_ssl,
                    ssh_username=self.ssh_username,
                    ssh_password=self.ssh_password or "",
                    ssh_key_path=self.ssh_key_path or "",
                )
            ]
        return []

    def masked_token_id(self) -> str:
        """Return token ID with secret portion masked."""
        if not self.proxmox_token_id:
            return ""
        parts = self.proxmox_token_id.split("!")
        if len(parts) == 2:
            return f"{parts[0]}!****"
        return "****"

    def masked_settings(self) -> dict[str, str | int | bool | None]:
        """Return settings dict with secrets masked."""
        return {
            "proxmox_host": self.proxmox_host or "",
            "proxmox_token_id": self.masked_token_id(),
            "proxmox_node": self.proxmox_node or "",
            "poll_interval_seconds": self.poll_interval_seconds,
            "discover_vms": self.discover_vms,
            "verify_ssl": self.verify_ssl,
            "ssh_username": self.ssh_username,
            "ssh_enabled": self.ssh_enabled,
            "github_token_set": self.github_token is not None,
            "log_level": self.log_level,
            "proxmon_enabled": self.proxmon_enabled,
        }
