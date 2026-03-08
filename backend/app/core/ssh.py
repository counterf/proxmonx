"""SSH command executor with safety whitelist."""

import asyncio
import logging
import re
from pathlib import Path

import paramiko

from app.config import Settings

logger = logging.getLogger(__name__)

# Only these command prefixes are allowed over SSH
COMMAND_WHITELIST = frozenset({
    "docker ps",
    "docker inspect",
    "cat ",
    "which ",
    "dpkg -l",
    "rpm -q",
})

# Reject commands containing shell metacharacters to prevent injection.
# Covers: statement separators (;), logical ops (&& ||), pipes (|), command
# substitution (` $ ( )), brace expansion ({), redirects (< >), history (!),
# comments (#), newlines and backslash escapes.
SHELL_METACHARACTERS = re.compile(r'[;&|`$<>()\{\}!\n\\#]')


class SSHClient:
    """Execute read-only commands on Proxmox guests via SSH."""

    def __init__(self, settings: Settings) -> None:
        self._username = settings.ssh_username
        self._key_path = settings.ssh_key_path
        self._password = settings.ssh_password
        self._enabled = settings.ssh_enabled
        self._known_hosts_path = settings.ssh_known_hosts_path

    def _is_command_allowed(self, command: str) -> bool:
        """Check command against whitelist, rejecting shell metacharacters."""
        if SHELL_METACHARACTERS.search(command):
            logger.warning("Command contains shell metacharacters, refusing: %s", command)
            return False
        return any(command.startswith(prefix) for prefix in COMMAND_WHITELIST)

    async def execute(self, host: str, command: str, timeout: int = 10) -> str | None:
        """Execute a read-only command on a remote host.

        Returns stdout on success, None on failure.
        """
        if not self._enabled:
            logger.debug("SSH disabled, skipping command on %s", host)
            return None

        if not self._is_command_allowed(command):
            logger.warning("Command not in whitelist, refusing: %s", command)
            return None

        try:
            return await asyncio.to_thread(
                self._execute_sync, host, command, timeout
            )
        except Exception:
            logger.debug("SSH command failed on %s: %s", host, command)
            return None

    def _execute_sync(self, host: str, command: str, timeout: int) -> str | None:
        """Blocking SSH execution (run in thread)."""
        client = paramiko.SSHClient()
        if self._known_hosts_path and Path(self._known_hosts_path).is_file():
            client.load_host_keys(self._known_hosts_path)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            # WarningPolicy logs unknown host keys instead of silently accepting.
            # Set SSH_KNOWN_HOSTS_PATH for strict host key verification.
            client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            connect_kwargs: dict[str, str | int | Path | None] = {
                "hostname": host,
                "username": self._username,
                "timeout": timeout,
            }
            if self._key_path:
                connect_kwargs["key_filename"] = self._key_path
            elif self._password:
                connect_kwargs["password"] = self._password
            else:
                logger.debug("No SSH credentials configured")
                return None

            client.connect(**connect_kwargs)  # type: ignore[arg-type]
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            output = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if err:
                logger.debug("SSH stderr on %s: %s", host, err)
            return output if output else None
        except Exception:
            logger.debug("SSH connection failed to %s", host)
            return None
        finally:
            client.close()
