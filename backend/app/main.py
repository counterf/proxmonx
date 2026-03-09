"""FastAPI application entry point."""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router, _get_scheduler, _get_settings, _get_config_store
from app.config import Settings
from app.core.config_store import ConfigStore
from app.core.discovery import DiscoveryEngine
from app.core.github import GitHubClient
from app.core.proxmox import ProxmoxClient
from app.core.scheduler import Scheduler
from app.core.ssh import SSHClient


def _configure_logging(level: str) -> None:
    """Set up structured logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


# Global references for dependency injection
_scheduler: Scheduler | None = None
_settings: Settings | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: start/stop the scheduler."""
    global _scheduler, _settings

    settings = Settings()

    # Load config file and merge (config file takes priority over env vars)
    config_store = ConfigStore(settings.config_file_path)
    settings = config_store.merge_into_settings(settings)

    _settings = settings
    app.state.config_store = config_store
    _configure_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting proxmon")

    configured = config_store.is_configured()

    if not configured:
        logger.warning("proxmon starting in unconfigured mode -- visit the UI to configure")
        # Store empty scheduler reference and settings
        app.dependency_overrides[_get_scheduler] = lambda: None
        app.dependency_overrides[_get_settings] = lambda: settings
        app.dependency_overrides[_get_config_store] = lambda: config_store
        yield
        logger.info("proxmon stopped")
        return

    if not settings.verify_ssl:
        logger.warning("SSL verification is disabled (VERIFY_SSL=false)")

    if not settings.ssh_known_hosts_path:
        logger.warning(
            "SSH_KNOWN_HOSTS_PATH not set; using WarningPolicy (no strict host key verification)"
        )

    http_client = httpx.AsyncClient(timeout=10.0, verify=settings.verify_ssl, follow_redirects=True)
    app.state.http_client = http_client

    proxmox = ProxmoxClient(settings, http_client=http_client)
    github = GitHubClient(settings, http_client=http_client)
    ssh = SSHClient(settings)
    engine = DiscoveryEngine(proxmox, github, ssh, http_client=http_client, settings=settings)
    scheduler = Scheduler(settings, engine)
    _scheduler = scheduler

    # Override dependency getters
    app.dependency_overrides[_get_scheduler] = lambda: scheduler
    app.dependency_overrides[_get_settings] = lambda: settings
    app.dependency_overrides[_get_config_store] = lambda: config_store

    scheduler.start()

    yield

    await scheduler.stop()
    await http_client.aclose()
    logger.info("proxmon stopped")


app = FastAPI(
    title="proxmon",
    description="Proxmox guest application version monitor",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — origins configured via CORS_ORIGINS env var (JSON list or comma-separated).
# Read directly from os.environ rather than pydantic-settings because CORSMiddleware
# must be registered at module import time (before the ASGI lifespan runs). Docker
# Compose env_file injects values into the container's environment, so os.environ
# correctly picks up .env values in production.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://frontend"]


def _parse_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    if not raw:
        return _DEFAULT_CORS_ORIGINS
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(o) for o in parsed]
    except (ValueError, TypeError):
        pass
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)
