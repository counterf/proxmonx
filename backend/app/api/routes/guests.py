"""Guest-related API endpoints."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.config import ProxmoxHostConfig, Settings
from app.core.proxmox import ProxmoxClient
from app.core.task_store import TaskRecord, TaskStore
from app.detectors.registry import DETECTOR_MAP
from app.core.ssh import OS_UPDATE_COMMANDS, SSHClient
from app.models.guest import GuestInfo

from app.api.helpers import (
    _AppConfigBase,
    _get_config_store,
    _get_scheduler,
    _get_settings,
    _get_task_store,
    _keep_or_replace,
    _reload_settings_into_engine,
    _require_api_key,
    run_app_update_bg,
    run_os_update_bg,
    _now_iso,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _poll_upid(
    task_store: TaskStore,
    host_config: ProxmoxHostConfig,
    task_id: str,
    upid: str,
    success_detail: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    guest_id: str | None = None,
    scheduler=None,
) -> None:
    """Background task: poll Proxmox for UPID completion and update the task record."""
    try:
        for _ in range(60):  # poll every 10s up to 10 min
            await asyncio.sleep(10)
            safe_client = http_client if (http_client and not http_client.is_closed) else None
            client = ProxmoxClient(host_config, http_client=safe_client)
            try:
                data = await client.get_task_status(upid)
            except Exception:
                continue
            if data.get("status") == "stopped":
                exitstatus = str(data.get("exitstatus", ""))
                succeeded = exitstatus == "OK"
                task_store.update(
                    task_id,
                    status="success" if succeeded else "failed",
                    detail=success_detail if succeeded else (exitstatus or upid),
                    finished_at=_now_iso(),
                )
                if succeeded and guest_id and scheduler:
                    scheduler.trigger_guest_refresh(guest_id)
                return
        # Timed out without completion — mark as failed
        task_store.update(
            task_id,
            status="failed",
            detail=f"{upid} (poll timed out after 10 min)",
            finished_at=_now_iso(),
        )
        if guest_id and scheduler:
            scheduler.trigger_guest_refresh(guest_id)
    except Exception:
        logger.exception("_poll_upid crashed for task %s", task_id)
        try:
            task_store.update(task_id, status="failed", detail="internal polling error", finished_at=_now_iso())
        except Exception:
            logger.warning("Failed to mark task %s as failed after _poll_upid crash", task_id, exc_info=True)


# --- Request/Response models ---


class GuestActionRequest(BaseModel):
    action: Literal["start", "stop", "shutdown", "restart", "snapshot"]
    snapshot_name: str | None = None


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


# --- Endpoints ---


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


@router.get("/api/guests/{guest_id}/config")
async def get_guest_config(
    guest_id: str,
    config_store=Depends(_get_config_store),
) -> dict[str, Any]:
    """Return per-guest config overrides (API keys masked)."""
    data = config_store.load()
    guest_cfg = data.get("guest_config", {}).get(guest_id, {})
    if guest_cfg.get("api_key") or guest_cfg.get("ssh_password"):
        guest_cfg = dict(guest_cfg)
        if guest_cfg.get("api_key"):
            guest_cfg["api_key"] = "***"
        if guest_cfg.get("ssh_password"):
            guest_cfg["ssh_password"] = "***"
    return guest_cfg


@router.put("/api/guests/{guest_id}/config", dependencies=[Depends(_require_api_key)])
async def save_guest_config(
    guest_id: str,
    body: GuestConfigSaveRequest,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict[str, str]:
    """Save per-guest configuration overrides."""
    # ssh_version_cmd safety is enforced by _AppConfigBase.validate_ssh_version_cmd

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

    if body.forced_detector is not None and body.forced_detector != "":
        merged["forced_detector"] = body.forced_detector
    if body.version_host is not None and body.version_host != "":
        merged["version_host"] = body.version_host
    # None means "clear" -- not added to merged, stripped below

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


@router.post("/api/guests/{guest_id}/action", dependencies=[Depends(_require_api_key)])
async def perform_guest_action(
    guest_id: str,
    body: GuestActionRequest,
    request: Request,
    scheduler=Depends(_get_scheduler),
    config_store=Depends(_get_config_store),
    task_store=Depends(_get_task_store),
) -> dict[str, str]:
    """Trigger a lifecycle action (start/stop/shutdown/restart/snapshot) on a guest."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    guest = scheduler.guests.get(guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")

    # Find matching host config
    data = config_store.load()
    hosts: list[dict] = data.get("proxmox_hosts", [])
    host_dict = next((h for h in hosts if h.get("id") == guest.host_id), None)
    if not host_dict:
        raise HTTPException(status_code=404, detail=f"Host config not found for host_id={guest.host_id!r}")

    # Build per-host client
    host_config = ProxmoxHostConfig(**host_dict)
    client = ProxmoxClient(host_config)

    # Map model guest_type ("vm") to Proxmox resource ("qemu")
    proxmox_type = "lxc" if guest.type == "lxc" else "qemu"
    vmid = guest.id.rsplit(":", 1)[-1]

    task_id = str(uuid4())
    task_store.create(TaskRecord(
        id=task_id, guest_id=guest_id, guest_name=guest.name,
        host_id=guest.host_id, action=body.action,
        status="pending", started_at=_now_iso(),
    ))

    try:
        snapshot_name = None
        if body.action == "snapshot":
            snapshot_name = body.snapshot_name or f"proxmon-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        upid = await client.guest_action(vmid, proxmox_type, body.action, snapshot_name)
        logger.info("Action %s on guest %s -> task %s", body.action, guest_id, upid)
        task_store.update(task_id, status="running", detail=upid)
        success_detail = f"Snapshot '{snapshot_name}' created" if snapshot_name else None
        http_client = getattr(request.app.state, "http_client", None)
        asyncio.create_task(_poll_upid(task_store, host_config, task_id, upid, success_detail, http_client=http_client, guest_id=guest_id, scheduler=scheduler))
        return {"status": "ok", "task": upid}
    except httpx.HTTPStatusError as exc:
        # Extract the Proxmox error message
        detail: str = exc.response.reason_phrase or f"Proxmox API error: {exc.response.status_code}"
        try:
            resp_body = exc.response.json()
            errors = resp_body.get("errors") or resp_body.get("message") or resp_body.get("data")
            if errors:
                detail = str(errors)
        except Exception:
            if exc.response.text:
                detail = exc.response.text.strip()
        task_store.update(task_id, status="failed", detail=detail, finished_at=_now_iso())
        # Proxmox uses 500 for logical conflicts (e.g. "already running", "already stopped").
        # Map those to 409 so the frontend shows the message rather than a generic error.
        status_code = 409 if exc.response.status_code == 500 else exc.response.status_code
        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as exc:
        task_store.update(task_id, status="failed", detail=str(exc), finished_at=_now_iso())
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/guests/{guest_id}/refresh", status_code=202, dependencies=[Depends(_require_api_key)])
async def refresh_guest(
    guest_id: str,
    scheduler=Depends(_get_scheduler),
) -> dict[str, str]:
    """Trigger a re-detection cycle for a single guest (fire-and-forget)."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    if not scheduler.trigger_guest_refresh(guest_id):
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")
    return {"status": "started"}


@router.post("/api/guests/{guest_id}/os-update", dependencies=[Depends(_require_api_key)])
async def os_update_guest(
    guest_id: str,
    batch_id: str | None = None,
    scheduler=Depends(_get_scheduler),
    config_store=Depends(_get_config_store),
    task_store=Depends(_get_task_store),
) -> dict[str, Any]:
    """Run OS package update inside an LXC container via pct exec (fire-and-forget)."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    guest = scheduler.guests.get(guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")
    if guest.type != "lxc":
        raise HTTPException(status_code=400, detail="OS update is only supported for LXC containers")
    if guest.status != "running":
        raise HTTPException(status_code=400, detail="Guest must be running to update OS")
    if not guest.os_type or guest.os_type not in OS_UPDATE_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unsupported OS type: {guest.os_type!r}")

    data = config_store.load()
    hosts: list[dict] = data.get("proxmox_hosts", [])
    host_dict = next((h for h in hosts if h.get("id") == guest.host_id), None)
    if not host_dict:
        raise HTTPException(status_code=404, detail=f"Host config not found for {guest.host_id!r}")

    host_config = ProxmoxHostConfig(**host_dict)
    if not host_config.pct_exec_enabled:
        raise HTTPException(status_code=400, detail="pct exec is not enabled for this host — enable it in Settings")

    if task_store.list_running_for_guest(guest_id, "os_update"):
        raise HTTPException(status_code=409, detail="An OS update is already running for this guest")

    ssh_settings = Settings(
        ssh_enabled=True,
        ssh_username=host_config.ssh_username,
        ssh_key_path=host_config.ssh_key_path,
        ssh_password=host_config.ssh_password,
    )
    ssh = SSHClient(ssh_settings)
    vmid = guest_id.rsplit(":", 1)[-1]

    task_id = str(uuid4())
    task_store.create(TaskRecord(
        id=task_id, guest_id=guest_id, guest_name=guest.name,
        host_id=guest.host_id, action="os_update",
        status="running", started_at=_now_iso(),
        batch_id=batch_id,
    ))

    try:
        asyncio.create_task(run_os_update_bg(
            task_id, guest_id, ssh, host_config, vmid, guest.os_type, scheduler, task_store,
        ))
    except Exception as exc:
        task_store.update(
            task_id,
            status="failed",
            detail=f"Failed to schedule OS update: {exc}",
            finished_at=_now_iso(),
        )
        raise HTTPException(status_code=500, detail="Failed to schedule OS update") from exc

    return {"task_id": task_id, "status": "running"}


