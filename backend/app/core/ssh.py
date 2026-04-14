"""SSH command executor with safety whitelist."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import paramiko

from app.config import Settings

# Hardcoded OS update commands by Proxmox ostype value.
# Keys match the ostype field from `pct config` / Proxmox API.
OS_UPDATE_COMMANDS: dict[str, str] = {
    "alpine":    "apk -U upgrade",
    "debian":    "DEBIAN_FRONTEND=noninteractive apt-get -qq update && DEBIAN_FRONTEND=noninteractive apt-get -yq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold dist-upgrade",
    "ubuntu":    "DEBIAN_FRONTEND=noninteractive apt-get -qq update && DEBIAN_FRONTEND=noninteractive apt-get -yq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold dist-upgrade",
    "devuan":    "DEBIAN_FRONTEND=noninteractive apt-get -qq update && DEBIAN_FRONTEND=noninteractive apt-get -yq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold dist-upgrade",
    "fedora":    "dnf -y update",
    "centos":    "dnf -y update",
    "archlinux": "pacman -Syyu --noconfirm",
    "opensuse":  "zypper ref && zypper --non-interactive dup",
}

# Commands that refresh the package index then list pending upgrades (one package name per line).
# apt/apk/zypper entries perform a quiet network refresh first; dnf and pacman read local cache only.
# If the refresh fails the list command is skipped (&&), so callers receive None rather than stale data.
OS_PENDING_UPDATES_LIST_COMMANDS: dict[str, str] = {
    "alpine":    "apk update -q 2>/dev/null && apk list --upgradable 2>/dev/null | grep upgradable | cut -d' ' -f1",
    "debian":    "apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null | grep upgradable | cut -d/ -f1",
    "ubuntu":    "apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null | grep upgradable | cut -d/ -f1",
    "devuan":    "apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null | grep upgradable | cut -d/ -f1",
    "fedora":    "dnf list updates -q 2>/dev/null | grep -v ^Updated | grep -v ^$ | cut -d. -f1",
    "centos":    "dnf list updates -q 2>/dev/null | grep -v ^Updated | grep -v ^$ | cut -d. -f1",
    "archlinux": "pacman -Qu 2>/dev/null | cut -d' ' -f1",
    "opensuse":  "zypper refresh -q 2>/dev/null && zypper list-updates 2>/dev/null | grep ^v | cut -d'|' -f3 | tr -d ' '",
}


def _extract_ssh_host(host: str) -> str:
    """Strip scheme and port from a host string for use as an SSH target.

    Handles bare IPs ('192.168.1.10'), hostnames with port ('host:8006'),
    and full URLs ('https://192.168.1.10:8006').
    """
    if "://" in host:
        return urlparse(host).hostname or host
    return host.split(":")[0]

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
_ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub('', text)

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

    @classmethod
    def from_host_config(cls, host_config) -> SSHClient:
        """Create an SSHClient from a ProxmoxHostConfig (avoids building a full Settings)."""
        instance = cls.__new__(cls)
        instance._username = host_config.ssh_username or "root"
        instance._key_path = host_config.ssh_key_path or ""
        instance._password = host_config.ssh_password or ""
        instance._enabled = True
        instance._known_hosts_path = ""
        return instance

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

    async def run_os_update(
        self,
        proxmox_host: str,
        vmid: str,
        os_type: str,
        ssh_username: str | None = None,
        ssh_key_path: str | None = None,
        ssh_password: str | None = None,
        timeout: int = 300,
    ) -> tuple[bool, str]:
        """Run OS package update in an LXC container via pct exec.

        Returns (success, output):
        - success: exit_code == 0 (package manager ran without error)
        - output: combined stdout/stderr for display (last 10 lines logged)
        """
        if not self._enabled:
            return False, "SSH not enabled"
        if not vmid.isdigit():
            return False, f"Invalid vmid: {vmid!r}"
        inner_cmd = OS_UPDATE_COMMANDS.get(os_type)
        if not inner_cmd:
            return False, f"Unsupported OS type: {os_type!r}"

        ssh_host = _extract_ssh_host(proxmox_host)
        # Wrap in sh -c so && is interpreted inside the container, not by the Proxmox host shell
        escaped = inner_cmd.replace("'", "'\\''")
        pct_command = f"pct exec {vmid} -- sh -c '{escaped}'"
        logger.info("OS update on %s vmid %s (ostype=%s)", ssh_host, vmid, os_type)
        try:
            stdout, stderr, exit_code = await asyncio.to_thread(
                self._execute_sync,
                ssh_host,
                pct_command,
                timeout,
                username=ssh_username,
                key_path=ssh_key_path,
                password=ssh_password,
                capture_exit_code=True,
            )
            success = (exit_code == 0)
            output = (stdout or "") + ("\n" + stderr if stderr else "")
            output = output.strip()

            tail = "\n".join(output.splitlines()[-10:]) if output else "(no output)"
            if success:
                logger.info(
                    "OS update on %s vmid %s (ostype=%s): exit_code=%s\n%s",
                    ssh_host, vmid, os_type, exit_code, tail,
                )
            else:
                logger.warning(
                    "OS update FAILED on %s vmid %s (ostype=%s): exit_code=%s\n%s",
                    ssh_host, vmid, os_type, exit_code, tail,
                )
            return success, output
        except Exception as exc:
            logger.warning("OS update exception on %s vmid %s: %s", ssh_host, vmid, exc)
            return False, str(exc)

    async def run_app_update(
        self,
        proxmox_host: str,
        vmid: str,
        ssh_username: str | None = None,
        ssh_key_path: str | None = None,
        ssh_password: str | None = None,
        timeout: int = 300,
    ) -> tuple[bool, str]:
        """Run the community-script updater inside an LXC container via pct exec.

        Executes PHS_SILENT=1 /usr/bin/update. Returns (success, output).
        """
        if not self._enabled:
            return False, "SSH not enabled"
        if not vmid.isdigit():
            return False, f"Invalid vmid: {vmid!r}"

        ssh_host = _extract_ssh_host(proxmox_host)
        escaped = "PHS_SILENT=1 /usr/bin/update".replace("'", "'\\''")
        pct_command = f"pct exec {vmid} -- sh -c '{escaped}'"
        logger.info("App update on %s vmid %s", ssh_host, vmid)
        try:
            stdout, stderr, exit_code = await asyncio.to_thread(
                self._execute_sync,
                ssh_host,
                pct_command,
                timeout,
                username=ssh_username,
                key_path=ssh_key_path,
                password=ssh_password,
                capture_exit_code=True,
            )
            success = (exit_code == 0)
            output = (stdout or "") + ("\n" + stderr if stderr else "")
            output = _strip_ansi(output).strip()
            tail = "\n".join(output.splitlines()[-10:]) if output else "(no output)"
            if success:
                logger.info(
                    "App update on %s vmid %s: exit_code=%s\n%s",
                    ssh_host, vmid, exit_code, tail,
                )
            else:
                logger.warning(
                    "App update FAILED on %s vmid %s: exit_code=%s\n%s",
                    ssh_host, vmid, exit_code, tail,
                )
            return success, output
        except Exception as exc:
            logger.warning("App update exception on %s vmid %s: %s", ssh_host, vmid, exc)
            return False, str(exc)

    async def run_pending_updates_list(
        self,
        proxmox_host: str,
        vmid: str,
        os_type: str,
        ssh_username: str | None = None,
        ssh_key_path: str | None = None,
        ssh_password: str | None = None,
        timeout: int = 90,
    ) -> list[str] | None:
        """List pending OS package updates in an LXC container via pct exec.

        Refreshes the package index (apt-get update / apk update / zypper refresh)
        before listing, so results reflect current repo state. Performs network I/O
        inside the container. Returns a list of package names, empty list if
        up-to-date, or None on failure (including refresh failure).
        """
        if not self._enabled:
            return None
        if not vmid.isdigit():
            return None
        check_cmd = OS_PENDING_UPDATES_LIST_COMMANDS.get(os_type)
        if not check_cmd:
            return None

        ssh_host = _extract_ssh_host(proxmox_host)
        escaped = check_cmd.replace("'", "'\\''")
        pct_command = f"pct exec {vmid} -- sh -c '{escaped}'"
        logger.debug("pending updates list on %s vmid %s (ostype=%s)", ssh_host, vmid, os_type)
        try:
            stdout, _stderr, exit_code = await asyncio.to_thread(
                self._execute_sync,
                ssh_host,
                pct_command,
                timeout,
                username=ssh_username,
                key_path=ssh_key_path,
                password=ssh_password,
                capture_exit_code=True,
            )
            # grep exits 1 when no matches (0 packages) — still valid
            if exit_code not in (0, 1):
                logger.debug(
                    "pending updates list failed on %s vmid %s: exit_code=%s",
                    ssh_host, vmid, exit_code,
                )
                return None
            return [p.strip() for p in (stdout or "").splitlines() if p.strip()]
        except Exception as exc:
            logger.debug("pending updates list exception on %s vmid %s: %s", ssh_host, vmid, exc)
            return None

    async def run_reboot_required_check(
        self,
        proxmox_host: str,
        vmid: str,
        ssh_username: str | None = None,
        ssh_key_path: str | None = None,
        ssh_password: str | None = None,
        timeout: int = 10,
    ) -> bool | None:
        """Check if /var/run/reboot-required exists in an LXC container.

        Returns True (reboot needed), False (not needed), or None (check failed).
        Non-Debian distros cleanly return False since the file won't exist.
        """
        if not self._enabled:
            return None
        if not vmid.isdigit():
            return None

        ssh_host = _extract_ssh_host(proxmox_host)
        pct_command = f"pct exec {vmid} -- test -f /var/run/reboot-required"
        logger.debug("reboot-required check on %s vmid %s", ssh_host, vmid)
        try:
            _stdout, _stderr, exit_code = await asyncio.to_thread(
                self._execute_sync,
                ssh_host,
                pct_command,
                timeout,
                username=ssh_username,
                key_path=ssh_key_path,
                password=ssh_password,
                capture_exit_code=True,
            )
            if exit_code == 0:
                return True
            if exit_code == 1:
                return False
            logger.debug(
                "reboot-required check unexpected exit_code=%s on %s vmid %s",
                exit_code, ssh_host, vmid,
            )
            return None
        except Exception as exc:
            logger.debug("reboot-required check exception on %s vmid %s: %s", ssh_host, vmid, exc)
            return None

    async def run_community_script_check(
        self,
        proxmox_host: str,
        vmid: str,
        ssh_username: str | None = None,
        ssh_key_path: str | None = None,
        ssh_password: str | None = None,
        timeout: int = 10,
    ) -> bool | None:
        """Check if /usr/bin/update exists inside an LXC container via pct exec.

        Returns True (present), False (absent), None (check failed / SSH disabled).
        """
        if not self._enabled:
            return None
        if not vmid.isdigit():
            return None

        ssh_host = _extract_ssh_host(proxmox_host)
        pct_command = f"pct exec {vmid} -- test -f /usr/bin/update"
        logger.debug("community-script check on %s vmid %s", ssh_host, vmid)
        try:
            _stdout, _stderr, exit_code = await asyncio.to_thread(
                self._execute_sync,
                ssh_host,
                pct_command,
                timeout,
                username=ssh_username,
                key_path=ssh_key_path,
                password=ssh_password,
                capture_exit_code=True,
            )
            if exit_code == 0:
                return True
            if exit_code == 1:
                return False
            logger.debug(
                "community-script check unexpected exit_code=%s on %s vmid %s",
                exit_code, ssh_host, vmid,
            )
            return None
        except Exception as exc:
            logger.debug("community-script check exception on %s vmid %s: %s", ssh_host, vmid, exc)
            return None

    def _execute_sync(
        self,
        host: str,
        command: str,
        timeout: int,
        username: str | None = None,
        key_path: str | None = None,
        password: str | None = None,
        capture_exit_code: bool = False,
    ) -> tuple[str, str] | tuple[str, str, int]:
        """Blocking SSH execution (run in thread).

        Returns (stdout, stderr) when capture_exit_code is False.
        Returns (stdout, stderr, exit_code) when capture_exit_code is True.
        exit_code is -1 if the connection could not be established.
        """
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
                if capture_exit_code:
                    return "", "no credentials configured", -1
                return "", "no credentials configured"

            client.connect(**connect_kwargs)  # type: ignore[arg-type]
            _, stdout_ch, stderr_ch = client.exec_command(command, timeout=timeout)
            out = stdout_ch.read().decode("utf-8", errors="replace").strip()
            err = stderr_ch.read().decode("utf-8", errors="replace").strip()
            if capture_exit_code:
                exit_code = stdout_ch.channel.recv_exit_status()
                return out, err, exit_code
            return out, err
        except Exception as exc:
            if capture_exit_code:
                return "", str(exc), -1
            return "", str(exc)
        finally:
            client.close()
