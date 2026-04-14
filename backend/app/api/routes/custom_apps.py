"""Custom app definition CRUD endpoints."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.config import CustomAppDef, _CUSTOM_APP_NAME_RE
from app.core.github import parse_github_repo
from app.detectors.registry import _BUILTIN_NAMES, load_custom_detectors

from app.api.helpers import (
    _get_config_store,
    _reload_settings_into_engine,
    _require_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Request model ---


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


# --- Helpers ---


def _reload_custom_detectors(
    request: Request, config_store,
) -> None:
    """Reload custom detectors from the DB and seed app_config for https apps."""
    defs_raw = config_store.list_custom_app_defs()
    defs = []
    for i, item in enumerate(defs_raw):
        if isinstance(item, dict):
            try:
                defs.append(CustomAppDef(**item))
            except Exception as exc:
                logger.warning("Skipping invalid custom_app_defs[%d]: %s", i, exc)
                continue
    load_custom_detectors(defs)

    # Sync app_config scheme for custom apps
    app_configs = config_store.list_app_configs()
    for defn in defs:
        if defn.scheme != "http" and defn.name not in app_configs:
            config_store.upsert_app_config(defn.name, {"scheme": defn.scheme})
        elif defn.scheme == "http" and defn.name in app_configs:
            entry = app_configs[defn.name]
            if isinstance(entry, dict) and entry.get("scheme"):
                entry.pop("scheme")
                if not entry:
                    config_store.delete_app_config(defn.name)
                else:
                    config_store.upsert_app_config(defn.name, entry)

    # Reload settings into engine
    _reload_settings_into_engine(request, config_store)


# --- Endpoints ---


@router.get("/api/custom-apps")
async def list_custom_apps(
    config_store=Depends(_get_config_store),
) -> list[dict]:
    """List all custom app definitions."""
    return config_store.list_custom_app_defs()


@router.post("/api/custom-apps", status_code=201, dependencies=[Depends(_require_api_key)])
async def create_custom_app(
    body: CustomAppDefRequest,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict:
    """Create a new custom app definition."""
    if config_store.get_custom_app_def(body.name) is not None:
        raise HTTPException(status_code=409, detail=f"Custom app '{body.name}' already exists")

    new_def = body.model_dump()
    config_store.upsert_custom_app_def(new_def)
    _reload_custom_detectors(request, config_store)
    return new_def


@router.put("/api/custom-apps/{name}", dependencies=[Depends(_require_api_key)])
async def update_custom_app(
    name: str,
    body: CustomAppDefRequest,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict:
    """Update an existing custom app definition."""
    if config_store.get_custom_app_def(name) is None:
        raise HTTPException(status_code=404, detail=f"Custom app '{name}' not found")

    updated = body.model_dump()
    updated["name"] = name  # preserve original name
    config_store.upsert_custom_app_def(updated)
    _reload_custom_detectors(request, config_store)
    return updated


@router.delete("/api/custom-apps/{name}", dependencies=[Depends(_require_api_key)])
async def delete_custom_app(
    name: str,
    request: Request,
    config_store=Depends(_get_config_store),
) -> dict[str, str]:
    """Delete a custom app definition and clear references in guest_config."""
    if config_store.get_custom_app_def(name) is None:
        raise HTTPException(status_code=404, detail=f"Custom app '{name}' not found")

    config_store.delete_custom_app_def(name)

    # Clear forced_detector references in guest_config
    guest_configs = config_store.list_guest_configs()
    for gid, gcfg in guest_configs.items():
        if isinstance(gcfg, dict) and gcfg.get("forced_detector") == name:
            gcfg.pop("forced_detector", None)
            config_store.upsert_guest_config(gid, gcfg)

    # Remove app_config entry for the deleted custom app
    config_store.delete_app_config(name)

    _reload_custom_detectors(request, config_store)
    return {"status": "deleted"}
