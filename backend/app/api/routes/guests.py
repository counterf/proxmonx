"""Guest-related API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import field_validator

from app.detectors.registry import DETECTOR_MAP
from app.models.guest import GuestInfo

from app.api.helpers import (
    _AppConfigBase,
    _get_config_store,
    _get_scheduler,
    _get_settings,
    _keep_or_replace,
    _reload_settings_into_engine,
    _require_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request/Response models ---


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
    if guest_cfg.get("api_key"):
        guest_cfg = dict(guest_cfg)
        guest_cfg["api_key"] = "***"
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

    if body.forced_detector:
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


@router.post("/api/refresh", status_code=202, dependencies=[Depends(_require_api_key)])
async def refresh(scheduler=Depends(_get_scheduler)) -> dict[str, str]:
    """Trigger an immediate re-discovery cycle."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="proxmon is not configured")
    scheduler.trigger_refresh()
    return {"status": "started"}
