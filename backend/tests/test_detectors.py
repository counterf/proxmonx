"""Tests for detector plugins."""

import pytest
import httpx
import respx

from app.detectors.sonarr import SonarrDetector
from app.detectors.radarr import RadarrDetector
from app.detectors.bazarr import BazarrDetector
from app.detectors.prowlarr import ProwlarrDetector
from app.detectors.overseerr import OverseerrDetector
from app.detectors.plex import PlexDetector
from app.detectors.immich import ImmichDetector
from app.detectors.gitea import GiteaDetector
from app.detectors.qbittorrent import QBittorrentDetector
from app.detectors.sabnzbd import SABnzbdDetector
from app.detectors.traefik import TraefikDetector
from app.detectors.caddy import CaddyDetector
from app.detectors.ntfy import NtfyDetector
from app.detectors.docker_generic import DockerGenericDetector
from app.models.guest import GuestInfo


# -- Detection (name/tag matching) --

class TestDetection:
    def test_sonarr_name_match(self) -> None:
        d = SonarrDetector()
        guest = GuestInfo(id="100", name="sonarr-lxc", type="lxc", status="running")
        assert d.detect(guest) == "name_match"

    def test_sonarr_tag_match(self) -> None:
        d = SonarrDetector()
        guest = GuestInfo(id="100", name="media-server", type="lxc", status="running", tags=["app:sonarr"])
        assert d.detect(guest) == "tag_match"

    def test_sonarr_no_match(self) -> None:
        d = SonarrDetector()
        guest = GuestInfo(id="100", name="database", type="lxc", status="running")
        assert d.detect(guest) is None

    def test_plex_alias_match(self) -> None:
        d = PlexDetector()
        guest = GuestInfo(id="101", name="plexmediaserver-01", type="lxc", status="running")
        assert d.detect(guest) == "name_match"

    def test_docker_image_match(self) -> None:
        d = SonarrDetector()
        assert d.match_docker_image("linuxserver/sonarr:latest") is True
        assert d.match_docker_image("nginx:latest") is False

    def test_radarr_name_match(self) -> None:
        d = RadarrDetector()
        guest = GuestInfo(id="102", name="radarr", type="lxc", status="running")
        assert d.detect(guest) == "name_match"

    def test_prowlarr_tag_match(self) -> None:
        d = ProwlarrDetector()
        guest = GuestInfo(id="103", name="indexer", type="lxc", status="running", tags=["prowlarr"])
        assert d.detect(guest) == "tag_match"


# -- Installed version detection --

