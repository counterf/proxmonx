"""Background polling scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from app.config import Settings
from app.core.discovery import DiscoveryEngine
from app.models.guest import GuestInfo

if TYPE_CHECKING:
    from app.core.alerting import AlertManager

logger = logging.getLogger(__name__)


class Scheduler:
    """Runs the discovery/detection loop on a configurable interval."""

    def __init__(
        self,
        settings: Settings,
        engine: DiscoveryEngine,
        alert_manager: AlertManager | None = None,
    ) -> None:
        self._interval = settings.poll_interval_seconds
        self._engine = engine
        self._alert_manager = alert_manager
        self._guests: dict[str, GuestInfo] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._refresh_event = asyncio.Event()
        self._last_poll: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def guests(self) -> dict[str, GuestInfo]:
        return dict(self._guests)

    @property
    def last_poll(self) -> datetime | None:
        return self._last_poll

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the background polling loop."""
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler started with %ds interval", self._interval)

    async def stop(self) -> None:
        """Stop the background polling loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Scheduler stopped")

    def trigger_refresh(self) -> None:
        """Trigger an immediate refresh cycle."""
        self._refresh_event.set()

    def trigger_guest_refresh(self, guest_id: str) -> bool:
        """Schedule a single-guest re-detection out-of-band. Returns False if not found."""
        if guest_id not in self._guests:
            return False
        asyncio.create_task(self._refresh_single_guest(guest_id))
        return True

    async def _refresh_single_guest(self, guest_id: str) -> None:
        """Re-process one guest: re-detect app and re-check versions."""
        existing = self._guests.get(guest_id)
        if not existing:
            return
        hosts = self._engine._settings.get_hosts() if self._engine._settings else []
        host_config = next((h for h in hosts if h.id == existing.host_id), None)
        if not host_config:
            logger.warning("No host config found for guest %s (host_id=%s)", guest_id, existing.host_id)
            return
        host_client = httpx.AsyncClient(
            timeout=10.0,
            verify=host_config.verify_ssl,
            follow_redirects=True,
        )
        try:
            # Re-fetch live status from Proxmox so a guest that was stopped
            # during the last full cycle but is now running gets processed correctly.
            from app.core.proxmox import ProxmoxClient
            settings = self._engine._build_host_settings(host_config)
            proxmox = ProxmoxClient(settings, http_client=host_client)
            fresh_guests = await proxmox.list_guests()
            raw_vmid = guest_id.rsplit(":", 1)[-1]
            fresh = next((g for g in fresh_guests if str(g.id) == raw_vmid), None)
            guest_copy = existing.model_copy()
            if fresh:
                guest_copy.status = fresh.status
                guest_copy.disk_used = fresh.disk_used
                guest_copy.disk_total = fresh.disk_total

            updated = await self._engine._process_guest(
                guest_copy,
                existing,
                host_config=host_config,
                host_http_client=host_client,
            )
        except Exception:
            logger.exception("Single-guest refresh failed for %s", guest_id)
            return
        finally:
            await host_client.aclose()
        async with self._lock:
            self._guests[guest_id] = updated
        logger.info("Single-guest refresh complete for %s (%s)", existing.name, guest_id)

    async def _loop(self) -> None:
        """Main polling loop."""
        # Run immediately on startup
        await self._run_cycle()

        while True:
            try:
                # Wait for either the interval or a manual refresh trigger
                try:
                    await asyncio.wait_for(
                        self._refresh_event.wait(), timeout=self._interval
                    )
                    self._refresh_event.clear()
                    logger.info("Manual refresh triggered")
                except asyncio.TimeoutError:
                    pass  # Normal interval elapsed

                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in scheduler loop")
                # Back off on error
                await asyncio.sleep(min(self._interval, 60))

    async def _run_cycle(self) -> None:
        """Execute one discovery cycle."""
        async with self._lock:
            self._running = True
            try:
                old_guests = dict(self._guests)
                self._guests = await self._engine.run_full_cycle(self._guests)
                self._last_poll = datetime.now(timezone.utc)
                if self._alert_manager:
                    try:
                        await self._alert_manager.evaluate(old_guests, self._guests)
                    except Exception:
                        logger.warning("Alert evaluation failed", exc_info=True)
            finally:
                self._running = False
