"""FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router, _get_scheduler, _get_settings
from app.config import Settings
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
    _settings = settings
    _configure_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting proxmon")

    proxmox = ProxmoxClient(settings)
    github = GitHubClient(settings)
    ssh = SSHClient(settings)
    engine = DiscoveryEngine(proxmox, github, ssh)
    scheduler = Scheduler(settings, engine)
    _scheduler = scheduler

    # Override dependency getters
    app.dependency_overrides[_get_scheduler] = lambda: scheduler
    app.dependency_overrides[_get_settings] = lambda: settings

    scheduler.start()

    yield

    await scheduler.stop()
    logger.info("proxmon stopped")


app = FastAPI(
    title="proxmon",
    description="Proxmox guest application version monitor",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)
