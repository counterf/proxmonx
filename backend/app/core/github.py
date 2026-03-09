"""GitHub Releases API client with in-memory TTL cache."""

import contextlib
import logging
import time

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Cache TTL: 1 hour
CACHE_TTL_SECONDS = 3600


class GitHubClient:
    """Fetch latest release versions from GitHub with caching."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._token = settings.github_token
        self._cache: dict[str, tuple[str, float]] = {}  # repo -> (version, timestamp)
        self._http_client = http_client

    async def get_latest_version(self, repo: str) -> str | None:
        """Get the latest release version for a GitHub repo.

        Args:
            repo: Owner/repo format, e.g. "Sonarr/Sonarr"

        Returns:
            Version string (v prefix stripped) or None on failure.
        """
        if not repo:
            return None

        # Check cache
        cached = self._cache.get(repo)
        if cached:
            version, cached_at = cached
            if time.time() - cached_at < CACHE_TTL_SECONDS:
                logger.debug("Cache hit for %s: %s", repo, version)
                return version

        # Fetch from GitHub
        try:
            version = await self._fetch_latest(repo)
            if version:
                self._cache[repo] = (version, time.time())
            return version
        except Exception:
            logger.warning("Failed to fetch latest version for %s", repo)
            return None

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

            if response.status_code == 403:
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
            if resp.status_code == 200:
                releases: list[dict[str, str]] = resp.json()
                if releases:
                    tag = releases[0].get("tag_name", "")
                    return self._normalize_version(tag) if tag else None

            # Final fallback: tags API (e.g. qbittorrent uses release-x.y.z tags)
            resp = await c.get(
                f"https://api.github.com/repos/{repo}/tags?per_page=1", headers=headers
            )
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
