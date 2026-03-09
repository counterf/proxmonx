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
# substitution (` $ ( )), redirects (< >), history (!), comments (#),
# newlines and backslash escapes.  Braces {} are intentionally excluded
# because Docker --format uses Go templates (e.g. {{.Image}}) and the
# command whitelist already prevents execution of arbitrary commands.
SHELL_METACHARACTERS = re.compile(r'[;&|`$<>()!\n\\#]')

# For user-configured version commands: only reject the most dangerous
# injection patterns.  Pipes (|) are allowed for e.g. "myapp --version | head -1".
_VERSION_CMD_DANGEROUS = re.compile(r';|`|\$\(|&&|\|\|')


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

    @staticmethod
    def _is_version_cmd_safe(command: str) -> bool:
        """Validate a user-configured version command.

        Rejects empty commands, commands over 512 chars, and commands
        containing dangerous injection patterns (;  `  $()  &&  ||).
        Pipes (|) are allowed.  Newlines and null bytes are rejected.
        """
        if not command or not command.strip():
            return False
        if len(command) > 512:
            return False
        if '\n' in command or '\0' in command:
            return False
        if _VERSION_CMD_DANGEROUS.search(command):
            return False
        return True

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

    async def execute_version_cmd(
        self,
        host: str,
        command: str,
        username: str | None = None,
        key_path: str | None = None,
        password: str | None = None,
        timeout: int = 10,
    ) -> str | None:
        """Execute a user-configured version command on a remote host.

        Bypasses COMMAND_WHITELIST (user-configured, trusted input) but
        still validates against dangerous injection metacharacters.
        """
        if not self._enabled:
            logger.debug("SSH disabled, skipping version cmd on %s", host)
            return None

        if not self._is_version_cmd_safe(command):
            logger.warning(
                "SSH version cmd rejected for %s: %.80s", host, command
            )
            return None

        effective_username = username or self._username
        effective_key_path = key_path or self._key_path
        effective_password = password or self._password
        if not effective_key_path and not effective_password:
            logger.warning(
                "SSH version cmd skipped for %s: no credentials configured "
                "(set SSH key/password in global Settings or per-app SSH fields)",
                host,
            )
            return None

        try:
            return await asyncio.to_thread(
                self._execute_sync,
                host,
                command,
                timeout,
                username=username,
                key_path=key_path,
                password=password,
            )
        except Exception:
            logger.warning("SSH version cmd failed on %s: %.80s", host, command)
            return None

    def _execute_sync(
        self,
        host: str,
        command: str,
        timeout: int,
        username: str | None = None,
        key_path: str | None = None,
        password: str | None = None,
    ) -> str | None:
        """Blocking SSH execution (run in thread).

        Optional credential overrides take priority over instance defaults.
        """
        effective_username = username or self._username
        effective_key_path = key_path or self._key_path
        effective_password = password or self._password

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
                "username": effective_username,
                "timeout": timeout,
            }
            if effective_key_path:
                connect_kwargs["key_filename"] = effective_key_path
            elif effective_password:
                connect_kwargs["password"] = effective_password
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
