"""Base detector abstract class."""

import contextlib
import re
from abc import ABC, abstractmethod

import httpx

from app.models.guest import GuestInfo


class BaseDetector(ABC):
    """Every detector plugin must implement this interface."""

    name: str  # e.g. "sonarr"
    display_name: str  # e.g. "Sonarr"
    github_repo: str | None  # e.g. "Sonarr/Sonarr"
    aliases: list[str]  # alternative name matches
    default_port: int
    docker_images: list[str]  # Docker image name patterns
    http_client: httpx.AsyncClient | None = None

    def _name_matches(self, guest_name: str) -> bool:
        """Word-boundary/token matching to avoid substring false positives."""
        name_tokens = set(re.split(r'[-_.\s]+', guest_name.lower()))
        return self.name in name_tokens or any(alias in name_tokens for alias in self.aliases)

    def detect(self, guest: GuestInfo) -> str | None:
        """Check if this detector matches a guest by name or tags.

        Returns the detection method string or None.
        """
        # Check tags first (higher priority per PRD)
        for tag in guest.tags:
            tag_lower = tag.lower()
            if tag_lower == self.name or tag_lower == f"app:{self.name}":
                return "tag_match"
            for alias in self.aliases:
                if tag_lower == alias or tag_lower == f"app:{alias}":
                    return "tag_match"

        # Check guest name using token matching
        if self._name_matches(guest.name):
            return "name_match"

        return None

    def match_docker_image(self, image: str) -> bool:
        """Return True if a Docker image string matches this app."""
        image_lower = image.lower()
        for pattern in self.docker_images:
            if pattern in image_lower:
                return True
        return False

    @abstractmethod
    async def get_installed_version(self, host: str, port: int | None = None) -> str | None:
        """Query the app's local API for its version.

        Args:
            host: Guest IP address.
            port: Override port (uses default_port if None).
        """
        ...

    async def _http_get(self, url: str, timeout: float = 5.0) -> httpx.Response:
        """Helper for making HTTP GET requests to guest apps."""
        ctx = contextlib.nullcontext(self.http_client) if self.http_client else httpx.AsyncClient(timeout=timeout, verify=False)
        async with ctx as client:
            return await client.get(url)
