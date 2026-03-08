"""Tests for GitHub client."""

import pytest
import httpx
import respx

from app.core.github import GitHubClient
from app.config import Settings


def _make_settings(**overrides: str | int | bool | None) -> Settings:
    defaults = {
        "proxmox_host": "https://localhost:8006",
        "proxmox_token_id": "test@pve!token",
        "proxmox_token_secret": "secret",
        "proxmox_node": "pve",
        "github_token": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestGitHubClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_fetch_latest_version(self) -> None:
        respx.get("https://api.github.com/repos/Sonarr/Sonarr/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v4.0.15.3012"})
        )
        client = GitHubClient(_make_settings())
        version = await client.get_latest_version("Sonarr/Sonarr")
        assert version == "4.0.15.3012"

    @respx.mock
    @pytest.mark.asyncio
    async def test_strips_v_prefix(self) -> None:
        respx.get("https://api.github.com/repos/test/repo/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v1.2.3"})
        )
        client = GitHubClient(_make_settings())
        version = await client.get_latest_version("test/repo")
        assert version == "1.2.3"

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_v_prefix(self) -> None:
        respx.get("https://api.github.com/repos/test/repo/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "2.0.0"})
        )
        client = GitHubClient(_make_settings())
        version = await client.get_latest_version("test/repo")
        assert version == "2.0.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_404_returns_none(self) -> None:
        respx.get("https://api.github.com/repos/test/norepo/releases/latest").mock(
            return_value=httpx.Response(404)
        )
        client = GitHubClient(_make_settings())
        version = await client.get_latest_version("test/norepo")
        assert version is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limit_returns_none(self) -> None:
        respx.get("https://api.github.com/repos/test/repo/releases/latest").mock(
            return_value=httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
        )
        client = GitHubClient(_make_settings())
        version = await client.get_latest_version("test/repo")
        assert version is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_caching(self) -> None:
        route = respx.get("https://api.github.com/repos/test/cached/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v1.0.0"})
        )
        client = GitHubClient(_make_settings())

        # First call hits API
        v1 = await client.get_latest_version("test/cached")
        assert v1 == "1.0.0"
        assert route.call_count == 1

        # Second call uses cache
        v2 = await client.get_latest_version("test/cached")
        assert v2 == "1.0.0"
        assert route.call_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_repo_returns_none(self) -> None:
        client = GitHubClient(_make_settings())
        version = await client.get_latest_version("")
        assert version is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_header_with_token(self) -> None:
        route = respx.get("https://api.github.com/repos/test/auth/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v1.0.0"})
        )
        client = GitHubClient(_make_settings(github_token="ghp_test123"))
        await client.get_latest_version("test/auth")
        assert route.call_count == 1
        request = route.calls[0].request
        assert "Bearer ghp_test123" in request.headers.get("Authorization", "")
