"""Shared helpers for API route modules."""

import asyncio
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

from app.config import ProxmoxHostConfig, Settings
from app.core.github import parse_github_repo
from app.core.ssh import SSHClient
from app.core.task_store import TaskStore

logger = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("Background task failed: %s", exc, exc_info=exc)


# --- Dependency placeholders ---


def _get_scheduler():
    """Dependency placeholder -- overridden in main.py."""
    raise RuntimeError("Scheduler not initialized")


def _get_settings():
    """Dependency placeholder -- overridden in main.py."""
    raise RuntimeError("Settings not initialized")


def _get_config_store():
    """Dependency placeholder -- overridden in main.py."""
    raise RuntimeError("ConfigStore not initialized")


def _get_task_store():
    """Dependency placeholder -- overridden in main.py."""
    raise RuntimeError("TaskStore not initialized")


_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def _require_api_key(
    request: Request,
    x_api_key: str | None = Depends(_api_key_header),
) -> None:
    """Validate API key on mutating endpoints when proxmon_api_key is set.

    Accepts the key via ``Authorization: Bearer <token>`` or ``X-Api-Key: <token>``.
    If no API key is configured, authentication is skipped (backwards compatible).
    During initial setup, the auth middleware grants a setup exemption (local-
    network only) and sets ``request.state.setup_exempt``; honour that flag here.
    """
    if getattr(request.state, "setup_exempt", False):
        return

    settings = getattr(request.app.state, "settings", None)
    expected = settings.proxmon_api_key if settings else None
    if not expected:
        return

    token = x_api_key
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    if token and hmac.compare_digest(token, expected):
        return

    # Accept a valid browser session cookie as equivalent to an API key.
    session_store = getattr(request.app.state, "session_store", None)
    if session_store is not None:
        session_token = request.cookies.get("proxmon_session")
        if session_token and session_store.is_valid(session_token):
            return

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


# --- Secret masking ---

_TOP_SECRET_FIELDS = frozenset({
    "github_token", "ssh_password", "ssh_key",
    "ntfy_token", "proxmon_api_key",
})
_NESTED_SECRET_FIELDS = frozenset({"api_key", "ssh_password", "ssh_key", "token_secret"})
_EXCLUDED_FIELDS = frozenset({"config_db_path", "ssh_known_hosts_path"})


def _mask(data: dict, secret_fields: frozenset[str]) -> dict:
    """Replace secret field values with '***' (or None if unset)."""
    return {k: ("***" if k in secret_fields and v else v) for k, v in data.items()}


# Secret masking protocol:
# The frontend sends "***" for secret fields that were loaded from settings and not changed.
# It sends None when the field was never set or the value is absent.
# Both "***" and None mean: keep the existing stored value unchanged.
# To update a field, the frontend sends the new plaintext value.
# To clear a field intentionally, the frontend sends an empty string "".
def _keep_or_replace(incoming: str | None, existing: str | None) -> str | None:
    """Keep existing when incoming is None or '***'. Clear when incoming is ''. Replace otherwise."""
    if incoming is None or incoming == "***":
        return existing or None
    if incoming == "":
        return None  # explicit clear
    return incoming


def _reload_settings_into_engine(request: Request, config_store) -> None:
    """Reload settings from DB and update the discovery engine's reference."""
    new_settings = config_store.merge_into_settings(Settings())
    request.app.dependency_overrides[_get_settings] = lambda: new_settings
    request.app.state.settings = new_settings
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.reload_settings(new_settings)


# --- Shared request models ---


class _AppConfigBase(BaseModel):
    """Shared fields and validators for per-app / per-guest config entries."""

    port: int | None = Field(default=None, ge=0, le=65535)  # 0 = clear sentinel
    api_key: str | None = None
    scheme: str | None = None
    github_repo: str | None = None
    ssh_version_cmd: str | None = Field(default=None, max_length=512)
    ssh_username: str | None = None
    ssh_key: str | None = None
    ssh_password: str | None = None
    version_host: str | None = None

    @field_validator("scheme")
    @classmethod
    def validate_scheme(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if v not in ("http", "https"):
            raise ValueError(f"scheme must be 'http' or 'https', got {v!r}")
        return v

    @field_validator("ssh_version_cmd")
    @classmethod
    def validate_ssh_version_cmd(cls, v: str | None) -> str | None:
        if v is not None:
            if "\n" in v or "\0" in v:
                raise ValueError("ssh_version_cmd must not contain newlines or null bytes")
            if v and not SSHClient._is_version_cmd_safe(v):
                raise ValueError("ssh_version_cmd contains unsafe shell patterns")
        return v

    @field_validator("github_repo")
    @classmethod
    def validate_github_repo(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        try:
            return parse_github_repo(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def run_os_update_bg(
    task_id: str,
    guest_id: str,
    ssh: SSHClient,
    host_config: ProxmoxHostConfig,
    vmid: str,
    os_type: str,
    scheduler: Any,
    task_store: TaskStore,
) -> None:
    try:
        success, output = await ssh.run_os_update(
            host_config.host, vmid, os_type,
            ssh_username=host_config.ssh_username,
            ssh_key=host_config.ssh_key,
            ssh_password=host_config.ssh_password,
        )
        task_store.update(
            task_id,
            status="success" if success else "failed",
            output=output,
            finished_at=_now_iso(),
        )
        if success:
            scheduler.trigger_guest_refresh(guest_id)
    except Exception as exc:
        task_store.update(
            task_id,
            status="failed",
            detail=str(exc),
            finished_at=_now_iso(),
        )


_APP_UPDATE_PROBE_INTERVAL = 5  # seconds between version probes (initial + retries)
_APP_UPDATE_RETRY_BUDGET = 60   # max seconds to keep retrying after first probe


def _last_lines(text: str, n: int = 3) -> str:
    """Return the last *n* non-empty lines of *text*."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:]) if lines else text


async def run_app_update_bg(
    task_id: str,
    guest_id: str,
    ssh: SSHClient,
    host_config: ProxmoxHostConfig,
    vmid: str,
    scheduler: Any,
    task_store: TaskStore,
) -> None:
    try:
        success, output = await ssh.run_app_update(
            host_config.host, vmid,
            ssh_username=host_config.ssh_username,
            ssh_key=host_config.ssh_key,
            ssh_password=host_config.ssh_password,
        )
        task_store.update(
            task_id,
            status="success" if success else "failed",
            detail=_last_lines(output) if output else None,
            output=output,
            finished_at=_now_iso(),
        )
        if success:
            await asyncio.sleep(_APP_UPDATE_PROBE_INTERVAL)
            deadline = asyncio.get_event_loop().time() + _APP_UPDATE_RETRY_BUDGET
            while True:
                ok = await scheduler.refresh_single_guest_awaitable(guest_id)
                if ok or asyncio.get_event_loop().time() >= deadline:
                    break
                await asyncio.sleep(_APP_UPDATE_PROBE_INTERVAL)
    except Exception as exc:
        task_store.update(
            task_id,
            status="failed",
            detail=str(exc),
            finished_at=_now_iso(),
        )
