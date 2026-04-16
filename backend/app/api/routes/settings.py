"""Settings-related API endpoints."""

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.core.auth import hash_password
from app.core.github import GitHubClient
from app.core.notifier import NtfyNotifier
from app.detectors.registry import ALL_DETECTORS, DETECTOR_MAP

from app.api.helpers import (
    _AppConfigBase,
    _EXCLUDED_FIELDS,
    _NESTED_SECRET_FIELDS,
    _TOP_SECRET_FIELDS,
    _get_config_store,
    _get_scheduler,
    _get_settings,
    _keep_or_replace,
    _mask,
    _require_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response models ---


class AppConfigEntry(_AppConfigBase):
    """Per-app config entry sent by the frontend."""


class ProxmoxHostSaveEntry(BaseModel):
    id: str
    label: str
    host: str
    token_id: str
    token_secret: str | None = None  # None / "***" = keep current
    node: str
    ssh_username: str = "root"
    ssh_password: str | None = None
    ssh_key: str | None = None
    pct_exec_enabled: bool = False
    backup_storage: str | None = None

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
    poll_interval_seconds: int = Field(default=3600, ge=30, le=86400)
    pending_updates_interval_seconds: int = Field(default=3600, ge=3600, le=86400)
    discover_vms: bool = False
    ssh_enabled: bool = True
    ssh_username: str = "root"
    ssh_key: str | None = None
    ssh_password: str | None = None
    github_token: str | None = None
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
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


class NotificationTestRequest(BaseModel):
    ntfy_url: str | None = None
    ntfy_token: str | None = None
    ntfy_priority: int | None = None


class GitHubTestRequest(BaseModel):
    repo: str


class GitHubTestResponse(BaseModel):
    ok: bool
    repo: str
    version: str | None = None
    source: str | None = None
    reason: str | None = None


class ConnectionTestRequest(BaseModel):
    host: str
    token_id: str
    token_secret: str
    node: str
    host_id: str | None = None

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Proxmox host is required")
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


def _apply_auth_settings(
    body: SettingsSaveRequest,
    existing: dict[str, Any],
    config_data: dict[str, Any],
) -> None:
    """Apply auth-related fields (mode, username, password hash) to config_data.

    Preserves existing values when the request omits them.
    """
    if body.auth_mode is not None:
        config_data["auth_mode"] = body.auth_mode
    else:
        config_data["auth_mode"] = existing.get("auth_mode", "disabled")
    if body.auth_username is not None:
        config_data["auth_username"] = body.auth_username
    else:
        config_data["auth_username"] = existing.get("auth_username", "root")
    # Password hash: set from new_password when provided, otherwise preserve existing.
    existing_hash = existing.get("auth_password_hash", "")
    target_auth_mode = config_data.get("auth_mode", "disabled")
    if target_auth_mode == "forms" and not config_data.get("auth_username", "").strip():
        raise HTTPException(
            status_code=422,
            detail="Cannot enable forms auth without setting a username",
        )
    if target_auth_mode == "forms" and not existing_hash and not body.new_password:
        raise HTTPException(
            status_code=422,
            detail="Cannot enable forms auth without setting a password",
        )
    if target_auth_mode == "forms" and body.new_password:
        config_data["auth_password_hash"] = hash_password(body.new_password)
    elif existing_hash:
        config_data["auth_password_hash"] = existing_hash


def _apply_notification_settings(
    body: SettingsSaveRequest,
    existing: dict[str, Any],
    config_data: dict[str, Any],
) -> None:
    """Apply notification-related fields to config_data.

    Preserves existing values when the request omits them.
    """
    if body.notifications_enabled is not None:
        config_data["notifications_enabled"] = body.notifications_enabled
    else:
        config_data["notifications_enabled"] = existing.get("notifications_enabled", False)
    if body.ntfy_url is not None:
        config_data["ntfy_url"] = body.ntfy_url
    else:
        config_data["ntfy_url"] = existing.get("ntfy_url", "")
    config_data["ntfy_token"] = _keep_or_replace(
        body.ntfy_token, existing.get("ntfy_token"),
    ) or ""
    if body.ntfy_priority is not None:
        config_data["ntfy_priority"] = body.ntfy_priority
    else:
        config_data["ntfy_priority"] = existing.get("ntfy_priority", 3)
    if body.notify_disk_threshold is not None:
        config_data["notify_disk_threshold"] = body.notify_disk_threshold
    else:
        config_data["notify_disk_threshold"] = existing.get("notify_disk_threshold", 95)
    if body.notify_disk_cooldown_minutes is not None:
        config_data["notify_disk_cooldown_minutes"] = body.notify_disk_cooldown_minutes
    else:
        config_data["notify_disk_cooldown_minutes"] = existing.get("notify_disk_cooldown_minutes", 60)
    if body.notify_on_outdated is not None:
        config_data["notify_on_outdated"] = body.notify_on_outdated
    else:
        config_data["notify_on_outdated"] = existing.get("notify_on_outdated", True)


# --- Endpoints ---


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


@router.get("/api/setup/status")
async def setup_status(
    config_store=Depends(_get_config_store),
) -> dict[str, bool]:
    """Return whether the app is configured."""
    return {
        "configured": config_store.is_configured(),
    }


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
    result["auth_password_set"] = bool(config_store.load_auth().get("auth_password_hash"))
    return result


@router.get("/api/settings/hosts/{host_id}/backup-storages", dependencies=[Depends(_require_api_key)])
async def list_host_backup_storages(
    host_id: str,
    config_store=Depends(_get_config_store),
) -> list[dict] | dict:
    """Return Proxmox storages that support backup content for the given host."""
    from app.config import ProxmoxHostConfig
    from app.core.proxmox import ProxmoxClient

    host_dict = config_store.get_host(host_id)
    if not host_dict:
        return {"error": f"Host {host_id!r} not found"}

    try:
        host_config = ProxmoxHostConfig(**host_dict)
        client = ProxmoxClient(host_config)
        storages = await client.list_backup_storages()
        return storages
    except Exception as exc:
        logger.warning("Failed to list backup storages for host %s: %s", host_id, exc)
        return {"error": str(exc)}


@router.post("/api/settings/test-connection", dependencies=[Depends(_require_api_key)])
async def test_connection(
    body: ConnectionTestRequest,
    config_store=Depends(_get_config_store),
) -> dict[str, bool | str | dict[str, str | int | float | bool | None] | None]:
    """Test Proxmox connectivity without saving settings."""
    token_secret = body.token_secret
    if token_secret == "***" and body.host_id is not None:
        host_dict = config_store.get_host(body.host_id)
        if host_dict is None:
            return {"success": False, "message": "Saved host not found", "node_info": None}
        token_secret = host_dict.get("token_secret", "")
    base_url = f"{body.host.rstrip('/')}/api2/json"
    headers = {
        "Authorization": f"PVEAPIToken={body.token_id}={token_secret}",
    }
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            # Test with /version endpoint
            resp = await client.get(f"{base_url}/version", headers=headers)
            resp.raise_for_status()
            version_data = resp.json().get("data", {})

            # Also check the node exists
            node_resp = await client.get(
                f"{base_url}/nodes/{body.node}/status",
                headers=headers,
            )
            node_resp.raise_for_status()
            node_data = node_resp.json().get("data", {})

            pve_version = version_data.get("version", "unknown") if isinstance(version_data, dict) else "unknown"

            return {
                "success": True,
                "message": f"Connected to Proxmox {pve_version} on node {body.node}",
                "node_info": {
                    "pve_version": pve_version,
                    "node": body.node,
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
        msg = f"Connection refused: {body.host}"
        logger.warning("Connection test failed: %s", msg)
        return {"success": False, "message": msg, "node_info": None}
    except httpx.TimeoutException:
        msg = f"Connection timed out: {body.host}"
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
async def get_app_config_defaults() -> list[dict[str, str | int | bool | None]]:
    """Return the list of supported apps with default ports and API key support."""
    return [
        {
            "name": d.name,
            "display_name": d.display_name,
            "default_port": d.default_port,
            "accepts_api_key": d.accepts_api_key,
            "github_repo": d.github_repo,
        }
        for d in ALL_DETECTORS
    ]


@router.post("/api/settings", dependencies=[Depends(_require_api_key)])
async def save_settings(
    body: SettingsSaveRequest,
    request: Request,
    settings=Depends(_get_settings),
    config_store=Depends(_get_config_store),
    scheduler=Depends(_get_scheduler),
) -> dict[str, bool | str]:
    """Save settings to config file, reload, and restart scheduler."""
    # Read existing scalars once to preserve values for mask-aware fields
    current_file = config_store.load()

    # Build scalar config data to persist
    config_data: dict[str, Any] = {
        "poll_interval_seconds": body.poll_interval_seconds,
        "pending_updates_interval_seconds": body.pending_updates_interval_seconds,
        "discover_vms": body.discover_vms,
        "ssh_enabled": body.ssh_enabled,
        "ssh_username": body.ssh_username,
        "ssh_key": _keep_or_replace(body.ssh_key, current_file.get("ssh_key")),
        "ssh_password": _keep_or_replace(body.ssh_password, current_file.get("ssh_password")),
        "github_token": _keep_or_replace(body.github_token, current_file.get("github_token")),
        "log_level": body.log_level,
        "version_detect_method": body.version_detect_method,
    }

    # Auth settings
    _apply_auth_settings(body, current_file, config_data)

    # Notification settings
    _apply_notification_settings(body, current_file, config_data)

    # API key (mask-aware) and trust proxy headers
    config_data["proxmon_api_key"] = _keep_or_replace(
        body.proxmon_api_key, current_file.get("proxmon_api_key"),
    )
    if body.trust_proxy_headers is not None:
        config_data["trust_proxy_headers"] = body.trust_proxy_headers
    else:
        config_data["trust_proxy_headers"] = current_file.get("trust_proxy_headers", False)

    # Build hosts list for atomic save
    hosts_to_save: list[dict] | None = None
    if body.proxmox_hosts is not None:
        # Validate token_secret is provided for new hosts
        existing_host_ids = {h["id"] for h in config_store.list_hosts()}
        for entry in body.proxmox_hosts:
            is_new = entry.id not in existing_host_ids
            if is_new and (not entry.token_secret or entry.token_secret == "***"):
                raise HTTPException(
                    status_code=422,
                    detail=f"token_secret is required for new host '{entry.id}'",
                )
            if not is_new and entry.token_secret == "":
                entry.token_secret = None  # preserve existing secret via CRUD layer
        hosts_to_save = [entry.model_dump() for entry in body.proxmox_hosts]

    # Build app config dict for atomic save
    app_configs_to_save: dict[str, dict] | None = None
    if body.app_config is not None:
        app_configs_to_save = {}
        for app_name, entry in body.app_config.items():
            prev = config_store.get_app_config(app_name) or {}
            merged_entry: dict[str, Any] = {}
            if entry.port is not None:
                # 0 is the clear sentinel — maps to NULL in DB
                merged_entry["port"] = entry.port if entry.port != 0 else None
            # Non-secret optional fields: None = keep, "" = clear to NULL
            for field in ("scheme", "github_repo", "ssh_version_cmd", "ssh_username"):
                val = getattr(entry, field)
                if val is None:
                    if prev.get(field) is not None:
                        merged_entry[field] = prev[field]
                elif val == "":
                    merged_entry[field] = None  # explicit clear — present in dict prevents CRUD re-fill
                else:
                    merged_entry[field] = val
            # Secret fields: pass through, CRUD handles "***"/None preservation
            merged_entry["api_key"] = entry.api_key
            merged_entry["ssh_password"] = entry.ssh_password
            merged_entry["ssh_key"] = entry.ssh_key
            # Check for meaningful content: ignore None-valued secret placeholders,
            # but also check prev for existing secrets to avoid silent deletion
            _secret_names = ("api_key", "ssh_password", "ssh_key")
            has_content = any(
                v is not None for k, v in merged_entry.items()
                if k not in _secret_names
            ) or any(
                merged_entry.get(s) not in (None, "***", "")
                for s in _secret_names
            ) or any(
                prev.get(s) not in (None, "", "***") and merged_entry.get(s) not in ("",)
                for s in _secret_names
            )
            if has_content:
                app_configs_to_save[app_name] = merged_entry
            # Omitted apps are deleted by save_full()'s replace-all semantics
        changed_apps = list(body.app_config.keys())
        if changed_apps:
            logger.info("App config updated for: %s", ", ".join(changed_apps))

    # Atomic save: scalars + hosts + app configs in one transaction
    try:
        config_store.save_full(config_data, hosts=hosts_to_save, app_configs=app_configs_to_save)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Reload settings: config file values take priority over env/defaults
    new_settings = config_store.merge_into_settings(Settings())

    is_configured = config_store.is_configured()

    # Stop existing scheduler if running
    if scheduler is not None:
        await scheduler.stop()

    old_client: httpx.AsyncClient | None = getattr(request.app.state, "http_client", None)

    if not is_configured:
        # Unconfigured: install null scheduler, don't transfer guest cache
        request.app.state.http_client = None
        request.app.state.scheduler = None
        request.app.dependency_overrides[_get_scheduler] = lambda: None
        request.app.dependency_overrides[_get_settings] = lambda: new_settings
        request.app.state.settings = new_settings
        if old_client is not None:
            await old_client.aclose()
        return {"success": True, "message": "Settings saved"}

    from app.main import build_runtime
    new_client, new_scheduler = build_runtime(new_settings)
    # Transfer cached guest state so the dashboard doesn't go blank after save
    if scheduler is not None:
        new_scheduler._guests = scheduler._guests
    try:
        new_scheduler.start()
        # Swap succeeded — install new runtime and close old client
        request.app.state.http_client = new_client
        request.app.state.scheduler = new_scheduler
        request.app.dependency_overrides[_get_scheduler] = lambda: new_scheduler
        request.app.dependency_overrides[_get_settings] = lambda: new_settings
        request.app.state.settings = new_settings
        if old_client is not None:
            await old_client.aclose()
    except Exception as exc:
        await new_client.aclose()
        # Attempt to restart the old scheduler so the app isn't left dead
        if scheduler is not None and old_client is not None and not old_client.is_closed:
            try:
                scheduler.start()
            except Exception:
                logger.warning("Failed to restart old scheduler after new scheduler failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {exc}") from exc

    return {"success": True, "message": "Settings saved"}


@router.post("/api/notifications/test", dependencies=[Depends(_require_api_key)])
async def test_notification(
    body: NotificationTestRequest | None = None,
    settings=Depends(_get_settings),
) -> dict[str, bool | str]:
    """Send a test notification to verify ntfy connectivity."""
    # Resolve effective values: body overrides persisted settings
    url = (body.ntfy_url if body and body.ntfy_url is not None else None) or settings.ntfy_url
    token_from_body = body.ntfy_token if body else None
    if token_from_body is None or token_from_body == "***":
        token = settings.ntfy_token
    else:
        token = token_from_body
    priority = (body.ntfy_priority if body and body.ntfy_priority is not None else None) or settings.ntfy_priority

    if not url:
        return {"success": False, "message": "ntfy URL is not configured"}

    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        notifier = NtfyNotifier(
            url=url,
            token=token,
            priority=priority,
            http_client=client,
        )
        sent = await notifier.send(
            title="proxmon Test",
            message="This is a test notification from proxmon.",
            tags="white_check_mark",
        )
    if sent:
        return {"success": True, "message": "Test notification sent successfully"}
    return {"success": False, "message": "Failed to send notification -- check ntfy URL and token"}
