"""FastAPI application entry point."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth_routes import auth_router
from app.api.routes import router, _get_scheduler, _get_settings, _get_config_store
from app.config import Settings
from app.core.alerting import AlertManager
from app.core.auth import hash_password
from app.core.config_store import ConfigStore
from app.core.discovery import DiscoveryEngine
from app.core.github import GitHubClient
from app.core.notifier import NtfyNotifier
from app.core.proxmox import ProxmoxClient
from app.core.scheduler import Scheduler
from app.core.session_store import SessionStore
from app.core.ssh import SSHClient
from app.middleware.auth_middleware import AuthMiddleware


def _configure_logging(level: str) -> None:
    """Set up logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def build_runtime(settings: Settings) -> tuple[httpx.AsyncClient, Scheduler]:
    """Create HTTP client, discovery engine, and scheduler from settings.

    Returns (http_client, scheduler) so the caller can manage lifecycle.
    Used by both lifespan() and save_settings() to avoid duplicating wiring.
    """
    http_client = httpx.AsyncClient(timeout=10.0, verify=settings.verify_ssl, follow_redirects=True)
    proxmox = ProxmoxClient(settings, http_client=http_client)
    github = GitHubClient(settings, http_client=http_client)
    ssh = SSHClient(settings)
    engine = DiscoveryEngine(proxmox, github, ssh, http_client=http_client, settings=settings)

    alert_manager: AlertManager | None = None
    if settings.notifications_enabled and settings.ntfy_url:
        notifier = NtfyNotifier(
            url=settings.ntfy_url,
            token=settings.ntfy_token,
            priority=settings.ntfy_priority,
            http_client=http_client,
        )
        alert_manager = AlertManager(notifier, settings)

    scheduler = Scheduler(settings, engine, alert_manager=alert_manager)
    return http_client, scheduler


# Global references for dependency injection
_scheduler: Scheduler | None = None
_settings: Settings | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: start/stop the scheduler."""
    global _scheduler, _settings

    db_path = os.environ.get("CONFIG_DB_PATH", "/app/data/proxmon.db")
    config_store = ConfigStore(db_path)
    settings = config_store.merge_into_settings(Settings())

    _settings = settings
    app.state.config_store = config_store
    app.state.settings = settings

    # Session store for auth (same DB file)
    session_store = SessionStore(db_path)
    app.state.session_store = session_store

    # Bootstrap default password if auth enabled and no hash set.
    _boot_data = config_store.load()
    if _boot_data.get("auth_mode", "forms") == "forms" and not _boot_data.get("auth_password_hash", ""):
        _boot_data["auth_password_hash"] = hash_password("proxmon!")
        config_store.save(_boot_data)
        settings = config_store.merge_into_settings(Settings())
        _settings = settings
        app.state.settings = settings

    _configure_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting proxmon")

    configured = config_store.is_configured()

    if not configured:
        logger.warning("proxmon starting in unconfigured mode -- visit the UI to configure")
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

    http_client, scheduler = build_runtime(settings)
    app.state.http_client = http_client
    _scheduler = scheduler

    if settings.notifications_enabled and settings.ntfy_url:
        logger.info("Notifications enabled -> %s", settings.ntfy_url)

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

app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    # Dev only: production is same-origin; these are for local Vite/React dev servers.
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)

_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.staticfiles import StaticFiles
    from starlette.types import Scope

    class _SPAStaticFiles(StaticFiles):
        """StaticFiles that falls back to index.html for SPA client-side routing."""

        async def get_response(self, path: str, scope: Scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    # Mounted last so /api and /health routes are matched first by the router.
    app.mount("/", _SPAStaticFiles(directory=str(_static_dir), html=True), name="static")
