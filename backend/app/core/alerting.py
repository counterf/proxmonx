"""Alert evaluation: disk threshold and version-status transitions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.core.notifier import NtfyNotifier
from app.models.guest import GuestInfo

logger = logging.getLogger(__name__)


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PB"


class AlertManager:
    """Evaluates alert rules after each discovery cycle and dispatches via ntfy."""

    def __init__(self, notifier: NtfyNotifier, settings: Settings) -> None:
        self._notifier = notifier
        self._disk_threshold = settings.notify_disk_threshold
        self._cooldown_minutes = settings.notify_disk_cooldown_minutes
        self._notify_outdated = settings.notify_on_outdated
        self._enabled = settings.notifications_enabled
        self._cooldowns: dict[tuple[str, str], datetime] = {}

    def _cooldown_expired(self, key: tuple[str, str]) -> bool:
        last = self._cooldowns.get(key)
        if last is None:
            return True
        return datetime.now(timezone.utc) - last >= timedelta(minutes=self._cooldown_minutes)

    def _record_cooldown(self, key: tuple[str, str]) -> None:
        self._cooldowns[key] = datetime.now(timezone.utc)

    async def evaluate(
        self,
        previous: dict[str, GuestInfo],
        current: dict[str, GuestInfo],
    ) -> None:
        if not self._enabled:
            return

        for gid, guest in current.items():
            await self._check_disk(gid, guest)
            await self._check_outdated(gid, guest, previous.get(gid))

        self._evict_expired_cooldowns()

    def _evict_expired_cooldowns(self) -> None:
        """Remove cooldown entries older than 2x the cooldown window."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self._cooldown_minutes * 2)
        expired = [k for k, ts in self._cooldowns.items() if ts < cutoff]
        for k in expired:
            del self._cooldowns[k]

    async def _check_disk(self, gid: str, guest: GuestInfo) -> None:
        if guest.disk_used is None or guest.disk_total is None or guest.disk_total == 0:
            return

        pct = guest.disk_used / guest.disk_total * 100
        if pct < self._disk_threshold:
            return

        key = (gid, "disk")
        if not self._cooldown_expired(key):
            return

        title = f"Disk Alert: {guest.name}"
        body = (
            f"Disk usage is at {pct:.0f}% "
            f"({_format_bytes(guest.disk_used)}/{_format_bytes(guest.disk_total)})"
        )
        sent = await self._notifier.send(title, body, tags="warning,floppy_disk", priority=4)
        if sent:
            self._record_cooldown(key)
            logger.info("Disk alert sent for %s (%.0f%%)", guest.name, pct)

    async def _check_outdated(
        self,
        gid: str,
        guest: GuestInfo,
        previous: GuestInfo | None,
    ) -> None:
        if not self._notify_outdated:
            return
        if guest.update_status != "outdated":
            return
        prev_status = previous.update_status if previous else "unknown"
        if prev_status == "outdated":
            return

        title = f"Update Available: {guest.app_name or guest.name}"
        body = f"{guest.name}: {guest.installed_version} -> {guest.latest_version}"
        sent = await self._notifier.send(title, body, tags="arrow_up")
        if sent:
            logger.info(
                "Outdated alert sent for %s (%s -> %s)",
                guest.name, guest.installed_version, guest.latest_version,
            )
