"""GitHub Releases API client with in-memory TTL cache."""

import logging
import time

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Cache TTL: 1 hour
CACHE_TTL_SECONDS = 3600


class GitHubClient:
    """Fetch latest release versions from GitHub with caching."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.github_token
        self._cache: dict[str, tuple[str, float]] = {}  # repo -> (version, timestamp)

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

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 404:
                logger.debug("No releases found for %s", repo)
                return None

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

    @staticmethod
    def _normalize_version(tag: str) -> str:
        """Strip common prefixes from version tags."""
        tag = tag.strip()
        if tag.startswith("v"):
            tag = tag[1:]
        return tag