@router.post("/api/guests/{guest_id}/app-update", dependencies=[Depends(_require_api_key)])
async def app_update_guest(
    guest_id: str,
    batch_id: str | None = None,
    scheduler=Depends(_get_scheduler),
    config_store=Depends(_get_config_store),
    task_store=Depends(_get_task_store),
) -> dict[str, Any]:
    """Run the community-script updater inside an LXC container via pct exec (fire-and-forget)."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    guest = scheduler.guests.get(guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")
    if guest.type != "lxc":
        raise HTTPException(status_code=400, detail="App update is only supported for LXC containers")
    if guest.status != "running":
        raise HTTPException(status_code=400, detail="Guest must be running to update app")
    if not guest.has_community_script:
        raise HTTPException(status_code=400, detail="/usr/bin/update not found on this container")

    data = config_store.load()
    hosts: list[dict] = data.get("proxmox_hosts", [])
    host_dict = next((h for h in hosts if h.get("id") == guest.host_id), None)
    if not host_dict:
        raise HTTPException(status_code=404, detail=f"Host config not found for {guest.host_id!r}")

    host_config = ProxmoxHostConfig(**host_dict)
    if not host_config.pct_exec_enabled:
        raise HTTPException(status_code=400, detail="pct exec is not enabled for this host — enable it in Settings")

    if task_store.list_running_for_guest(guest_id, "app_update"):
        raise HTTPException(status_code=409, detail="An app update is already running for this guest")

    ssh_settings = Settings(
        ssh_enabled=True,
        ssh_username=host_config.ssh_username,
        ssh_key_path=host_config.ssh_key_path,
        ssh_password=host_config.ssh_password,
    )
    ssh = SSHClient(ssh_settings)
    vmid = guest_id.rsplit(":", 1)[-1]

    task_id = str(uuid4())
    task_store.create(TaskRecord(
        id=task_id, guest_id=guest_id, guest_name=guest.name,
        host_id=guest.host_id, action="app_update",
        status="running", started_at=_now_iso(),
        batch_id=batch_id,
    ))

    try:
        asyncio.create_task(run_app_update_bg(
            task_id, guest_id, ssh, host_config, vmid, scheduler, task_store,
        ))
    except Exception as exc:
        task_store.update(
            task_id,
            status="failed",
            detail=f"Failed to schedule app update: {exc}",
            finished_at=_now_iso(),
        )
        raise HTTPException(status_code=500, detail="Failed to schedule app update") from exc

    return {"task_id": task_id, "status": "running"}


@router.post("/api/guests/{guest_id}/backup", dependencies=[Depends(_require_api_key)])
async def backup_guest(
    guest_id: str,
    request: Request,
    scheduler=Depends(_get_scheduler),
    config_store=Depends(_get_config_store),
    task_store=Depends(_get_task_store),
) -> dict[str, str]:
    """Trigger a vzdump backup via the Proxmox API. Returns UPID immediately."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    guest = scheduler.guests.get(guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")

    data = config_store.load()
    hosts: list[dict] = data.get("proxmox_hosts", [])
    host_dict = next((h for h in hosts if h.get("id") == guest.host_id), None)
    if not host_dict:
        raise HTTPException(status_code=404, detail=f"Host config not found for {guest.host_id!r}")

    host_config = ProxmoxHostConfig(**host_dict)
    if not host_config.backup_storage:
        raise HTTPException(status_code=400, detail="No backup storage configured for this host — set it in Settings")

    client = ProxmoxClient(host_config)
    vmid = guest_id.rsplit(":", 1)[-1]

    task_id = str(uuid4())
    task_store.create(TaskRecord(
        id=task_id, guest_id=guest_id, guest_name=guest.name,
        host_id=guest.host_id, action="backup",
        status="pending", started_at=_now_iso(),
    ))

    try:
        upid = await client.create_backup(vmid, host_config.backup_storage)
        logger.info("Backup queued for guest %s -> %s", guest_id, upid)
        task_store.update(task_id, status="running", detail=upid)
        http_client = getattr(request.app.state, "http_client", None)
        asyncio.create_task(_poll_upid(task_store, host_config, task_id, upid, f"Backed up to {host_config.backup_storage}", http_client=http_client, guest_id=guest_id, scheduler=scheduler))
        return {"status": "ok", "task": upid}
    except httpx.HTTPStatusError as exc:
        detail: str = exc.response.reason_phrase or f"Proxmox API error: {exc.response.status_code}"
        try:
            body_data = exc.response.json()
            errors = body_data.get("errors") or body_data.get("message") or body_data.get("data")
            if errors:
                detail = str(errors)
        except Exception:
            if exc.response.text:
                detail = exc.response.text.strip()
        task_store.update(task_id, status="failed", detail=detail, finished_at=_now_iso())
        status_code = 409 if exc.response.status_code == 500 else exc.response.status_code
        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as exc:
        task_store.update(task_id, status="failed", detail=str(exc), finished_at=_now_iso())
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/refresh", status_code=202, dependencies=[Depends(_require_api_key)])
async def refresh(scheduler=Depends(_get_scheduler)) -> dict[str, str | None]:
    """Trigger an immediate re-discovery cycle."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    if scheduler.is_running:
        return {"status": "busy", "snapshot_at": None}
    snapshot = scheduler.last_poll
    scheduler.trigger_refresh()
    return {"status": "started", "snapshot_at": snapshot.isoformat() if snapshot else None}
