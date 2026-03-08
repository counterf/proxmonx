"""Background polling scheduler."""

import asyncio
import logging
from datetime import datetime, timezone

from app.config import Settings
from app.core.discovery import DiscoveryEngine
from app.models.guest import GuestInfo

logger = logging.getLogger(__name__)


class Scheduler:
    """Runs the discovery/detection loop on a configurable interval."""

    def __init__(self, settings: Settings, engine: DiscoveryEngine) -> None:
        self._interval = settings.poll_interval_seconds
        self._enabled = settings.proxmon_enabled
        self._engine = engine
        self._guests: dict[str, GuestInfo] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._refresh_event = asyncio.Event()
        self._last_poll: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def guests(self) -> dict[str, GuestInfo]:
        return self._guests

    @property
    def last_poll(self) -> datetime | None:
        return self._last_poll

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the background polling loop."""
        if not self._enabled:
            logger.info("Proxmon polling disabled via PROXMON_ENABLED=false")
            return
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
                self._guests = await self._engine.run_full_cycle(self._guests)
                self._last_poll = datetime.now(timezone.utc)
            finally:
                self._running = False
