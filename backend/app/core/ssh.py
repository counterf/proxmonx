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

# For user-configured version commands: reject dangerous injection patterns.
# Bare pipes are allowed only when the next token is a safe filter command.
_VERSION_CMD_DANGEROUS = re.compile(r'[;`]|\$\(|&&|\|\|')

# Commands allowed after a pipe in version commands.
_PIPE_SAFE_COMMANDS = frozenset({'awk', 'grep', 'cut', 'head', 'tail', 'sed', 'tr', 'xargs'})


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
        Newlines and null bytes are rejected.

        Pipes (|) are allowed only when every segment after the first
        starts with a safe filter command (awk, grep, cut, head, tail,
        sed, tr, xargs).
        """
        if not command or not command.strip():
            return False
        if len(command) > 512:
            return False
        if '\n' in command or '\0' in command:
            return False
        if _VERSION_CMD_DANGEROUS.search(command):
            return False
        # Validate pipe segments
        segments = command.split('|')
        for segment in segments[1:]:
            first_token = segment.strip().split()[0] if segment.strip() else ''
            if first_token not in _PIPE_SAFE_COMMANDS:
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
            out, err = await asyncio.to_thread(
                self._execute_sync, host, command, timeout
            )
            if err:
                logger.debug("SSH stderr on %s: %s", host, err)
            return out or None
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
            out, err = await asyncio.to_thread(
                self._execute_sync,
                host,
                command,
                timeout,
                username=username,
                key_path=key_path,
                password=password,
            )
            if out:
                logger.info("SSH version cmd on %s returned: %s", host, out[:80])
            else:
                logger.warning(
                    "SSH version cmd on %s returned empty output for: %.80s",
                    host, command,
                )
            return out or None
        except Exception:
            logger.warning("SSH version cmd failed on %s: %.80s", host, command)
            return None

    async def run_pct_exec(
        self,
        proxmox_host: str,
        vmid: str,
        cmd: str,
        ssh_username: str | None = None,
        ssh_key_path: str | None = None,
        ssh_password: str | None = None,
        timeout: int = 15,
    ) -> str | None:
        """Run ``pct exec <vmid> -- <cmd>`` on the Proxmox host via SSH.

        Returns stdout on success, None on failure.
        """
        if not self._enabled:
            logger.debug("SSH disabled, skipping pct exec on %s", proxmox_host)
            return None

        # Validate vmid is digits only
        if not vmid.isdigit():
            logger.warning("pct exec rejected: vmid %r is not numeric", vmid)
            return None

        # Validate the version command with the same safety check
        if not self._is_version_cmd_safe(cmd):
            logger.warning("pct exec rejected unsafe cmd for vmid %s: %.80s", vmid, cmd)
            return None

        pct_command = f"pct exec {vmid} -- {cmd}"
        logger.info("pct exec on %s: %s", proxmox_host, pct_command)

        try:
            stdout, stderr = await asyncio.to_thread(
                self._execute_sync,
                proxmox_host,
                pct_command,
                timeout,
                username=ssh_username,
                key_path=ssh_key_path,
                password=ssh_password,
            )
            if stdout:
                logger.info("pct exec on %s vmid %s stdout: %s", proxmox_host, vmid, stdout[:200])
            else:
                logger.warning(
                    "pct exec on %s vmid %s returned empty stdout (stderr: %s)",
                    proxmox_host, vmid, stderr[:200] if stderr else "(none)",
                )
            return stdout or None
        except Exception as exc:
            logger.warning("pct exec failed on %s vmid %s: %s", proxmox_host, vmid, exc)
            return None

    def _execute_sync(
        self,
        host: str,
        command: str,
        timeout: int,
        username: str | None = None,
        key_path: str | None = None,
        password: str | None = None,
    ) -> tuple[str, str]:
        """Blocking SSH execution (run in thread). Returns (stdout, stderr)."""
        effective_username = username or self._username
        effective_key_path = key_path or self._key_path
        effective_password = password or self._password

        client = paramiko.SSHClient()
        if self._known_hosts_path and Path(self._known_hosts_path).is_file():
            client.load_host_keys(self._known_hosts_path)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
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
                return "", "no credentials configured"

            client.connect(**connect_kwargs)  # type: ignore[arg-type]
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return out, err
        except Exception as exc:
            return "", str(exc)
        finally:
            client.close()
