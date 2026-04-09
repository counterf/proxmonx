"""Bulk job API endpoints."""

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.helpers import (
    _get_bulk_job_store,
    _get_config_store,
    _get_scheduler,
    _get_task_store,
    _require_api_key,
    run_app_update_bg,
    run_os_update_bg,
    _now_iso,
)
from app.config import ProxmoxHostConfig, Settings
from app.core.bulk_job_store import BulkJob, BulkJobResult, BulkJobStore
from app.core.task_store import TaskRecord, TaskStore

logger = logging.getLogger(__name__)
router = APIRouter()


class StartBulkJobRequest(BaseModel):
    action: str  # os_update | app_update
    guest_ids: list[str]


async def _run_bulk_job(
    job_id: str,
    action: str,
    guest_ids: list[str],
    scheduler: Any,
    task_store: TaskStore,
    bulk_job_store: BulkJobStore,
    config_store: Any,
) -> None:
    """Background coroutine: process guests sequentially, update job state."""
    from app.core.ssh import OS_UPDATE_COMMANDS, SSHClient

    bulk_job_store.update(job_id, status="running", started_at=_now_iso())

    # Phase 1: create all TaskRecords upfront as "pending"
    task_ids: dict[str, str] = {}
    for guest_id in guest_ids:
        task_id = str(uuid.uuid4())
        guest = scheduler.guests.get(guest_id)
        guest_name = guest.name if guest else guest_id
        host_id = guest.host_id if guest else ""
        task_store.create(TaskRecord(
            id=task_id,
            guest_id=guest_id,
            guest_name=guest_name,
            host_id=host_id,
            action=action,
            status="pending",
            started_at=_now_iso(),
            batch_id=job_id,
        ))
        task_ids[guest_id] = task_id

    # Phase 2: process sequentially
    for guest_id in guest_ids:
        task_id = task_ids[guest_id]
        guest = scheduler.guests.get(guest_id)

        if not guest:
            task_store.update(task_id, status="failed", detail="Guest not found", finished_at=_now_iso())
            bulk_job_store.update_result(job_id, guest_id, "failed", error="Guest not found")
            continue

        if guest.type != "lxc" or guest.status != "running":
            task_store.update(task_id, status="skipped", detail="Guest not eligible", finished_at=_now_iso())
            bulk_job_store.update_result(job_id, guest_id, "skipped", error="Guest not eligible")
            continue

        if action == "os_update" and (not guest.os_type or guest.os_type not in OS_UPDATE_COMMANDS):
            task_store.update(task_id, status="skipped", detail=f"Unsupported OS: {guest.os_type!r}", finished_at=_now_iso())
            bulk_job_store.update_result(job_id, guest_id, "skipped", error=f"Unsupported OS: {guest.os_type!r}")
            continue

        if action == "app_update" and not guest.has_community_script:
            task_store.update(task_id, status="skipped", detail="/usr/bin/update not found on this container", finished_at=_now_iso())
            bulk_job_store.update_result(job_id, guest_id, "skipped", error="/usr/bin/update not found on this container")
            continue

        # Resolve host config
        try:
            settings_data = config_store.load()
            proxmox_hosts = settings_data.get("proxmox_hosts", [])
            host_dict = next((h for h in proxmox_hosts if h.get("id") == guest.host_id), None)
            if not host_dict:
                raise ValueError(f"Host config not found for {guest.host_id}")
            host_config = ProxmoxHostConfig(**host_dict)
        except Exception as exc:
            task_store.update(task_id, status="failed", detail=str(exc), finished_at=_now_iso())
            bulk_job_store.update_result(job_id, guest_id, "failed", error=str(exc))
            continue

        if not host_config.pct_exec_enabled:
            task_store.update(task_id, status="skipped", detail="pct exec not enabled", finished_at=_now_iso())
            bulk_job_store.update_result(job_id, guest_id, "skipped", error="pct exec not enabled")
            continue

        vmid = guest_id.rsplit(":", 1)[-1]

        ssh_settings = Settings(
            ssh_enabled=True,
            ssh_username=host_config.ssh_username or "root",
            ssh_key_path=host_config.ssh_key_path or "",
            ssh_password=host_config.ssh_password or "",
        )
        ssh = SSHClient(ssh_settings)

        try:
            if action == "os_update":
                if task_store.list_running_for_guest(guest_id, "os_update"):
                    task_store.update(task_id, status="skipped", detail="Update already in progress", finished_at=_now_iso())
                    bulk_job_store.update_result(job_id, guest_id, "skipped", error="Update already in progress")
                    continue
                task_store.update(task_id, status="running")
                await run_os_update_bg(
                    task_id=task_id,
                    guest_id=guest_id,
                    ssh=ssh,
                    host_config=host_config,
                    vmid=vmid,
                    os_type=guest.os_type or "",
                    scheduler=scheduler,
                    task_store=task_store,
                )
            else:
                if task_store.list_running_for_guest(guest_id, "app_update"):
                    task_store.update(task_id, status="skipped", detail="Update already in progress", finished_at=_now_iso())
                    bulk_job_store.update_result(job_id, guest_id, "skipped", error="Update already in progress")
                    continue
                task_store.update(task_id, status="running")
                await run_app_update_bg(
                    task_id=task_id,
                    guest_id=guest_id,
                    ssh=ssh,
                    host_config=host_config,
                    vmid=vmid,
                    scheduler=scheduler,
                    task_store=task_store,
                )
        except Exception as exc:
            logger.exception("Bulk job %s: error processing guest %s", job_id, guest_id)
            task_store.update(task_id, status="failed", detail=str(exc), finished_at=_now_iso())

        task = task_store.get(task_id)
        if task:
            bulk_job_store.update_result(job_id, guest_id, task.status, task_id=task_id)

    # Phase 3: finalize
    job = bulk_job_store.get(job_id)
    if job:
        final = "completed" if job.failed == 0 else "failed"
        bulk_job_store.update(job_id, status=final, finished_at=_now_iso())


