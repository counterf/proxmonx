"""API route definitions."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.models.guest import GuestDetail, GuestSummary

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_scheduler():
    """Dependency placeholder -- overridden in main.py."""
    raise RuntimeError("Scheduler not initialized")


def _get_settings():
    """Dependency placeholder -- overridden in main.py."""
    raise RuntimeError("Settings not initialized")


@router.get("/health")
async def health(scheduler=Depends(_get_scheduler)) -> dict[str, str | int | float | None]:
    """Health check endpoint."""
    uptime_seconds = 0.0
    if scheduler.last_poll:
        uptime_seconds = (datetime.now(timezone.utc) - scheduler.last_poll).total_seconds()
    return {
        "status": "ok",
        "last_poll": scheduler.last_poll.isoformat() if scheduler.last_poll else None,
        "guest_count": len(scheduler.guests),
        "is_polling": scheduler.is_running,
        "seconds_since_last_poll": round(uptime_seconds, 1) if scheduler.last_poll else None,
    }


@router.get("/api/guests")
async def list_guests(scheduler=Depends(_get_scheduler)) -> list[GuestSummary]:
    """List all discovered guests."""
    return [guest.to_summary() for guest in scheduler.guests.values()]


@router.get("/api/guests/{guest_id}")
async def get_guest(guest_id: str, scheduler=Depends(_get_scheduler)) -> GuestDetail:
    """Get detail for a single guest."""
    guest = scheduler.guests.get(guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} not found")
    return guest.to_detail()


@router.post("/api/refresh", status_code=202)
async def refresh(scheduler=Depends(_get_scheduler)) -> dict[str, str]:
    """Trigger an immediate re-discovery cycle."""
    scheduler.trigger_refresh()
    return {"status": "started"}


@router.get("/api/settings")
async def get_settings(settings=Depends(_get_settings)) -> dict[str, str | int | bool | None]:
    """Return current settings with secrets masked."""
    return settings.masked_settings()
