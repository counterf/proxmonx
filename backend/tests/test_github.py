"""Tests for GitHub client."""

import pytest
import httpx
import respx

from app.core.github import GitHubClient, parse_github_repo
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


class TestParseGithubRepo:
    def test_passthrough_owner_repo(self) -> None:
        assert parse_github_repo("Sonarr/Sonarr") == "Sonarr/Sonarr"

    def test_https_url(self) -> None:
        assert parse_github_repo("https://github.com/Sonarr/Sonarr") == "Sonarr/Sonarr"

    def test_git_suffix(self) -> None:
        assert parse_github_repo("https://github.com/foo/bar.git") == "foo/bar"

    def test_no_scheme_github_host(self) -> None:
        assert parse_github_repo("github.com/foo/bar") == "foo/bar"

    def test_trailing_slash(self) -> None:
        assert parse_github_repo("https://github.com/foo/bar/") == "foo/bar"

    def test_url_only_owner_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot extract"):
            parse_github_repo("https://github.com/foo")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty"):
            parse_github_repo("   ")

    def test_garbage_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected"):
            parse_github_repo("not-a-valid-repo")


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
        respx.get("https://api.github.com/repos/test/norepo/releases?per_page=1").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://api.github.com/repos/test/norepo/tags?per_page=1").mock(
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


class TestGitHubClientTestRepo:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success_releases_latest(self) -> None:
        route = respx.get("https://api.github.com/repos/o/r/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v1.2.3"})
        )
        client = GitHubClient(_make_settings())
        result = await client.test_repo("o/r")
        assert result.ok is True
        assert result.repo == "o/r"
        assert result.version == "1.2.3"
        assert result.source == "releases/latest"
        assert result.reason is None
        assert route.call_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_url_input_normalized_in_result(self) -> None:
        respx.get("https://api.github.com/repos/Sonarr/Sonarr/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v4.0.0"})
        )
        client = GitHubClient(_make_settings())
        result = await client.test_repo("https://github.com/Sonarr/Sonarr")
        assert result.ok is True
        assert result.repo == "Sonarr/Sonarr"
        assert result.version == "4.0.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_not_found_all_404(self) -> None:
        respx.get("https://api.github.com/repos/owner/nonexistent/releases/latest").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://api.github.com/repos/owner/nonexistent/releases?per_page=1").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://api.github.com/repos/owner/nonexistent/tags?per_page=1").mock(
            return_value=httpx.Response(404)
        )
        client = GitHubClient(_make_settings())
        result = await client.test_repo("owner/nonexistent")
        assert result.ok is False
        assert result.reason == "not_found"

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limited_403(self) -> None:
        respx.get("https://api.github.com/repos/x/y/releases/latest").mock(
            return_value=httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
        )
        client = GitHubClient(_make_settings())
        result = await client.test_repo("x/y")
        assert result.ok is False
        assert result.reason == "rate_limited"

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limited_429(self) -> None:
        respx.get("https://api.github.com/repos/x/y/releases/latest").mock(
            return_value=httpx.Response(429)
        )
        client = GitHubClient(_make_settings())
        result = await client.test_repo("x/y")
        assert result.ok is False
        assert result.reason == "rate_limited"

    @respx.mock
    @pytest.mark.asyncio
    async def test_invalid_url(self) -> None:
        client = GitHubClient(_make_settings())
        result = await client.test_repo("@@@")
        assert result.ok is False
        assert result.reason == "invalid_url"

    @respx.mock
    @pytest.mark.asyncio
    async def test_fallback_releases_list(self) -> None:
        respx.get("https://api.github.com/repos/o/r/releases/latest").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://api.github.com/repos/o/r/releases?per_page=1").mock(
            return_value=httpx.Response(200, json=[{"tag_name": "v2.0.0"}])
        )
        client = GitHubClient(_make_settings())
        result = await client.test_repo("o/r")
        assert result.ok is True
        assert result.source == "releases_list"
        assert result.version == "2.0.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_fallback_tags(self) -> None:
        respx.get("https://api.github.com/repos/o/r/releases/latest").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://api.github.com/repos/o/r/releases?per_page=1").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://api.github.com/repos/o/r/tags?per_page=1").mock(
            return_value=httpx.Response(200, json=[{"name": "release-1.2.3"}])
        )
        client = GitHubClient(_make_settings())
        result = await client.test_repo("o/r")
        assert result.ok is True
        assert result.source == "tags"
        assert result.version == "1.2.3"

    @respx.mock
    @pytest.mark.asyncio
    async def test_test_repo_hits_api_when_cache_warm(self) -> None:
        latest = respx.get("https://api.github.com/repos/test/cached/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v1.0.0"})
        )
        client = GitHubClient(_make_settings())
        await client.get_latest_version("test/cached")
        assert latest.call_count == 1
        result = await client.test_repo("test/cached")
        assert result.ok is True
        assert latest.call_count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_bypass_cache_on_get_latest_version(self) -> None:
        route = respx.get("https://api.github.com/repos/test/bypass/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v1.0.0"})
        )
        client = GitHubClient(_make_settings())
        await client.get_latest_version("test/bypass")
        assert route.call_count == 1
        await client.get_latest_version("test/bypass", bypass_cache=True)
        assert route.call_count == 2
