"""API route definitions."""

import hmac
import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator

from app.config import CustomAppDef, Settings, _CUSTOM_APP_NAME_RE
from app.core.auth import hash_password
from app.core.github import GitHubClient, parse_github_repo
from app.core.notifier import NtfyNotifier
from app.detectors.registry import ALL_DETECTORS, DETECTOR_MAP, _BUILTIN_NAMES, load_custom_detectors
from app.models.guest import GuestInfo

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response models ---


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

    @field_validator("ssh_version_cmd")
    @classmethod
    def validate_ssh_version_cmd(cls, v: str | None) -> str | None:
        if v and ('\n' in v or '\0' in v):
            raise ValueError("ssh_version_cmd must not contain newlines or null bytes")
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


class AppConfigEntry(_AppConfigBase):
    pass


class ProxmoxHostSaveEntry(BaseModel):
    id: str
    label: str
    host: str
    token_id: str
    token_secret: str | None = None  # None / "***" = keep current
    node: str
    verify_ssl: bool = False
    ssh_username: str = "root"
    ssh_password: str | None = None
    ssh_key_path: str | None = None
    pct_exec_enabled: bool = False

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Host ID is required")
        if len(v) > 64:
            raise ValueError("Host ID must not exceed 64 characters")
        return v.strip()

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Host label is required")
        return v.strip()

    @field_validator("host")
    @classmethod
    def validate_host_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Host must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Token ID is required")
        return v.strip()

    @field_validator("node")
    @classmethod
    def validate_node(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Node name is required")
        return v.strip()


class SettingsSaveRequest(BaseModel):
    proxmox_host: str
    proxmox_token_id: str
    proxmox_token_secret: str | None = None
    proxmox_node: str
    poll_interval_seconds: int = Field(default=300, ge=30, le=3600)
    discover_vms: bool = False
    verify_ssl: bool = False
    ssh_enabled: bool = True
    ssh_username: str = "root"
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    github_token: str | None = None
    log_level: str = "info"
    version_detect_method: Literal["pct_first", "ssh_first", "ssh_only", "pct_only"] = "pct_first"
    app_config: dict[str, AppConfigEntry] | None = None
    proxmox_hosts: list[ProxmoxHostSaveEntry] | None = None
    auth_mode: Literal["disabled", "forms"] | None = None
    auth_username: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=1024)
    notifications_enabled: bool | None = None
    ntfy_url: str | None = None
    ntfy_token: str | None = None
    ntfy_priority: int | None = Field(default=None, ge=1, le=5)
    notify_disk_threshold: int | None = Field(default=None, ge=50, le=100)
    notify_disk_cooldown_minutes: int | None = Field(default=None, ge=15, le=1440)
    notify_on_outdated: bool | None = None
    proxmon_api_key: str | None = None
    trust_proxy_headers: bool | None = None

    @field_validator("proxmox_host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Host must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("proxmox_token_id")
    @classmethod
    def validate_token_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Token ID is required")
        return v.strip()

    @field_validator("proxmox_node")
    @classmethod
    def validate_node(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Node name is required")
        return v.strip()

    @field_validator("app_config")
    @classmethod
    def validate_app_config(
        cls, v: dict[str, AppConfigEntry] | None,
    ) -> dict[str, AppConfigEntry] | None:
        if v is None:
            return v
        for key in v:
            if key not in DETECTOR_MAP:
                raise ValueError(f"Unknown app: {key}")
        return v


class GitHubTestRequest(BaseModel):
    repo: str


class GitHubTestResponse(BaseModel):
    ok: bool
    repo: str
    version: str | None = None
    source: str | None = None
    reason: str | None = None


class ConnectionTestRequest(BaseModel):
    proxmox_host: str
    proxmox_token_id: str
    proxmox_token_secret: str
    proxmox_node: str
    verify_ssl: bool = False
    host_id: str | None = None

    @field_validator("proxmox_host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Proxmox host is required")
        if not v.startswith(("http://", "https://")):
            raise ValueError("Host must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("proxmox_token_id")
    @classmethod
    def validate_token_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Token ID is required")
        return v.strip()

    @field_validator("proxmox_node")
    @classmethod
    def validate_node(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Node name is required")
        return v.strip()


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


# --- Existing endpoints ---


@router.get("/health")
async def health(
    scheduler=Depends(_get_scheduler),
    config_store=Depends(_get_config_store),
) -> dict[str, str | int | float | bool | None]:
    """Health check endpoint."""
    configured = config_store.is_configured()
    if not configured or scheduler is None:
        return {
            "status": "unconfigured",
            "configured": False,
            "last_poll": None,
            "guest_count": 0,
            "is_polling": False,
            "seconds_since_last_poll": None,
        }

    uptime_seconds = 0.0
    if scheduler.last_poll:
        uptime_seconds = (datetime.now(timezone.utc) - scheduler.last_poll).total_seconds()
    return {
        "status": "ok",
        "configured": True,
        "last_poll": scheduler.last_poll.isoformat() if scheduler.last_poll else None,
        "guest_count": len(scheduler.guests),
        "is_polling": scheduler.is_running,
        "seconds_since_last_poll": round(uptime_seconds, 1) if scheduler.last_poll else None,
    }


@router.get("/api/guests")
async def list_guests(scheduler=Depends(_get_scheduler)) -> list[GuestInfo]:
    """List all discovered guests."""
    if scheduler is None:
        return []
    return list(scheduler.guests.values())


@router.get("/api/guests/{guest_id}")
async def get_guest(guest_id: str, scheduler=Depends(_get_scheduler)) -> GuestInfo:
    """Get detail for a single guest."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    guest = scheduler.guests.get(guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")
    return guest


class GuestConfigSaveRequest(_AppConfigBase):
    forced_detector: str | None = None

    @field_validator("forced_detector")
    @classmethod
    def validate_forced_detector(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if v not in DETECTOR_MAP:
            raise ValueError(f"Unknown detector: {v!r}")
        return v


@router.get("/api/guests/{guest_id}/config")
async def get_guest_config(
    guest_id: str,
    config_store=Depends(_get_config_store),
) -> dict[str, Any]:
    """Return per-guest config overrides (API keys masked)."""
    data = config_store.load()
    guest_cfg = data.get("guest_config", {}).get(guest_id, {})
    if guest_cfg.get("api_key"):
        guest_cfg = dict(guest_cfg)
        guest_cfg["api_key"] = "***"
    return guest_cfg


def _reload_settings_into_engine(request: Request, config_store) -> None:
    """Reload settings from DB and update the discovery engine's reference."""
    new_settings = config_store.merge_into_settings(Settings())
    request.app.dependency_overrides[_get_settings] = lambda: new_settings
    request.app.state.settings = new_settings
    scheduler = request.app.dependency_overrides.get(_get_scheduler, lambda: None)()
    if scheduler and hasattr(scheduler, '_engine'):
        scheduler._engine._settings = new_settings


@router.put("/api/guests/{guest_id}/config", dependencies=[Depends(_require_api_key)])
async def save_guest_config(
    guest_id: str,
    body: GuestConfigSaveRequest,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict[str, str]:
    """Save per-guest configuration overrides."""
    data = config_store.load()
    all_guest_cfg: dict = data.get("guest_config", {})
    prev = all_guest_cfg.get(guest_id, {})

    merged: dict[str, Any] = {}
    if body.port is not None:
        merged["port"] = body.port
    if body.scheme is not None and body.scheme != "":
        merged["scheme"] = body.scheme
    if body.github_repo is not None and body.github_repo != "":
        merged["github_repo"] = body.github_repo
    if body.ssh_version_cmd is not None and body.ssh_version_cmd != "":
        merged["ssh_version_cmd"] = body.ssh_version_cmd
    if body.ssh_username is not None and body.ssh_username != "":
        merged["ssh_username"] = body.ssh_username

    merged["api_key"] = _keep_or_replace(body.api_key, prev.get("api_key"))
    merged["ssh_key_path"] = _keep_or_replace(body.ssh_key_path, prev.get("ssh_key_path"))
    merged["ssh_password"] = _keep_or_replace(body.ssh_password, prev.get("ssh_password"))

    if body.forced_detector:
        merged["forced_detector"] = body.forced_detector
    # None means "clear" — not added to merged, stripped below

    # Strip None values
    merged = {k: v for k, v in merged.items() if v is not None}

    if merged:
        all_guest_cfg[guest_id] = merged
    elif guest_id in all_guest_cfg:
        del all_guest_cfg[guest_id]

    data["guest_config"] = all_guest_cfg
    config_store.save(data)
    _reload_settings_into_engine(request, config_store)
    logger.info("Guest config saved for %s", guest_id)
    return {"status": "saved"}


@router.delete("/api/guests/{guest_id}/config", dependencies=[Depends(_require_api_key)])
async def delete_guest_config(
    guest_id: str,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict[str, str]:
    """Remove all per-guest config overrides (reset to inherit from global)."""
    data = config_store.load()
    all_guest_cfg: dict = data.get("guest_config", {})
    if guest_id in all_guest_cfg:
        del all_guest_cfg[guest_id]
        data["guest_config"] = all_guest_cfg
        config_store.save(data)
    _reload_settings_into_engine(request, config_store)
    logger.info("Guest config cleared for %s", guest_id)
    return {"status": "cleared"}


@router.post("/api/refresh", status_code=202, dependencies=[Depends(_require_api_key)])
async def refresh(scheduler=Depends(_get_scheduler)) -> dict[str, str]:
    """Trigger an immediate re-discovery cycle."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    scheduler.trigger_refresh()
    return {"status": "started"}


@router.get("/api/setup/status")
async def setup_status(
    config_store=Depends(_get_config_store),
) -> dict[str, bool | list[str]]:
    """Return whether the app is configured and which fields are missing."""
    return {
        "configured": config_store.is_configured(),
        "missing_fields": config_store.get_missing_fields(),
    }


_TOP_SECRET_FIELDS = frozenset({
    "proxmox_token_secret", "github_token", "ssh_password",
    "ntfy_token", "proxmon_api_key",
})
_NESTED_SECRET_FIELDS = frozenset({"api_key", "ssh_password", "token_secret"})
_EXCLUDED_FIELDS = frozenset({"config_db_path", "ssh_known_hosts_path"})


def _mask(data: dict, secret_fields: frozenset[str]) -> dict:
    """Replace secret field values with '***' (or None if unset)."""
    return {k: ("***" if k in secret_fields and v else v) for k, v in data.items()}


@router.get("/api/settings/full")
async def get_full_settings(
    settings=Depends(_get_settings),
    config_store=Depends(_get_config_store),
) -> dict[str, Any]:
    """Return all settings with secrets masked."""
    result = _mask(settings.model_dump(), _TOP_SECRET_FIELDS)
    for key in _EXCLUDED_FIELDS:
        result.pop(key, None)

    result["app_config"] = {
        name: _mask(cfg.model_dump(), _NESTED_SECRET_FIELDS)
        for name, cfg in settings.app_config.items()
    }
    result["guest_config"] = {
        gid: _mask(cfg.model_dump(), _NESTED_SECRET_FIELDS)
        for gid, cfg in settings.guest_config.items()
    }
    result["proxmox_hosts"] = [
        _mask(h.model_dump(), _NESTED_SECRET_FIELDS)
        for h in settings.proxmox_hosts
    ]
    result["auth_password_set"] = bool(
        config_store.load().get("auth_password_hash", "")
    )
    return result


@router.post("/api/settings/test-connection", dependencies=[Depends(_require_api_key)])
async def test_connection(
    body: ConnectionTestRequest,
) -> dict[str, bool | str | dict[str, str | int | float | bool | None] | None]:
    """Test Proxmox connectivity without saving settings."""
    base_url = f"{body.proxmox_host.rstrip('/')}/api2/json"
    headers = {
        "Authorization": f"PVEAPIToken={body.proxmox_token_id}={body.proxmox_token_secret}",
    }
    try:
        async with httpx.AsyncClient(verify=body.verify_ssl, timeout=10.0) as client:
            # Test with /version endpoint
            resp = await client.get(f"{base_url}/version", headers=headers)
            resp.raise_for_status()
            version_data = resp.json().get("data", {})

            # Also check the node exists
            node_resp = await client.get(
                f"{base_url}/nodes/{body.proxmox_node}/status",
                headers=headers,
            )
            node_resp.raise_for_status()
            node_data = node_resp.json().get("data", {})

            pve_version = version_data.get("version", "unknown") if isinstance(version_data, dict) else "unknown"

            return {
                "success": True,
                "message": f"Connected to Proxmox {pve_version} on node {body.proxmox_node}",
                "node_info": {
                    "pve_version": pve_version,
                    "node": body.proxmox_node,
                    "uptime": node_data.get("uptime") if isinstance(node_data, dict) else None,
                },
            }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401:
            msg = "Authentication failed: invalid token ID or secret"
        elif status == 403:
            msg = "Authorization denied: token lacks required permissions"
        else:
            msg = f"Proxmox API returned HTTP {status}"
        logger.warning("Connection test failed: %s", msg)
        return {"success": False, "message": msg, "node_info": None}
    except httpx.ConnectError:
        msg = f"Connection refused: {body.proxmox_host}"
        logger.warning("Connection test failed: %s", msg)
        return {"success": False, "message": msg, "node_info": None}
    except httpx.TimeoutException:
        msg = f"Connection timed out: {body.proxmox_host}"
        logger.warning("Connection test failed: %s", msg)
        return {"success": False, "message": msg, "node_info": None}
    except Exception as exc:
        msg = f"Connection error: {exc}"
        logger.warning("Connection test failed: %s", msg)
        return {"success": False, "message": msg, "node_info": None}


@router.post("/api/github/test", dependencies=[Depends(_require_api_key)])
async def github_test_repo(body: GitHubTestRequest, request: Request) -> GitHubTestResponse:
    settings: Settings = request.app.state.settings
    result = await GitHubClient(settings).test_repo(body.repo)
    return GitHubTestResponse(
        ok=result.ok,
        repo=result.repo,
        version=result.version,
        source=result.source,
        reason=result.reason,
    )


@router.get("/api/app-config/defaults")
async def get_app_config_defaults() -> list[dict[str, str | int | bool]]:
    """Return the list of supported apps with default ports and API key support."""
    return [
        {
            "name": d.name,
            "display_name": d.display_name,
            "default_port": d.default_port,
            "accepts_api_key": d.accepts_api_key,
            "default_scheme": "http",
            "github_repo": d.github_repo,
        }
        for d in ALL_DETECTORS
    ]


def _keep_or_replace(incoming: str | None, existing: str | None) -> str | None:
    """Return existing value when incoming is None, empty, or the masked sentinel '***'."""
    if not incoming or incoming == "***":
        return existing or None
    return incoming


@router.post("/api/settings", dependencies=[Depends(_require_api_key)])
async def save_settings(
    body: SettingsSaveRequest,
    request: Request,
    settings=Depends(_get_settings),
    config_store=Depends(_get_config_store),
    scheduler=Depends(_get_scheduler),
) -> dict[str, bool | str]:
    """Save settings to config file, reload, and restart scheduler."""
    # Read existing config once to avoid TOCTOU and preserve values
    current_file = config_store.load()

    # If token_secret is None, empty, or masked sentinel, keep current value
    token_secret = _keep_or_replace(
        body.proxmox_token_secret,
        current_file.get("proxmox_token_secret") or settings.proxmox_token_secret,
    )
    if not token_secret:
        raise HTTPException(
            status_code=422,
            detail="Token secret is required (no existing value found)",
        )

    # Build config data to persist
    config_data: dict[str, Any] = {
        "proxmox_host": body.proxmox_host,
        "proxmox_token_id": body.proxmox_token_id,
        "proxmox_token_secret": token_secret,
        "proxmox_node": body.proxmox_node,
        "poll_interval_seconds": body.poll_interval_seconds,
        "discover_vms": body.discover_vms,
        "verify_ssl": body.verify_ssl,
        "ssh_enabled": body.ssh_enabled,
        "ssh_username": body.ssh_username,
        "ssh_key_path": body.ssh_key_path,
        "ssh_password": _keep_or_replace(body.ssh_password, current_file.get("ssh_password")),
        "github_token": _keep_or_replace(body.github_token, current_file.get("github_token")),
        "log_level": body.log_level,
        "version_detect_method": body.version_detect_method,
    }

    # Auth settings -- preserve existing values when not sent
    if body.auth_mode is not None:
        config_data["auth_mode"] = body.auth_mode
    else:
        config_data["auth_mode"] = current_file.get("auth_mode", "forms")
    if body.auth_username is not None:
        config_data["auth_username"] = body.auth_username
    else:
        config_data["auth_username"] = current_file.get("auth_username", "root")
    # Password hash: set from new_password when provided, otherwise preserve existing.
    existing_hash = current_file.get("auth_password_hash", "")
    target_auth_mode = config_data.get("auth_mode", "forms")
    if target_auth_mode == "forms" and body.new_password:
        config_data["auth_password_hash"] = hash_password(body.new_password)
    elif existing_hash:
        config_data["auth_password_hash"] = existing_hash

    # Notification settings -- only overwrite when the client sends a value
    if body.notifications_enabled is not None:
        config_data["notifications_enabled"] = body.notifications_enabled
    else:
        config_data["notifications_enabled"] = current_file.get("notifications_enabled", False)
    if body.ntfy_url is not None:
        config_data["ntfy_url"] = body.ntfy_url
    else:
        config_data["ntfy_url"] = current_file.get("ntfy_url", "")
    config_data["ntfy_token"] = _keep_or_replace(
        body.ntfy_token, current_file.get("ntfy_token"),
    ) or ""
    if body.ntfy_priority is not None:
        config_data["ntfy_priority"] = body.ntfy_priority
    else:
        config_data["ntfy_priority"] = current_file.get("ntfy_priority", 3)
    if body.notify_disk_threshold is not None:
        config_data["notify_disk_threshold"] = body.notify_disk_threshold
    else:
        config_data["notify_disk_threshold"] = current_file.get("notify_disk_threshold", 95)
    if body.notify_disk_cooldown_minutes is not None:
        config_data["notify_disk_cooldown_minutes"] = body.notify_disk_cooldown_minutes
    else:
        config_data["notify_disk_cooldown_minutes"] = current_file.get("notify_disk_cooldown_minutes", 60)
    if body.notify_on_outdated is not None:
        config_data["notify_on_outdated"] = body.notify_on_outdated
    else:
        config_data["notify_on_outdated"] = current_file.get("notify_on_outdated", True)

    # API key (mask-aware) and trust proxy headers
    config_data["proxmon_api_key"] = _keep_or_replace(
        body.proxmon_api_key, current_file.get("proxmon_api_key"),
    )
    if body.trust_proxy_headers is not None:
        config_data["trust_proxy_headers"] = body.trust_proxy_headers
    else:
        config_data["trust_proxy_headers"] = current_file.get("trust_proxy_headers", False)

    # Multi-host support
    if body.proxmox_hosts is not None and len(body.proxmox_hosts) > 0:
        existing_hosts: list[dict] = current_file.get("proxmox_hosts", [])
        saved_hosts = []
        for entry in body.proxmox_hosts:
            existing = next((h for h in existing_hosts if h.get("id") == entry.id), {})
            saved_hosts.append({
                "id": entry.id,
                "label": entry.label,
                "host": entry.host,
                "token_id": entry.token_id,
                "token_secret": _keep_or_replace(entry.token_secret, existing.get("token_secret")),
                "node": entry.node,
                "verify_ssl": entry.verify_ssl,
                "ssh_username": entry.ssh_username,
                "ssh_password": _keep_or_replace(entry.ssh_password, existing.get("ssh_password")),
                "ssh_key_path": entry.ssh_key_path or existing.get("ssh_key_path") or "",
                "pct_exec_enabled": entry.pct_exec_enabled,
            })
        config_data["proxmox_hosts"] = saved_hosts
        # Sync first host to flat fields used by ProxmoxClient constructor
        if saved_hosts:
            first = saved_hosts[0]
            config_data["proxmox_host"] = first["host"]
            config_data["proxmox_token_id"] = first["token_id"]
            config_data["proxmox_token_secret"] = first["token_secret"]
            config_data["proxmox_node"] = first["node"]

    # Preserve existing proxmox_hosts when payload omits them
    if "proxmox_hosts" not in config_data:
        existing_hosts_data = current_file.get("proxmox_hosts")
        if existing_hosts_data:
            config_data["proxmox_hosts"] = existing_hosts_data

    # Merge app_config: preserve existing API keys when client sends "***" or null
    if body.app_config is not None:
        existing_app_config: dict[str, dict[str, Any]] = current_file.get("app_config", {})
        merged_app_config: dict[str, dict[str, Any]] = dict(existing_app_config)
        for app_name, entry in body.app_config.items():
            prev = existing_app_config.get(app_name, {})
            merged_entry: dict[str, Any] = {}
            # Port: None means "use default" (omit)
            if entry.port is not None:
                merged_entry["port"] = entry.port
            # API key: None means "keep current", "" means "clear", "***" means "keep"
            if entry.api_key is None or entry.api_key == "***":
                # Keep existing
                if prev.get("api_key"):
                    merged_entry["api_key"] = prev["api_key"]
            elif entry.api_key == "":
                # Explicit clear -- do not include api_key
                pass
            else:
                merged_entry["api_key"] = entry.api_key
            # Scheme: None means "keep current / use default"
            if entry.scheme is not None:
                merged_entry["scheme"] = entry.scheme
            elif prev.get("scheme"):
                merged_entry["scheme"] = prev["scheme"]
            # GitHub repo: None means "keep current", "" means "clear", value means "set"
            if entry.github_repo is None:
                if prev.get("github_repo"):
                    merged_entry["github_repo"] = prev["github_repo"]
            elif entry.github_repo == "":
                pass  # Explicit clear
            else:
                merged_entry["github_repo"] = entry.github_repo
            # ssh_version_cmd: plain value, None = keep, empty = clear
            if entry.ssh_version_cmd is None:
                if prev.get("ssh_version_cmd"):
                    merged_entry["ssh_version_cmd"] = prev["ssh_version_cmd"]
            elif entry.ssh_version_cmd == "":
                pass  # clear
            else:
                merged_entry["ssh_version_cmd"] = entry.ssh_version_cmd
            # ssh_username: plain value
            if entry.ssh_username is None:
                if prev.get("ssh_username"):
                    merged_entry["ssh_username"] = prev["ssh_username"]
            elif entry.ssh_username == "":
                pass  # clear
            else:
                merged_entry["ssh_username"] = entry.ssh_username
            # ssh_key_path: plain value
            if entry.ssh_key_path is None:
                if prev.get("ssh_key_path"):
                    merged_entry["ssh_key_path"] = prev["ssh_key_path"]
            elif entry.ssh_key_path == "":
                pass  # clear
            else:
                merged_entry["ssh_key_path"] = entry.ssh_key_path
            # ssh_password: treat like api_key (masked)
            if entry.ssh_password is None or entry.ssh_password == "***":
                if prev.get("ssh_password"):
                    merged_entry["ssh_password"] = prev["ssh_password"]
            elif entry.ssh_password == "":
                pass  # clear
            else:
                merged_entry["ssh_password"] = entry.ssh_password
            if merged_entry:
                merged_app_config[app_name] = merged_entry
            elif app_name in merged_app_config:
                del merged_app_config[app_name]
        config_data["app_config"] = merged_app_config
        changed_apps = [a for a in body.app_config]
        if changed_apps:
            logger.info("App config updated for: %s", ", ".join(changed_apps))
    else:
        # Preserve existing app_config when payload omits it
        config_data["app_config"] = current_file.get("app_config", {})

    # Always preserve guest_config (managed via /api/guests/{id}/config)
    existing_guest_config = current_file.get("guest_config")
    if existing_guest_config:
        config_data["guest_config"] = existing_guest_config

    # Always preserve custom_app_defs (managed via /api/custom-apps)
    existing_custom_apps = current_file.get("custom_app_defs")
    if existing_custom_apps:
        config_data["custom_app_defs"] = existing_custom_apps

    # Write to config file
    try:
        config_store.save(config_data)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Reload settings: config file values take priority over env/defaults
    new_settings = config_store.merge_into_settings(Settings())

    # Stop existing scheduler if running
    if scheduler is not None:
        await scheduler.stop()

    old_client: httpx.AsyncClient | None = getattr(request.app.state, "http_client", None)

    from app.main import build_runtime
    new_client, new_scheduler = build_runtime(new_settings)
    try:
        new_scheduler.start()
        request.app.state.http_client = new_client
        request.app.dependency_overrides[_get_scheduler] = lambda: new_scheduler
        request.app.dependency_overrides[_get_settings] = lambda: new_settings
        request.app.state.settings = new_settings
    except Exception as exc:
        await new_client.aclose()
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {exc}") from exc
    finally:
        if old_client is not None:
            await old_client.aclose()

    return {"success": True, "message": "Settings saved"}


@router.post("/api/notifications/test", dependencies=[Depends(_require_api_key)])
async def test_notification(
    settings=Depends(_get_settings),
) -> dict[str, bool | str]:
    """Send a test notification to verify ntfy connectivity."""
    if not settings.ntfy_url:
        return {"success": False, "message": "ntfy URL is not configured"}

    notifier = NtfyNotifier(
        url=settings.ntfy_url,
        token=settings.ntfy_token,
        priority=settings.ntfy_priority,
    )
    sent = await notifier.send(
        title="proxmon Test",
        message="This is a test notification from proxmon.",
        tags="white_check_mark",
    )
    if sent:
        return {"success": True, "message": "Test notification sent successfully"}
    return {"success": False, "message": "Failed to send notification -- check ntfy URL and token"}


# --- Custom App Definitions ---


class CustomAppDefRequest(BaseModel):
    """Request model for creating/updating a custom app definition."""

    name: str
    display_name: str
    default_port: int = Field(ge=1, le=65535)
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
        if v in _BUILTIN_NAMES:
            raise ValueError(f"'{v}' conflicts with a built-in app name")
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


def _reload_custom_detectors(
    request: Request, config_store, data: dict | None = None
) -> None:
    """Reload custom detectors from the DB and seed app_config for https apps.

    Pass *data* (already-loaded config dict) to avoid a redundant DB read.
    """
    if data is None:
        data = config_store.load()
    defs_raw = data.get("custom_app_defs", [])
    defs = []
    for i, item in enumerate(defs_raw):
        if isinstance(item, dict):
            try:
                defs.append(CustomAppDef(**item))
            except Exception as exc:
                logger.warning("Skipping invalid custom_app_defs[%d]: %s", i, exc)
                continue
    load_custom_detectors(defs)

    # Seed app_config for custom apps with scheme != "http"
    app_config = data.get("app_config", {})
    changed = False
    for defn in defs:
        if defn.scheme != "http" and defn.name not in app_config:
            app_config[defn.name] = {"scheme": defn.scheme}
            changed = True
    if changed:
        data["app_config"] = app_config
        config_store.save(data)

    # Reload settings into engine
    _reload_settings_into_engine(request, config_store)


@router.get("/api/custom-apps")
async def list_custom_apps(
    config_store=Depends(_get_config_store),
) -> list[dict]:
    """List all custom app definitions."""
    data = config_store.load()
    return data.get("custom_app_defs", [])


@router.post("/api/custom-apps", status_code=201, dependencies=[Depends(_require_api_key)])
async def create_custom_app(
    body: CustomAppDefRequest,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict:
    """Create a new custom app definition."""
    data = config_store.load()
    existing: list[dict] = data.get("custom_app_defs", [])

    # Check for duplicate name
    for item in existing:
        if isinstance(item, dict) and item.get("name") == body.name:
            raise HTTPException(status_code=409, detail=f"Custom app '{body.name}' already exists")

    new_def = body.model_dump()
    existing.append(new_def)
    data["custom_app_defs"] = existing
    config_store.save(data)
    _reload_custom_detectors(request, config_store, data=data)
    return new_def


@router.put("/api/custom-apps/{name}", dependencies=[Depends(_require_api_key)])
async def update_custom_app(
    name: str,
    body: CustomAppDefRequest,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict:
    """Update an existing custom app definition."""
    data = config_store.load()
    existing: list[dict] = data.get("custom_app_defs", [])

    for i, item in enumerate(existing):
        if isinstance(item, dict) and item.get("name") == name:
            updated = body.model_dump()
            updated["name"] = name  # preserve original name
            existing[i] = updated
            data["custom_app_defs"] = existing
            config_store.save(data)
            _reload_custom_detectors(request, config_store, data=data)
            return updated

    raise HTTPException(status_code=404, detail=f"Custom app '{name}' not found")


@router.delete("/api/custom-apps/{name}", dependencies=[Depends(_require_api_key)])
async def delete_custom_app(
    name: str,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict[str, str]:
    """Delete a custom app definition and clear references in guest_config."""
    data = config_store.load()
    existing: list[dict] = data.get("custom_app_defs", [])

    found = False
    new_list = []
    for item in existing:
        if isinstance(item, dict) and item.get("name") == name:
            found = True
        else:
            new_list.append(item)

    if not found:
        raise HTTPException(status_code=404, detail=f"Custom app '{name}' not found")

    data["custom_app_defs"] = new_list

    # Clear forced_detector references in guest_config
    guest_config: dict = data.get("guest_config", {})
    for gid, gcfg in guest_config.items():
        if isinstance(gcfg, dict) and gcfg.get("forced_detector") == name:
            gcfg.pop("forced_detector", None)

    config_store.save(data)
    _reload_custom_detectors(request, config_store, data=data)
    return {"status": "deleted"}
