"""Application configuration via SQLite config store and defaults."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

VersionDetectMethod = Literal["pct_first", "ssh_first", "ssh_only", "pct_only"]

_CUSTOM_APP_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


class CustomAppDef(BaseModel):
    """User-defined app definition for version monitoring."""

    name: str
    display_name: str
    default_port: int
    scheme: Literal["http", "https"] = "http"
    version_path: str | None = None
    github_repo: str | None = None
    aliases: list[str] = []
    docker_images: list[str] = []
    accepts_api_key: bool = False
    auth_header: str | None = None
    version_keys: list[str] = ["version"]
    strip_v: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _CUSTOM_APP_NAME_RE.match(v):
            raise ValueError(
                "name must be 2-32 lowercase alphanumeric characters or hyphens, "
                "starting with a letter"
            )
        return v

    @field_validator("default_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("default_port must be between 1 and 65535")
        return v


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
    forced_detector: str | None = None  # guest config only: override auto-detection
    version_host: str | None = None  # guest config only: override IP/hostname for version probe


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
    backup_storage: str | None = None  # Proxmox storage ID for vzdump backups


class Settings(BaseSettings):
    """All settings configurable via SQLite config store (UI/wizard)."""

    # Proxmox connection (flat fields used by save endpoint and ProxmoxClient)
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
    ssh_enabled: bool = True

    # Config file path
    config_db_path: str = "/app/data/proxmon.db"

    # Per-app overrides (port and API key)
    app_config: dict[str, AppConfig] = {}

    # Per-guest overrides keyed by guest ID (e.g. "1773123726644:100")
    guest_config: dict[str, AppConfig] = {}

    # Custom app definitions (user-defined detectors)
    custom_app_defs: list[CustomAppDef] = []

    # Authentication
    auth_mode: str = "disabled"  # "disabled" | "forms"
    auth_username: str = "root"
    # auth_password_hash is stored in the DB JSON blob only — never on Settings,
    # to prevent accidental serialization of the hash.

    # Notifications
    notifications_enabled: bool = False
    ntfy_url: str = ""
    ntfy_token: str = ""
    ntfy_priority: int = 3
    notify_disk_threshold: int = 95
    notify_disk_cooldown_minutes: int = 60
    notify_on_outdated: bool = True

    # API key for protecting mutating endpoints
    proxmon_api_key: str | None = None

    # Trust X-Forwarded-* headers from reverse proxies
    trust_proxy_headers: bool = False

    def get_hosts(self) -> list[ProxmoxHostConfig]:
        """Return the list of configured Proxmox hosts."""
        return list(self.proxmox_hosts)

