"""Bulk job API endpoints."""

import asyncio
import logging
import uuid
from itertools import groupby
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.helpers import (
    _get_config_store,
    _get_scheduler,
    _get_task_store,
    _now_iso,
    _require_api_key,
    run_app_update_bg,
    run_os_update_bg,
)
from app.config import ProxmoxHostConfig, Settings
from app.core.task_store import TaskRecord, TaskStore

logger = logging.getLogger(__name__)
router = APIRouter()


class StartBulkJobRequest(BaseModel):
    action: str  # os_update | app_update
    guest_ids: list[str]


def _build_bulk_job(batch_id: str, tasks: list[TaskRecord]) -> dict:
    terminal = {"success", "failed", "skipped"}
    results = {
        t.guest_id: {
            "status": t.status,
            "task_id": t.id,
            "error": t.detail if t.status in ("failed", "skipped") else None,
        }
        for t in tasks
    }
    total = len(tasks)
    failed = sum(1 for t in tasks if t.status == "failed")
    skipped = sum(1 for t in tasks if t.status == "skipped")
    completed = sum(1 for t in tasks if t.status in terminal)
    any_running = any(t.status in {"pending", "running"} for t in tasks)
    job_status = "running" if any_running else ("failed" if failed > 0 else "completed")
    non_pending = [t.started_at for t in tasks if t.status != "pending"]
    finished = [t.finished_at for t in tasks if t.finished_at and t.status in terminal]
    all_done = all(t.status in terminal for t in tasks)
    return {
        "id": batch_id,
        "action": tasks[0].action,
        "status": job_status,
        "guest_ids": [t.guest_id for t in tasks],
        "results": results,
        "total": total,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "created_at": min(t.started_at for t in tasks),
        "started_at": min(non_pending) if non_pending else None,
        "finished_at": max(finished) if all_done and finished else None,
    }


async def _run_bulk_job(
    job_id: str,
    action: str,
    guest_ids: list[str],
    task_ids: dict[str, str],
    scheduler: Any,
    task_store: TaskStore,
    config_store: Any,
) -> None:
    """Background coroutine: process guests sequentially."""
    from app.core.ssh import OS_UPDATE_COMMANDS, SSHClient

    for guest_id in guest_ids:
        task_id = task_ids[guest_id]
        guest = scheduler.guests.get(guest_id)

        if not guest:
            task_store.update(task_id, status="failed", detail="Guest not found", finished_at=_now_iso())
            continue

        if guest.type != "lxc" or guest.status != "running":
            task_store.update(task_id, status="skipped", detail="Guest not eligible", finished_at=_now_iso())
            continue

        if action == "os_update" and (not guest.os_type or guest.os_type not in OS_UPDATE_COMMANDS):
            task_store.update(
                task_id,
                status="skipped",
                detail=f"Unsupported OS: {guest.os_type!r}",
                finished_at=_now_iso(),
            )
            continue

        if action == "app_update" and not guest.has_community_script:
            task_store.update(
                task_id,
                status="skipped",
                detail="/usr/bin/update not found on this container",
                finished_at=_now_iso(),
            )
            continue

        try:
            settings_data = config_store.load()
            proxmox_hosts = settings_data.get("proxmox_hosts", [])
            host_dict = next((h for h in proxmox_hosts if h.get("id") == guest.host_id), None)
            if not host_dict:
                raise ValueError(f"Host config not found for {guest.host_id}")
            host_config = ProxmoxHostConfig(**host_dict)
        except Exception as exc:
            task_store.update(task_id, status="failed", detail=str(exc), finished_at=_now_iso())
            continue

        if not host_config.pct_exec_enabled:
            task_store.update(task_id, status="skipped", detail="pct exec not enabled", finished_at=_now_iso())
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
                    task_store.update(
                        task_id,
                        status="skipped",
                        detail="Update already in progress",
                        finished_at=_now_iso(),
                    )
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
                    task_store.update(
                        task_id,
                        status="skipped",
                        detail="Update already in progress",
                        finished_at=_now_iso(),
                    )
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


@router.post("/api/bulk-jobs", dependencies=[Depends(_require_api_key)])
async def start_bulk_job(
    request_body: StartBulkJobRequest,
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
    task_ids: dict[str, str] = {}
    for guest_id in request_body.guest_ids:
        task_id = str(uuid.uuid4())
        guest = scheduler.guests.get(guest_id)
        guest_name = guest.name if guest else guest_id
        host_id = guest.host_id if guest else ""
        task_store.create(
            TaskRecord(
                id=task_id,
                guest_id=guest_id,
                guest_name=guest_name,
                host_id=host_id,
                action=request_body.action,
                status="pending",
                started_at=_now_iso(),
                batch_id=job_id,
            )
        )
        task_ids[guest_id] = task_id

    asyncio.create_task(
        _run_bulk_job(
            job_id=job_id,
            action=request_body.action,
            guest_ids=request_body.guest_ids,
            task_ids=task_ids,
            scheduler=scheduler,
            task_store=task_store,
            config_store=config_store,
        )
    )
    return {"job_id": job_id, "status": "pending"}


@router.get("/api/bulk-jobs/{job_id}", dependencies=[Depends(_require_api_key)])
async def get_bulk_job(
    job_id: str,
    task_store: TaskStore = Depends(_get_task_store),
) -> dict:
    tasks = task_store.list_by_batch_id(job_id)
    if not tasks:
        raise HTTPException(status_code=404, detail="Bulk job not found")
    return _build_bulk_job(job_id, tasks)


@router.get("/api/bulk-jobs", dependencies=[Depends(_require_api_key)])
async def list_bulk_jobs(
    task_store: TaskStore = Depends(_get_task_store),
) -> list[dict]:
    all_tasks = task_store.list_recent_batched_tasks(50)
    jobs = []
    for batch_id, group in groupby(all_tasks, key=lambda t: t.batch_id):
        tasks = list(group)
        jobs.append(_build_bulk_job(batch_id, tasks))
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return jobs
