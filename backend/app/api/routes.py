"""API route definitions."""

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.config import AppConfig, Settings
from app.core.discovery import DiscoveryEngine
from app.core.github import GitHubClient
from app.core.proxmox import ProxmoxClient
from app.core.scheduler import Scheduler
from app.core.ssh import SSHClient
from app.detectors.registry import ALL_DETECTORS, DETECTOR_MAP
from app.models.guest import GuestDetail, GuestSummary

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response models ---


class AppConfigEntry(BaseModel):
    port: int | None = None
    api_key: str | None = None
    scheme: str | None = None
    github_repo: str | None = None

    @field_validator("scheme")
    @classmethod
    def validate_scheme(cls, v: str | None) -> str | None:
        if v is not None and v not in ("http", "https"):
            raise ValueError("scheme must be 'http' or 'https'")
        return v

    @field_validator("github_repo")
    @classmethod
    def validate_github_repo(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if "github.com" in v or v.startswith("http"):
            raise ValueError("github_repo must be 'owner/repo' format, not a URL")
        if not re.match(r"^[^\s/]+/[^\s/]+$", v):
            raise ValueError("github_repo must match 'owner/repo' format")
        return v


class SettingsSaveRequest(BaseModel):
    proxmox_host: str
    proxmox_token_id: str
    proxmox_token_secret: str | None = None  # null = keep current
    proxmox_node: str
    poll_interval_seconds: int = 300
    discover_vms: bool = False
    verify_ssl: bool = False
    ssh_enabled: bool = True
    ssh_username: str = "root"
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    github_token: str | None = None
    log_level: str = "info"
    app_config: dict[str, AppConfigEntry] | None = None

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

    @field_validator("poll_interval_seconds")
    @classmethod
    def validate_poll_interval(cls, v: int) -> int:
        if v < 30 or v > 3600:
            raise ValueError("Poll interval must be between 30 and 3600 seconds")
        return v

    @field_validator("app_config")
    @classmethod
    def validate_app_config(
        cls, v: dict[str, AppConfigEntry] | None,
    ) -> dict[str, AppConfigEntry] | None:
        if v is None:
            return v
        for key, entry in v.items():
            if key not in DETECTOR_MAP:
                raise ValueError(f"Unknown app: {key}")
            if entry.port is not None and (entry.port < 1 or entry.port > 65535):
                raise ValueError(f"Port for {key} must be between 1 and 65535")
        return v


class ConnectionTestRequest(BaseModel):
    proxmox_host: str
    proxmox_token_id: str
    proxmox_token_secret: str
    proxmox_node: str
    verify_ssl: bool = False


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
async def list_guests(scheduler=Depends(_get_scheduler)) -> list[GuestSummary]:
    """List all discovered guests."""
    if scheduler is None:
        return []
    return [guest.to_summary() for guest in scheduler.guests.values()]


@router.get("/api/guests/{guest_id}")
async def get_guest(guest_id: str, scheduler=Depends(_get_scheduler)) -> GuestDetail:
    """Get detail for a single guest."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    guest = scheduler.guests.get(guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")
    return guest.to_detail()


@router.post("/api/refresh", status_code=202)
async def refresh(scheduler=Depends(_get_scheduler)) -> dict[str, str]:
    """Trigger an immediate re-discovery cycle."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    scheduler.trigger_refresh()
    return {"status": "started"}


@router.get("/api/settings")
async def get_settings(settings=Depends(_get_settings)) -> dict[str, str | int | bool | None]:
    """Return current settings with secrets masked."""
    return settings.masked_settings()


# --- New endpoints ---


@router.get("/api/setup/status")
async def setup_status(
    config_store=Depends(_get_config_store),
) -> dict[str, bool | list[str]]:
    """Return whether the app is configured and which fields are missing."""
    return {
        "configured": config_store.is_configured(),
        "missing_fields": config_store.get_missing_fields(),
    }


@router.get("/api/settings/full")
async def get_full_settings(
    settings=Depends(_get_settings),
) -> dict[str, Any]:
    """Return all settings with secrets masked."""
    # Mask API keys in app_config
    masked_app_config: dict[str, dict[str, Any]] = {}
    for app_name, cfg in settings.app_config.items():
        masked_app_config[app_name] = {
            "port": cfg.port,
            "api_key": "***" if cfg.api_key else None,
            "scheme": cfg.scheme,
            "github_repo": cfg.github_repo,
        }
    return {
        "proxmox_host": settings.proxmox_host,
        "proxmox_token_id": settings.proxmox_token_id,
        "proxmox_token_secret": "***" if settings.proxmox_token_secret else None,
        "proxmox_node": settings.proxmox_node,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "discover_vms": settings.discover_vms,
        "verify_ssl": settings.verify_ssl,
        "ssh_enabled": settings.ssh_enabled,
        "ssh_username": settings.ssh_username,
        "ssh_key_path": settings.ssh_key_path,
        "ssh_password": "***" if settings.ssh_password else None,
        "github_token": "***" if settings.github_token else None,
        "log_level": settings.log_level,
        "app_config": masked_app_config,
    }


@router.post("/api/settings/test-connection")
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


@router.post("/api/settings")
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

    # If token_secret is None, keep current value
    token_secret = body.proxmox_token_secret
    if token_secret is None:
        token_secret = current_file.get("proxmox_token_secret") or settings.proxmox_token_secret
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
    }

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
    new_client = httpx.AsyncClient(timeout=10.0, verify=new_settings.verify_ssl, follow_redirects=True)
    try:
        proxmox = ProxmoxClient(new_settings, http_client=new_client)
        github = GitHubClient(new_settings, http_client=new_client)
        ssh = SSHClient(new_settings)
        engine = DiscoveryEngine(proxmox, github, ssh, http_client=new_client, settings=new_settings)
        new_scheduler = Scheduler(new_settings, engine)
        new_scheduler.start()
        # Only update app state after successful start
        request.app.state.http_client = new_client
        request.app.dependency_overrides[_get_scheduler] = lambda: new_scheduler
        request.app.dependency_overrides[_get_settings] = lambda: new_settings
    except Exception as exc:
        await new_client.aclose()
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {exc}") from exc
    finally:
        # Close old client regardless of success/failure
        if old_client is not None:
            await old_client.aclose()

    return {"success": True, "message": "Settings saved"}
