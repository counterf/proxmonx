"""Task history API endpoints."""

import logging

from fastapi import APIRouter, Depends

from app.api.helpers import _get_task_store, _require_api_key

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/tasks", dependencies=[Depends(_require_api_key)])
async def list_tasks(
    limit: int = 200,
    task_store=Depends(_get_task_store),
) -> list[dict]:
    """Return recent task history, newest first."""
    return [r.model_dump() for r in task_store.list_recent(limit)]


@router.delete("/api/tasks", dependencies=[Depends(_require_api_key)])
async def clear_tasks(task_store=Depends(_get_task_store)) -> dict[str, str]:
    """Delete all task history."""
    task_store.clear()
    logger.info("Task history cleared")
    return {"status": "cleared"}