@router.post("/api/bulk-jobs", dependencies=[Depends(_require_api_key)])
async def start_bulk_job(
    request_body: StartBulkJobRequest,
    bulk_job_store: BulkJobStore = Depends(_get_bulk_job_store),
    task_store: TaskStore = Depends(_get_task_store),
    scheduler=Depends(_get_scheduler),
    config_store=Depends(_get_config_store),
) -> dict:
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Proxmon is not configured yet")
    if request_body.action not in ("os_update", "app_update"):
        raise HTTPException(status_code=400, detail="action must be os_update or app_update")
    if not request_body.guest_ids:
        raise HTTPException(status_code=400, detail="guest_ids must not be empty")

    job_id = str(uuid.uuid4())
    guest_ids = request_body.guest_ids
    results = {gid: BulkJobResult(status="pending") for gid in guest_ids}

    job = BulkJob(
        id=job_id,
        action=request_body.action,
        status="pending",
        guest_ids=guest_ids,
        results=results,
        total=len(guest_ids),
        created_at=_now_iso(),
    )
    bulk_job_store.create(job)

    asyncio.create_task(_run_bulk_job(
        job_id=job_id,
        action=request_body.action,
        guest_ids=guest_ids,
        scheduler=scheduler,
        task_store=task_store,
        bulk_job_store=bulk_job_store,
        config_store=config_store,
    ))

    return {"job_id": job_id, "status": "pending"}


@router.get("/api/bulk-jobs/{job_id}", dependencies=[Depends(_require_api_key)])
async def get_bulk_job(
    job_id: str,
    bulk_job_store: BulkJobStore = Depends(_get_bulk_job_store),
) -> dict:
    job = bulk_job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Bulk job not found")
    return job.model_dump()


@router.get("/api/bulk-jobs", dependencies=[Depends(_require_api_key)])
async def list_bulk_jobs(
    bulk_job_store: BulkJobStore = Depends(_get_bulk_job_store),
) -> list[dict]:
    return [j.model_dump() for j in bulk_job_store.list_recent()]
