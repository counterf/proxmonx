"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings configurable via environment variables."""

    # Proxmox connection (required)
    proxmox_host: str
    proxmox_token_id: str
    proxmox_token_secret: str
    proxmox_node: str

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

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://frontend"]

    # Application
    log_level: str = "info"
    proxmon_enabled: bool = True
    ssh_enabled: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def masked_token_id(self) -> str:
        """Return token ID with secret portion masked."""
        parts = self.proxmox_token_id.split("!")
        if len(parts) == 2:
            return f"{parts[0]}!****"
        return "****"

    def masked_settings(self) -> dict[str, str | int | bool | None]:
        """Return settings dict with secrets masked."""
        return {
            "proxmox_host": self.proxmox_host,
            "proxmox_token_id": self.masked_token_id(),
            "proxmox_node": self.proxmox_node,
            "poll_interval_seconds": self.poll_interval_seconds,
            "discover_vms": self.discover_vms,
            "verify_ssl": self.verify_ssl,
            "ssh_username": self.ssh_username,
            "ssh_enabled": self.ssh_enabled,
            "github_token_set": self.github_token is not None,
            "log_level": self.log_level,
            "proxmon_enabled": self.proxmon_enabled,
        }
