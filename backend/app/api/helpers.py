"""Shared helpers for API route modules."""

import hmac
import logging
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.core.github import parse_github_repo
from app.core.ssh import SSHClient

logger = logging.getLogger(__name__)


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


_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def _require_api_key(
    request: Request,
    x_api_key: str | None = Depends(_api_key_header),
) -> None:
    """Validate API key on mutating endpoints when proxmon_api_key is set.

    Accepts the key via ``Authorization: Bearer <token>`` or ``X-Api-Key: <token>``.
    If no API key is configured, authentication is skipped (backwards compatible).
    """
    config_store = getattr(request.app.state, "config_store", None)
    if config_store is not None and not config_store.is_configured():
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

    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# --- Secret masking ---

_TOP_SECRET_FIELDS = frozenset({
    "proxmox_token_secret", "github_token", "ssh_password",
    "ntfy_token", "proxmon_api_key",
})
_NESTED_SECRET_FIELDS = frozenset({"api_key", "ssh_password", "token_secret"})
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
# Note: empty string "" is also treated as "keep existing" by this function
# because `not incoming` is True for "".  There is currently no UI path to
# explicitly clear a secret field.
# This function implements that contract.
def _keep_or_replace(incoming: str | None, existing: str | None) -> str | None:
    """Return existing value when incoming is None, empty, or the masked sentinel '***'."""
    if not incoming or incoming == "***":
        return existing or None
    return incoming


def _reload_settings_into_engine(request: Request, config_store) -> None:
    """Reload settings from DB and update the discovery engine's reference."""
    new_settings = config_store.merge_into_settings(Settings())
    request.app.dependency_overrides[_get_settings] = lambda: new_settings
    request.app.state.settings = new_settings
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler and hasattr(scheduler, '_engine'):
        scheduler._engine._settings = new_settings


# --- Shared request models ---


class _AppConfigBase(BaseModel):
    """Shared fields and validators for per-app / per-guest config entries."""

    port: int | None = Field(default=None, ge=1, le=65535)
    api_key: str | None = None
    scheme: Literal["http", "https"] | None = None
    github_repo: str | None = None
    ssh_version_cmd: str | None = Field(default=None, max_length=512)
    ssh_username: str | None = None
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    version_host: str | None = None

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
