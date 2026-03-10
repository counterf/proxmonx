"""Tests for AlertManager."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.core.alerting import AlertManager, _format_bytes
from app.core.notifier import NtfyNotifier
from app.models.guest import GuestInfo


def _make_settings(**overrides) -> Settings:
    defaults = {
        "notifications_enabled": True,
        "ntfy_url": "https://ntfy.example.com/test",
        "notify_disk_threshold": 95,
        "notify_disk_cooldown_minutes": 60,
        "notify_on_outdated": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_guest(
    gid: str = "host1:100",
    name: str = "test-guest",
    disk_used: int | None = None,
    disk_total: int | None = None,
    update_status: str = "unknown",
    app_name: str | None = None,
    installed_version: str | None = None,
    latest_version: str | None = None,
) -> GuestInfo:
    g = GuestInfo(id=gid, name=name, type="lxc", status="running", tags=[])
    g.disk_used = disk_used
    g.disk_total = disk_total
    g.update_status = update_status
    g.app_name = app_name
    g.installed_version = installed_version
    g.latest_version = latest_version
    return g


class TestFormatBytes:
    def test_bytes(self):
        assert _format_bytes(500) == "500.0 B"

    def test_gigabytes(self):
        assert _format_bytes(2 * 1024**3) == "2.0 GB"

    def test_terabytes(self):
        assert _format_bytes(3 * 1024**4) == "3.0 TB"


@pytest.mark.asyncio
class TestDiskAlerts:

    async def test_disk_above_threshold_sends_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        guest = _make_guest(disk_used=96, disk_total=100)
        await am.evaluate({}, {"host1:100": guest})

        notifier.send.assert_called_once()
        title = notifier.send.call_args[1].get("title") or notifier.send.call_args[0][0]
        assert "Disk Alert" in title

    async def test_disk_below_threshold_no_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        guest = _make_guest(disk_used=90, disk_total=100)
        await am.evaluate({}, {"host1:100": guest})

        notifier.send.assert_not_called()

    async def test_disk_none_values_no_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        guest = _make_guest(disk_used=None, disk_total=None)
        await am.evaluate({}, {"host1:100": guest})

        notifier.send.assert_not_called()

    async def test_disk_zero_total_no_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        guest = _make_guest(disk_used=50, disk_total=0)
        await am.evaluate({}, {"host1:100": guest})

        notifier.send.assert_not_called()

    async def test_disk_cooldown_prevents_repeat(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings(notify_disk_cooldown_minutes=60))

        guest = _make_guest(disk_used=96, disk_total=100)
        await am.evaluate({}, {"host1:100": guest})
        assert notifier.send.call_count == 1

        # Second cycle within cooldown
        await am.evaluate({}, {"host1:100": guest})
        assert notifier.send.call_count == 1  # no second call

    async def test_disk_cooldown_expired_sends_again(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings(notify_disk_cooldown_minutes=60))

        guest = _make_guest(disk_used=96, disk_total=100)
        await am.evaluate({}, {"host1:100": guest})
        assert notifier.send.call_count == 1

        # Expire the cooldown
        key = ("host1:100", "disk")
        am._cooldowns[key] = datetime.now(timezone.utc) - timedelta(minutes=61)

        await am.evaluate({}, {"host1:100": guest})
        assert notifier.send.call_count == 2

    async def test_disk_send_failure_no_cooldown_recorded(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=False)
        am = AlertManager(notifier, _make_settings())

        guest = _make_guest(disk_used=96, disk_total=100)
        await am.evaluate({}, {"host1:100": guest})

        assert ("host1:100", "disk") not in am._cooldowns


@pytest.mark.asyncio
class TestOutdatedAlerts:

    async def test_transition_to_outdated_sends_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        prev = _make_guest(update_status="up-to-date", app_name="Sonarr",
                           installed_version="3.0.0", latest_version="3.0.0")
        curr = _make_guest(update_status="outdated", app_name="Sonarr",
                           installed_version="3.0.0", latest_version="4.0.0")

        await am.evaluate({"host1:100": prev}, {"host1:100": curr})

        notifier.send.assert_called_once()
        title = notifier.send.call_args[1].get("title") or notifier.send.call_args[0][0]
        assert "Update Available" in title

    async def test_already_outdated_no_repeat(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        prev = _make_guest(update_status="outdated")
        curr = _make_guest(update_status="outdated")

        await am.evaluate({"host1:100": prev}, {"host1:100": curr})

        notifier.send.assert_not_called()

    async def test_new_guest_outdated_sends_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        curr = _make_guest(update_status="outdated", app_name="Radarr",
                           installed_version="3.0.0", latest_version="4.0.0")

        await am.evaluate({}, {"host1:100": curr})

        notifier.send.assert_called_once()

    async def test_outdated_disabled_no_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings(notify_on_outdated=False))

        prev = _make_guest(update_status="up-to-date")
        curr = _make_guest(update_status="outdated")

        await am.evaluate({"host1:100": prev}, {"host1:100": curr})

        notifier.send.assert_not_called()

    async def test_status_up_to_date_no_alert(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings())

        prev = _make_guest(update_status="unknown")
        curr = _make_guest(update_status="up-to-date")

        await am.evaluate({"host1:100": prev}, {"host1:100": curr})

        notifier.send.assert_not_called()


@pytest.mark.asyncio
class TestAlertManagerDisabled:

    async def test_disabled_skips_all(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings(notifications_enabled=False))

        guest = _make_guest(disk_used=99, disk_total=100, update_status="outdated")
        await am.evaluate({}, {"host1:100": guest})

        notifier.send.assert_not_called()


@pytest.mark.asyncio
class TestUpdateSettings:

    async def test_update_settings_changes_threshold(self):
        notifier = NtfyNotifier(url="https://ntfy.example.com/test")
        notifier.send = AsyncMock(return_value=True)
        am = AlertManager(notifier, _make_settings(notify_disk_threshold=95))

        guest = _make_guest(disk_used=92, disk_total=100)
        await am.evaluate({}, {"host1:100": guest})
        notifier.send.assert_not_called()

        am.update_settings(_make_settings(notify_disk_threshold=90))
        await am.evaluate({}, {"host1:100": guest})
        notifier.send.assert_called_once()