class TestInstalledVersion:
    @respx.mock
    @pytest.mark.asyncio
    async def test_sonarr_version(self) -> None:
        respx.get("http://10.0.0.1:8989/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        d = SonarrDetector()
        version = await d.get_installed_version("10.0.0.1")
        assert version == "4.0.14.2939"

    @respx.mock
    @pytest.mark.asyncio
    async def test_radarr_version(self) -> None:
        respx.get("http://10.0.0.2:7878/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "5.6.0.8846"})
        )
        d = RadarrDetector()
        version = await d.get_installed_version("10.0.0.2")
        assert version == "5.6.0.8846"

    @respx.mock
    @pytest.mark.asyncio
    async def test_plex_version_xml(self) -> None:
        xml = '<?xml version="1.0"?><MediaContainer version="1.40.0.7998-c29d4c0c8"/>'
        respx.get("http://10.0.0.3:32400/identity").mock(
            return_value=httpx.Response(200, text=xml)
        )
        d = PlexDetector()
        version = await d.get_installed_version("10.0.0.3")
        assert version == "1.40.0.7998"

    @respx.mock
    @pytest.mark.asyncio
    async def test_immich_version(self) -> None:
        respx.get("http://10.0.0.4:2283/api/server/about").mock(
            return_value=httpx.Response(200, json={"version": "v1.94.1"})
        )
        d = ImmichDetector()
        version = await d.get_installed_version("10.0.0.4")
        assert version == "1.94.1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_gitea_version(self) -> None:
        respx.get("http://10.0.0.5:3000/api/v1/version").mock(
            return_value=httpx.Response(200, json={"version": "1.22.0"})
        )
        d = GiteaDetector()
        version = await d.get_installed_version("10.0.0.5")
        assert version == "1.22.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_qbittorrent_version(self) -> None:
        respx.get("http://10.0.0.6:8080/api/v2/app/version").mock(
            return_value=httpx.Response(200, text="v4.6.3")
        )
        d = QBittorrentDetector()
        version = await d.get_installed_version("10.0.0.6")
        assert version == "4.6.3"

    @respx.mock
    @pytest.mark.asyncio
    async def test_sabnzbd_version(self) -> None:
        respx.get("http://10.0.0.7:8085/api?mode=version&output=json").mock(
            return_value=httpx.Response(200, json={"version": "4.2.1"})
        )
        d = SABnzbdDetector()
        version = await d.get_installed_version("10.0.0.7")
        assert version == "4.2.1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_traefik_version(self) -> None:
        respx.get("http://10.0.0.8:8080/api/version").mock(
            return_value=httpx.Response(200, json={"Version": "v3.1.0"})
        )
        d = TraefikDetector()
        version = await d.get_installed_version("10.0.0.8")
        assert version == "3.1.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_caddy_version(self) -> None:
        respx.get("http://10.0.0.9:2019/config/").mock(
            return_value=httpx.Response(200, text="{}", headers={"Server": "Caddy/2.7.6"})
        )
        d = CaddyDetector()
        version = await d.get_installed_version("10.0.0.9")
        assert version == "2.7.6"

    @respx.mock
    @pytest.mark.asyncio
    async def test_ntfy_version(self) -> None:
        respx.get("http://10.0.0.10:80/v1/info").mock(
            return_value=httpx.Response(200, json={"version": "v2.8.0"})
        )
        d = NtfyDetector()
        version = await d.get_installed_version("10.0.0.10")
        assert version == "2.8.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_bazarr_version(self) -> None:
        respx.get("http://10.0.0.11:6767/api/system/status").mock(
            return_value=httpx.Response(200, json={"bazarr_version": "1.4.3"})
        )
        d = BazarrDetector()
        version = await d.get_installed_version("10.0.0.11")
        assert version == "1.4.3"

    @respx.mock
    @pytest.mark.asyncio
    async def test_prowlarr_version(self) -> None:
        respx.get("http://10.0.0.12:9696/api/v1/system/status").mock(
            return_value=httpx.Response(200, json={"version": "1.12.2.4211"})
        )
        d = ProwlarrDetector()
        version = await d.get_installed_version("10.0.0.12")
        assert version == "1.12.2.4211"

    @respx.mock
    @pytest.mark.asyncio
    async def test_version_timeout(self) -> None:
        respx.get("http://10.0.0.99:8989/api/v3/system/status").mock(
            side_effect=httpx.ConnectTimeout("timeout")
        )
        d = SonarrDetector()
        version = await d.get_installed_version("10.0.0.99")
        assert version is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_overseerr_version(self) -> None:
        respx.get("http://10.0.0.13:5055/api/v1/status").mock(
            return_value=httpx.Response(200, json={"version": "1.33.2"})
        )
        d = OverseerrDetector()
        version = await d.get_installed_version("10.0.0.13")
        assert version == "1.33.2"


# -- API key support --

class TestApiKeySupport:
    def test_accepts_api_key_flag(self) -> None:
        assert SonarrDetector().accepts_api_key is True
        assert RadarrDetector().accepts_api_key is True
        assert ProwlarrDetector().accepts_api_key is True
        assert BazarrDetector().accepts_api_key is True
        assert OverseerrDetector().accepts_api_key is True
        assert SABnzbdDetector().accepts_api_key is True
        assert PlexDetector().accepts_api_key is False
        assert ImmichDetector().accepts_api_key is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_sonarr_with_api_key(self) -> None:
        route = respx.get("http://10.0.0.1:8989/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        d = SonarrDetector()
        version = await d.get_installed_version("10.0.0.1", api_key="test-key")
        assert version == "4.0.14.2939"
        assert route.calls[0].request.headers["x-api-key"] == "test-key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_sonarr_401_without_key(self) -> None:
        respx.get("http://10.0.0.1:8989/api/v3/system/status").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )
        d = SonarrDetector()
        version = await d.get_installed_version("10.0.0.1")
        assert version is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_radarr_with_api_key(self) -> None:
        route = respx.get("http://10.0.0.2:7878/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "5.6.0.8846"})
        )
        d = RadarrDetector()
        version = await d.get_installed_version("10.0.0.2", api_key="radarr-key")
        assert version == "5.6.0.8846"
        assert route.calls[0].request.headers["x-api-key"] == "radarr-key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_prowlarr_with_api_key(self) -> None:
        route = respx.get("http://10.0.0.12:9696/api/v1/system/status").mock(
            return_value=httpx.Response(200, json={"version": "1.12.2.4211"})
        )
        d = ProwlarrDetector()
        version = await d.get_installed_version("10.0.0.12", api_key="prowlarr-key")
        assert version == "1.12.2.4211"
        assert route.calls[0].request.headers["x-api-key"] == "prowlarr-key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_bazarr_with_api_key(self) -> None:
        route = respx.get("http://10.0.0.11:6767/api/system/status").mock(
            return_value=httpx.Response(200, json={"bazarr_version": "1.4.3"})
        )
        d = BazarrDetector()
        version = await d.get_installed_version("10.0.0.11", api_key="bazarr-key")
        assert version == "1.4.3"
        assert route.calls[0].request.headers["x-api-key"] == "bazarr-key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_sabnzbd_with_api_key(self) -> None:
        route = respx.get("http://10.0.0.7:8085/api?mode=version&output=json").mock(
            return_value=httpx.Response(200, json={"version": "4.2.1"})
        )
        d = SABnzbdDetector()
        version = await d.get_installed_version("10.0.0.7", api_key="sab-key")
        assert version == "4.2.1"
        assert route.calls[0].request.headers["x-api-key"] == "sab-key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_overseerr_with_api_key(self) -> None:
        route = respx.get("http://10.0.0.13:5055/api/v1/status").mock(
            return_value=httpx.Response(200, json={"version": "1.33.2"})
        )
        d = OverseerrDetector()
        version = await d.get_installed_version("10.0.0.13", api_key="overseerr-key")
        assert version == "1.33.2"
        assert route.calls[0].request.headers["x-api-key"] == "overseerr-key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_port_override(self) -> None:
        respx.get("http://10.0.0.1:9999/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        d = SonarrDetector()
        version = await d.get_installed_version("10.0.0.1", port=9999)
        assert version == "4.0.14.2939"

    @respx.mock
    @pytest.mark.asyncio
    async def test_port_and_api_key_combined(self) -> None:
        route = respx.get("http://10.0.0.1:9999/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        d = SonarrDetector()
        version = await d.get_installed_version("10.0.0.1", port=9999, api_key="combo-key")
        assert version == "4.0.14.2939"
        assert route.calls[0].request.headers["x-api-key"] == "combo-key"

    @respx.mock
    @pytest.mark.asyncio
    async def test_scheme_https_builds_correct_url(self) -> None:
        route = respx.get("https://10.0.0.1:8989/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.14.2939"})
        )
        d = SonarrDetector()
        version = await d.get_installed_version("10.0.0.1", scheme="https")
        assert version == "4.0.14.2939"
        assert str(route.calls[0].request.url).startswith("https://")

    @respx.mock
    @pytest.mark.asyncio
    async def test_scheme_https_with_port_override(self) -> None:
        route = respx.get("https://10.0.0.2:7878/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "5.6.0.8846"})
        )
        d = RadarrDetector()
        version = await d.get_installed_version("10.0.0.2", port=7878, scheme="https")
        assert version == "5.6.0.8846"
        assert str(route.calls[0].request.url).startswith("https://")


# -- Docker generic --

class TestDockerGeneric:
    def test_parse_image_version(self) -> None:
        assert DockerGenericDetector.parse_image_version("nginx:1.24.0") == "1.24.0"
        assert DockerGenericDetector.parse_image_version("nginx:latest") is None
        assert DockerGenericDetector.parse_image_version("nginx") is None
        assert DockerGenericDetector.parse_image_version("linuxserver/sonarr:4.0.0") == "4.0.0"
