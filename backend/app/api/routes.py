"""API route definitions."""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.config import Settings
from app.core.discovery import DiscoveryEngine
from app.core.github import GitHubClient
from app.core.proxmox import ProxmoxClient
from app.core.scheduler import Scheduler
from app.core.ssh import SSHClient
from app.models.guest import GuestDetail, GuestSummary

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response models ---


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
) -> dict[str, str | int | bool | None]:
    """Return all settings with secrets masked."""
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


@router.post("/api/settings")
async def save_settings(
    body: SettingsSaveRequest,
    request: Request,
    settings=Depends(_get_settings),
    config_store=Depends(_get_config_store),
    scheduler=Depends(_get_scheduler),
) -> dict[str, bool | str]:
    """Save settings to config file, reload, and restart scheduler."""
    # If token_secret is None, keep current value
    token_secret = body.proxmox_token_secret
    if token_secret is None:
        current_data = config_store.load()
        token_secret = current_data.get("proxmox_token_secret") or settings.proxmox_token_secret
        if not token_secret:
            raise HTTPException(
                status_code=422,
                detail="Token secret is required (no existing value found)",
            )

    # Build config data to persist
    config_data: dict[str, str | int | bool | None] = {
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
        "ssh_password": body.ssh_password,
        "github_token": body.github_token,
        "log_level": body.log_level,
    }

    # Write to config file
    try:
        config_store.save(config_data)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Reload settings from merged config + env
    new_settings = Settings()
    file_data = config_store.load()
    current_dict = new_settings.model_dump()
    for key, value in file_data.items():
        if key in current_dict and value is not None:
            current_dict[key] = value
    new_settings = Settings(**current_dict)

    # Update the dependency overrides with new settings
    request.app.dependency_overrides[_get_settings] = lambda: new_settings

    # Stop existing scheduler if running
    if scheduler is not None:
        await scheduler.stop()

    # Start new scheduler with new settings
    http_client = httpx.AsyncClient(timeout=10.0, verify=new_settings.verify_ssl)
    # Replace http_client on app state (close old one if exists)
    old_client = getattr(request.app.state, "http_client", None)
    request.app.state.http_client = http_client

    proxmox = ProxmoxClient(new_settings, http_client=http_client)
    github = GitHubClient(new_settings, http_client=http_client)
    ssh = SSHClient(new_settings)
    engine = DiscoveryEngine(proxmox, github, ssh, http_client=http_client)
    new_scheduler = Scheduler(new_settings, engine)

    request.app.dependency_overrides[_get_scheduler] = lambda: new_scheduler
    new_scheduler.start()

    # Close old http client after new one is set up
    if old_client is not None:
        await old_client.aclose()

    return {"success": True, "message": "Settings saved"}
