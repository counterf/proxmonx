"""Application configuration via environment variables and config file."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings


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


class Settings(BaseSettings):
    """All settings configurable via environment variables or config file."""

    # Proxmox connection (optional so app can start unconfigured)
    proxmox_host: str | None = None
    proxmox_token_id: str | None = None
    proxmox_token_secret: str | None = None
    proxmox_node: str | None = None

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

    # Application
    log_level: str = "info"
    proxmon_enabled: bool = True
    ssh_enabled: bool = True

    # Config file path
    config_db_path: str = "/app/data/proxmon.db"

    # Per-app overrides (port and API key)
    app_config: dict[str, AppConfig] = {}

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

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
