"""GitHub Releases API client with in-memory TTL cache."""

from __future__ import annotations

import contextlib
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Cache TTL: 1 hour
CACHE_TTL_SECONDS = 3600


def parse_github_repo(value: str) -> str:
    """Normalize to 'owner/repo'. Accepts full GitHub URLs or bare owner/repo."""
    v = value.strip()
    if not v:
        raise ValueError("Empty repo string")
    if "github.com" in v or v.startswith("http"):
        if not v.startswith("http"):
            v = "https://" + v
        path = urlparse(v).path.strip("/").removesuffix(".git")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        raise ValueError(f"Cannot extract owner/repo from URL: {value!r}")
    if re.match(r"^[^\s/]+/[^\s/]+$", v):
        return v
    raise ValueError(f"Expected 'owner/repo' or GitHub URL, got: {value!r}")


@dataclass
class GitHubTestResult:
    ok: bool
    repo: str
    version: str | None
    source: str | None
    reason: str | None


class GitHubClient:
    """Fetch latest release versions from GitHub with caching."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._token = settings.github_token
        self._cache: dict[str, tuple[str, float]] = {}  # repo -> (version, timestamp)
        self._http_client = http_client

    async def get_latest_version(self, repo: str, bypass_cache: bool = False) -> str | None:
        """Get the latest release version for a GitHub repo.

        Args:
            repo: Owner/repo format, e.g. "Sonarr/Sonarr"
            bypass_cache: When True, always fetch from the API (still updates cache on success).

        Returns:
            Version string (v prefix stripped) or None on failure.
        """
        if not repo:
            return None

        if not bypass_cache:
            cached = self._cache.get(repo)
            if cached:
                version, cached_at = cached
                if time.time() - cached_at < CACHE_TTL_SECONDS:
                    logger.debug("Cache hit for %s: %s", repo, version)
                    return version

        try:
            version = await self._fetch_latest(repo)
            if version:
                self._cache[repo] = (version, time.time())
            return version
        except Exception:
            logger.warning("Failed to fetch latest version for %s", repo)
            return None

    async def test_repo(self, raw_input: str) -> GitHubTestResult:
        try:
            repo = parse_github_repo(raw_input)
        except ValueError:
            stripped = raw_input.strip()
            return GitHubTestResult(
                ok=False,
                repo=stripped if stripped else raw_input,
                version=None,
                source=None,
                reason="invalid_url",
            )

        try:
            version, source, reason = await self._fetch_with_detail(repo)
        except httpx.TimeoutException:
            return GitHubTestResult(
                ok=False, repo=repo, version=None, source=None, reason="network_error"
            )
        except httpx.ConnectError:
            return GitHubTestResult(
                ok=False, repo=repo, version=None, source=None, reason="network_error"
            )
        except Exception:
            logger.exception("Unexpected error testing GitHub repo %s", repo)
            return GitHubTestResult(
                ok=False, repo=repo, version=None, source=None, reason="unknown"
            )

        if version:
            self._cache[repo] = (version, time.time())
            return GitHubTestResult(
                ok=True, repo=repo, version=version, source=source, reason=None
            )
        return GitHubTestResult(
            ok=False,
            repo=repo,
            version=None,
            source=None,
            reason=reason or "unknown",
        )

    async def _fetch_with_detail(
        self, repo: str
    ) -> tuple[str | None, str | None, str | None]:
        """Return (version, source, reason). Reason is set only on failure."""
        headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        ctx = contextlib.nullcontext(self._http_client) if self._http_client else httpx.AsyncClient(timeout=10.0)
        async with ctx as c:
            url_latest = f"https://api.github.com/repos/{repo}/releases/latest"
            response = await c.get(url_latest, headers=headers)

            if response.status_code in (403, 429):
                return None, None, "rate_limited"

            if response.status_code == 200:
                data: dict[str, str] = response.json()
                tag = data.get("tag_name", "")
                if tag:
                    return self._normalize_version(tag), "releases/latest", None
                return None, None, "no_releases_or_tags"

            if response.status_code != 404:
                response.raise_for_status()
                return None, None, "unknown"

            # 404 on latest — try releases list then tags (same as _fetch_latest)
            resp = await c.get(
                f"https://api.github.com/repos/{repo}/releases?per_page=1",
                headers=headers,
            )
            if resp.status_code in (403, 429):
                return None, None, "rate_limited"
            if resp.status_code == 200:
                releases: list[dict[str, str]] = resp.json()
                if releases:
                    tag = releases[0].get("tag_name", "")
                    if tag:
                        return self._normalize_version(tag), "releases_list", None
            elif resp.status_code not in (404,):
                resp.raise_for_status()
                return None, None, "unknown"

            resp = await c.get(
                f"https://api.github.com/repos/{repo}/tags?per_page=1",
                headers=headers,
            )
            if resp.status_code in (403, 429):
                return None, None, "rate_limited"
            if resp.status_code == 404:
                return None, None, "not_found"
            if resp.status_code == 200:
                tags: list[dict[str, str]] = resp.json()
                if tags:
                    tag = tags[0].get("name", "")
                    if tag:
                        return self._normalize_version(tag), "tags", None
                return None, None, "no_releases_or_tags"
            resp.raise_for_status()
            return None, None, "unknown"

    async def _fetch_latest(self, repo: str) -> str | None:
        """Make the actual API call to GitHub."""
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        ctx = contextlib.nullcontext(self._http_client) if self._http_client else httpx.AsyncClient(timeout=10.0)
        async with ctx as c:
            response = await c.get(url, headers=headers)

            if response.status_code == 404:
                # Some repos only publish pre-releases or use tags; fall back
                return await self._fetch_latest_from_list(repo, headers)

            if response.status_code in (403, 429):
                remaining = response.headers.get("x-ratelimit-remaining", "?")
                logger.warning(
                    "GitHub rate limit hit for %s (remaining: %s)", repo, remaining
                )
                return None

            response.raise_for_status()
            data: dict[str, str] = response.json()
            tag = data.get("tag_name", "")
            return self._normalize_version(tag)

    async def _fetch_latest_from_list(
        self, repo: str, headers: dict[str, str]
    ) -> str | None:
        """Fallback: releases list → tags (handles pre-release-only / tag-only repos)."""
        ctx = contextlib.nullcontext(self._http_client) if self._http_client else httpx.AsyncClient(timeout=10.0)
        async with ctx as c:
            resp = await c.get(
                f"https://api.github.com/repos/{repo}/releases?per_page=1", headers=headers
            )
            if resp.status_code in (403, 429):
                remaining = resp.headers.get("x-ratelimit-remaining", "?")
                logger.warning("GitHub rate limit hit for %s (remaining: %s)", repo, remaining)
                return None
            if resp.status_code == 200:
                releases: list[dict[str, str]] = resp.json()
                if releases:
                    tag = releases[0].get("tag_name", "")
                    return self._normalize_version(tag) if tag else None

            # Final fallback: tags API (e.g. qbittorrent uses release-x.y.z tags)
            resp = await c.get(
                f"https://api.github.com/repos/{repo}/tags?per_page=1", headers=headers
            )
            if resp.status_code in (403, 429):
                remaining = resp.headers.get("x-ratelimit-remaining", "?")
                logger.warning("GitHub rate limit hit for %s (remaining: %s)", repo, remaining)
                return None
            if resp.status_code == 200:
                tags: list[dict[str, str]] = resp.json()
                if tags:
                    tag = tags[0].get("name", "")
                    return self._normalize_version(tag) if tag else None

        logger.debug("No release or tag found for %s", repo)
        return None

    @staticmethod
    def _normalize_version(tag: str) -> str:
        """Strip common prefixes (v1.0, release-1.0, etc.)."""
        tag = tag.strip()
        for prefix in ("release-", "v"):
            if tag.startswith(prefix):
                tag = tag[len(prefix):]
                break
        return tag
