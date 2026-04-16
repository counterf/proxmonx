"""Tests for discovery orchestration."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import httpx
import respx

from app.config import AppConfig, ProxmoxHostConfig, Settings
from app.core.discovery import DiscoveryEngine
from app.models.guest import GuestInfo
from app.core.github import GitHubClient
from app.core.proxmox import DiscoveryError, ProxmoxClient
from app.core.ssh import SSHClient


class TestResolveConfig:
    """Tests for the _resolve_config layered config resolution."""

    def _make_engine(self, **settings_overrides: Any) -> DiscoveryEngine:
        settings = _make_settings(**settings_overrides)
        return DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings), settings=settings,
        )

    def test_defaults_when_no_config(self) -> None:
        engine = self._make_engine()
        port, api_key, scheme, *_ = engine._resolve_config("sonarr", "default:100")
        assert port is None
        assert api_key is None
        assert scheme == "http"

    def test_app_config_applies(self) -> None:
        engine = self._make_engine(
            app_config={"sonarr": AppConfig(port=9999, api_key="app-key", scheme="https")}
        )
        port, api_key, scheme, *_ = engine._resolve_config("sonarr", "default:100")
        assert port == 9999
        assert api_key == "app-key"
        assert scheme == "https"

    def test_guest_config_overrides_app_config(self) -> None:
        engine = self._make_engine(
            app_config={"sonarr": AppConfig(port=9999, api_key="app-key", scheme="https")},
            guest_config={"default:100": AppConfig(api_key="guest-key")},
        )
        port, api_key, scheme, *_ = engine._resolve_config("sonarr", "default:100")
        assert port == 9999  # inherited from app_config
        assert api_key == "guest-key"  # overridden by guest_config
        assert scheme == "https"  # inherited from app_config

    def test_guest_config_port_override(self) -> None:
        engine = self._make_engine(
            app_config={"sonarr": AppConfig(port=8989)},
            guest_config={"default:100": AppConfig(port=7777)},
        )
        port, api_key, *_ = engine._resolve_config("sonarr", "default:100")
        assert port == 7777
        assert api_key is None

    def test_guest_config_without_app_config(self) -> None:
        engine = self._make_engine(
            guest_config={"default:100": AppConfig(api_key="solo-key", scheme="https")},
        )
        port, api_key, scheme, *_ = engine._resolve_config("sonarr", "default:100")
        assert port is None
        assert api_key == "solo-key"
        assert scheme == "https"

    def test_unrelated_guest_id_not_applied(self) -> None:
        engine = self._make_engine(
            guest_config={"default:200": AppConfig(api_key="other-key")},
        )
        _, api_key, *_ = engine._resolve_config("sonarr", "default:100")
        assert api_key is None


class TestForcedDetector:
    """Manual forced_detector on guest config skips auto app detection."""

    @pytest.mark.asyncio
    async def test_forced_detector_skips_name_matching(self) -> None:
        settings = _make_settings(
            guest_config={
                "default:102": AppConfig(forced_detector="radarr"),
            },
        )
        engine = DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings),
            settings=settings,
        )
        guest = GuestInfo(
            id="default:102",
            name="mystery-box",
            type="lxc",
            status="running",
            ip="10.0.0.50",
            tags=["unrelated"],
        )
        await engine._detect_app(guest)
        assert guest.detector_used == "radarr"
        assert guest.app_name == "Radarr"
        assert guest.detection_method == "manual"
        assert guest.raw_detection_output == {
            "detector": "radarr",
            "method": "manual",
        }

    @pytest.mark.asyncio
    async def test_invalid_forced_detector_ignored(self) -> None:
        settings = _make_settings(
            guest_config={
                "default:103": AppConfig(forced_detector="not-a-real-detector"),
            },
        )
        engine = DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings),
            settings=settings,
        )
        guest = GuestInfo(
            id="default:103",
            name="sonarr",
            type="lxc",
            status="running",
            ip="10.0.0.50",
        )
        await engine._detect_app(guest)
        assert guest.detector_used == "sonarr"
        assert guest.detection_method == "name_match"


def _make_host_config(**overrides: Any) -> ProxmoxHostConfig:
    defaults: dict[str, Any] = {
        "id": "default",
        "label": "Default",
        "host": "https://pve.local:8006",
        "token_id": "test@pve!token",
        "token_secret": "secret",
        "node": "pve",
    }
    defaults.update(overrides)
    return ProxmoxHostConfig(**defaults)


def _make_settings(**overrides: Any) -> Settings:
    host_config = _make_host_config()
    defaults: dict[str, Any] = {
        "ssh_enabled": False,
        "proxmox_hosts": [host_config],
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestProxmoxClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_lxc_guests(self) -> None:
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"vmid": 100, "name": "sonarr", "status": "running", "tags": "media"},
                    {"vmid": 101, "name": "radarr", "status": "running", "tags": "media;arr"},
                    {"vmid": 102, "name": "db-server", "status": "stopped", "tags": ""},
                ]
            })
        )
        client = ProxmoxClient(_make_host_config())
        guests = await client.list_guests()
        assert len(guests) == 3
        assert guests[0].id == "100"
        assert guests[0].name == "sonarr"
        assert guests[0].status == "running"
        assert guests[0].tags == ["media"]
        assert guests[1].tags == ["media", "arr"]
        assert guests[2].status == "stopped"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_includes_vms(self) -> None:
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        respx.get("https://pve.local:8006/api2/json/nodes/pve/qemu").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"vmid": 200, "name": "plex-vm", "status": "running", "tags": ""},
                ]
            })
        )
        client = ProxmoxClient(_make_host_config(), discover_vms=True)
        guests = await client.list_guests()
        assert len(guests) == 1
        assert guests[0].type == "vm"

    @respx.mock
    @pytest.mark.asyncio
    async def test_ip_resolution(self) -> None:
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc/100/config").mock(
            return_value=httpx.Response(200, json={
                "data": {
                    "net0": "name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:DD:EE:FF,ip=10.0.0.100/24,type=veth"
                }
            })
        )
        client = ProxmoxClient(_make_host_config())
        ip, os_type = await client.get_guest_network("100", "lxc")
        assert ip == "10.0.0.100"


class TestDiscoveryEngine:
    @respx.mock
    @pytest.mark.asyncio
    async def test_full_cycle_detects_apps(self) -> None:
        # Mock Proxmox API
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"vmid": 100, "name": "sonarr", "status": "running", "tags": ""},
                ]
            })
        )
        # Mock IP resolution
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc/100/config").mock(
            return_value=httpx.Response(200, json={
                "data": {"net0": "ip=10.0.0.100/24"}
            })
        )
        # Mock Sonarr API
        respx.get("http://10.0.0.100:8989/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        # Mock GitHub API
        respx.get("https://api.github.com/repos/Sonarr/Sonarr/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v4.0.15.3012"})
        )

        settings = _make_settings()
        engine = DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings),
            settings=settings,
        )
        guests = await engine.run_full_cycle({})

        assert "default:100" in guests
        guest = guests["default:100"]
        assert guest.app_name == "Sonarr"
        assert guest.installed_version == "4.0.14.2939"
        assert guest.latest_version == "4.0.15.3012"
        assert guest.update_status == "outdated"
        assert guest.detection_method == "name_match"

    @respx.mock
    @pytest.mark.asyncio
    async def test_stopped_guest_skips_detection(self) -> None:
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"vmid": 101, "name": "sonarr-backup", "status": "stopped", "tags": ""},
                ]
            })
        )

        settings = _make_settings()
        engine = DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings),
            settings=settings,
        )
        guests = await engine.run_full_cycle({})

        assert "default:101" in guests
        assert guests["default:101"].update_status == "unknown"
        assert guests["default:101"].app_name is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_app_config_port_and_api_key_override(self) -> None:
        """Discovery uses port and api_key from app_config."""
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"vmid": 100, "name": "sonarr", "status": "running", "tags": ""},
                ]
            })
        )
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc/100/config").mock(
            return_value=httpx.Response(200, json={
                "data": {"net0": "ip=10.0.0.100/24"}
            })
        )
        # Expect the overridden port (9999) to be used
        route = respx.get("http://10.0.0.100:9999/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        respx.get("https://api.github.com/repos/Sonarr/Sonarr/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v4.0.14.2939"})
        )

        settings = _make_settings(
            app_config={"sonarr": AppConfig(port=9999, api_key="my-key")},
        )
        engine = DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings),
            settings=settings,
        )
        guests = await engine.run_full_cycle({})

        assert "default:100" in guests
        assert guests["default:100"].installed_version == "4.0.14.2939"
        # Verify API key was sent as X-Api-Key header
        assert route.calls[0].request.headers["x-api-key"] == "my-key"


class TestGithubRepoOverride:
    @respx.mock
    @pytest.mark.asyncio
    async def test_override_uses_custom_repo(self) -> None:
        """Discovery uses github_repo from app_config when set."""
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"vmid": 100, "name": "sonarr", "status": "running", "tags": ""},
                ]
            })
        )
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc/100/config").mock(
            return_value=httpx.Response(200, json={
                "data": {"net0": "ip=10.0.0.100/24"}
            })
        )
        respx.get("http://10.0.0.100:8989/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        # The override repo should be called, NOT the default Sonarr/Sonarr
        custom_route = respx.get(
            "https://api.github.com/repos/MyFork/Sonarr/releases/latest"
        ).mock(
            return_value=httpx.Response(200, json={"tag_name": "v4.1.0.0"})
        )
        # Ensure the default repo is NOT called
        default_route = respx.get(
            "https://api.github.com/repos/Sonarr/Sonarr/releases/latest"
        ).mock(
            return_value=httpx.Response(200, json={"tag_name": "v4.0.15.3012"})
        )

        settings = _make_settings(
            app_config={"sonarr": AppConfig(github_repo="MyFork/Sonarr")},
        )
        engine = DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings),
            settings=settings,
        )
        guests = await engine.run_full_cycle({})

        assert "default:100" in guests
        assert guests["default:100"].latest_version == "4.1.0.0"
        assert custom_route.called
        assert not default_route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_fallback_to_detector_default_repo(self) -> None:
        """Discovery falls back to detector.github_repo when no override is set."""
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc").mock(
            return_value=httpx.Response(200, json={
                "data": [
                    {"vmid": 100, "name": "sonarr", "status": "running", "tags": ""},
                ]
            })
        )
        respx.get("https://pve.local:8006/api2/json/nodes/pve/lxc/100/config").mock(
            return_value=httpx.Response(200, json={
                "data": {"net0": "ip=10.0.0.100/24"}
            })
        )
        respx.get("http://10.0.0.100:8989/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        default_route = respx.get(
            "https://api.github.com/repos/Sonarr/Sonarr/releases/latest"
        ).mock(
            return_value=httpx.Response(200, json={"tag_name": "v4.0.15.3012"})
        )

        settings = _make_settings()
        engine = DiscoveryEngine(
            GitHubClient(settings),
            SSHClient(settings),
            settings=settings,
        )
        guests = await engine.run_full_cycle({})

        assert "default:100" in guests
        assert guests["default:100"].latest_version == "4.0.15.3012"
        assert default_route.called


class TestDiscoveryErrorResilience:
    """Tests for Finding 4: transient discovery failures preserve host state."""

    @pytest.mark.asyncio
    async def test_discovery_error_preserves_existing_guests(self) -> None:
        """When list_guests raises DiscoveryError, existing guests for that host are preserved."""
        existing_guest = GuestInfo(
            id="default:100", name="sonarr", type="lxc", status="running",
            host_id="default", host_label="Default", ip="10.0.0.100",
            app_name="Sonarr", detector_used="sonarr",
        )
        existing_guests = {"default:100": existing_guest}

        settings = _make_settings()
        engine = DiscoveryEngine(
            GitHubClient(settings), SSHClient(settings), settings=settings,
        )

        with patch.object(ProxmoxClient, "list_guests", side_effect=DiscoveryError("test")):
            result = await engine.run_full_cycle(existing_guests)

        assert "default:100" in result
        assert result["default:100"].name == "sonarr"

    @pytest.mark.asyncio
    async def test_multihost_preserves_failed_host_updates_successful(self) -> None:
        """Multi-host: failed host preserves guests, successful host updates."""
        host_a = _make_host_config(id="host-a", label="Host A")
        host_b = _make_host_config(id="host-b", label="Host B")

        existing_guests = {
            "host-a:100": GuestInfo(
                id="host-a:100", name="sonarr", type="lxc", status="running",
                host_id="host-a", host_label="Host A",
            ),
            "host-b:200": GuestInfo(
                id="host-b:200", name="radarr", type="lxc", status="running",
                host_id="host-b", host_label="Host B",
            ),
        }

        settings = _make_settings(proxmox_hosts=[host_a, host_b])
        engine = DiscoveryEngine(
            GitHubClient(settings), SSHClient(settings), settings=settings,
        )

        # host-a succeeds with new guest, host-b fails
        async def mock_run_host_cycle(host_config, existing, is_manual=False):
            if host_config.id == "host-a":
                return {
                    "host-a:101": GuestInfo(
                        id="host-a:101", name="prowlarr", type="lxc", status="running",
                        host_id="host-a", host_label="Host A",
                    ),
                }
            raise DiscoveryError("host-b unreachable")

        with patch.object(engine, "_run_host_cycle", side_effect=mock_run_host_cycle):
            result = await engine.run_full_cycle(existing_guests)

        # host-a got new data
        assert "host-a:101" in result
        # host-b's existing guest is preserved
        assert "host-b:200" in result
        assert result["host-b:200"].name == "radarr"
        # host-a's old guest is replaced (not present in new data)
        assert "host-a:100" not in result
