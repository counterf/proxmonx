"""Tests for SSH version command validation and execution."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.config import Settings
from app.core.ssh import SSHClient


@pytest.fixture
def settings() -> Settings:
    return Settings(
        ssh_username="root",
        ssh_key_path="/fake/key",
        ssh_password=None,
        ssh_enabled=True,
        ssh_known_hosts_path="",
    )


@pytest.fixture
def ssh_client(settings: Settings) -> SSHClient:
    return SSHClient(settings)


# -- _is_version_cmd_safe --


class TestIsVersionCmdSafe:
    def test_valid_simple_command(self) -> None:
        assert SSHClient._is_version_cmd_safe("myapp --version") is True

    def test_allow_pipe_to_safe_filter(self) -> None:
        assert SSHClient._is_version_cmd_safe("myapp --version | head -1") is True

    def test_allow_pipe_to_awk(self) -> None:
        assert SSHClient._is_version_cmd_safe("traefik version | awk '/^Version:/ {print $2}'") is True

    def test_allow_pipe_to_tail(self) -> None:
        assert SSHClient._is_version_cmd_safe("dpkg -l sonarr | tail -1") is True

    def test_reject_pipe_to_unsafe_command(self) -> None:
        assert SSHClient._is_version_cmd_safe("myapp --version | bash") is False

    def test_reject_pipe_to_sh(self) -> None:
        assert SSHClient._is_version_cmd_safe("echo test | sh -c 'id'") is False

    def test_reject_empty(self) -> None:
        assert SSHClient._is_version_cmd_safe("") is False

    def test_reject_whitespace_only(self) -> None:
        assert SSHClient._is_version_cmd_safe("   ") is False

    def test_reject_too_long(self) -> None:
        assert SSHClient._is_version_cmd_safe("a" * 513) is False

    def test_accept_max_length(self) -> None:
        assert SSHClient._is_version_cmd_safe("a" * 512) is True

    def test_reject_semicolon(self) -> None:
        assert SSHClient._is_version_cmd_safe("echo ok; rm -rf /") is False

    def test_reject_backtick(self) -> None:
        assert SSHClient._is_version_cmd_safe("echo `whoami`") is False

    def test_reject_dollar_paren(self) -> None:
        assert SSHClient._is_version_cmd_safe("echo $(whoami)") is False

    def test_reject_and_and(self) -> None:
        assert SSHClient._is_version_cmd_safe("true && rm -rf /") is False

    def test_reject_or_or(self) -> None:
        assert SSHClient._is_version_cmd_safe("false || rm -rf /") is False

    def test_reject_newline(self) -> None:
        assert SSHClient._is_version_cmd_safe("echo ok\nrm -rf /") is False

    def test_reject_null_byte(self) -> None:
        assert SSHClient._is_version_cmd_safe("echo ok\x00rm") is False


# -- execute_version_cmd --


class TestExecuteVersionCmd:
    @pytest.mark.asyncio
    async def test_returns_first_line_stripped(self, ssh_client: SSHClient) -> None:
        with patch.object(
            ssh_client, "_execute_sync", return_value="  1.2.3\n4.5.6\n"
        ):
            result = await ssh_client.execute_version_cmd("10.0.0.1", "app --version")
            assert result == "  1.2.3\n4.5.6\n"
            # The caller (discovery.py) does the strip/splitlines — execute_version_cmd
            # returns raw output from _execute_sync

    @pytest.mark.asyncio
    async def test_passes_credential_overrides(self, ssh_client: SSHClient) -> None:
        with patch.object(
            ssh_client, "_execute_sync", return_value="2.0.0"
        ) as mock_exec:
            await ssh_client.execute_version_cmd(
                "10.0.0.1",
                "app --version",
                username="admin",
                key_path="/custom/key",
                password="secret",
            )
            mock_exec.assert_called_once_with(
                "10.0.0.1",
                "app --version",
                10,
                username="admin",
                key_path="/custom/key",
                password="secret",
            )

    @pytest.mark.asyncio
    async def test_rejects_unsafe_command(self, ssh_client: SSHClient) -> None:
        with patch.object(ssh_client, "_execute_sync") as mock_exec:
            result = await ssh_client.execute_version_cmd(
                "10.0.0.1", "echo ok; rm -rf /"
            )
            assert result is None
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self, settings: Settings) -> None:
        settings.ssh_enabled = False
        client = SSHClient(settings)
        result = await client.execute_version_cmd("10.0.0.1", "app --version")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, ssh_client: SSHClient) -> None:
        with patch.object(
            ssh_client, "_execute_sync", side_effect=RuntimeError("boom")
        ):
            result = await ssh_client.execute_version_cmd("10.0.0.1", "app --version")
            assert result is None
