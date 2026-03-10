"""Ntfy notification sender."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class NtfyNotifier:
    """Sends push notifications via an ntfy server."""

    def __init__(
        self,
        url: str,
        token: str = "",
        priority: int = 3,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._priority = priority
        self._http_client = http_client

    async def send(
        self,
        title: str,
        message: str,
        tags: str = "",
        priority: int | None = None,
    ) -> bool:
        """POST a notification to the ntfy server.

        Returns True on success, False on failure.  Never raises.
        """
        if not self._url:
            logger.warning("ntfy URL not configured; skipping notification")
            return False

        headers: dict[str, str] = {
            "Title": title,
            "Priority": str(priority or self._priority),
        }
        if tags:
            headers["Tags"] = tags
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            if self._http_client:
                resp = await self._http_client.post(
                    self._url, content=message, headers=headers,
                )
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        self._url, content=message, headers=headers,
                    )
            if resp.status_code < 300:
                logger.info("ntfy notification sent: %s", title)
                return True
            logger.warning(
                "ntfy returned HTTP %d for '%s': %s",
                resp.status_code, title, resp.text[:200],
            )
        except Exception:
            logger.warning("Failed to send ntfy notification: %s", title, exc_info=True)
        return False
