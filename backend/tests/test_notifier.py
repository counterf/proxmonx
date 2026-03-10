"""Tests for NtfyNotifier."""

import pytest
import httpx
import respx

from app.core.notifier import NtfyNotifier


@pytest.mark.asyncio
class TestNtfyNotifier:

    @respx.mock
    async def test_send_success(self):
        route = respx.post("https://ntfy.example.com/alerts").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        notifier = NtfyNotifier(url="https://ntfy.example.com/alerts")
        result = await notifier.send("Test Title", "Test body", tags="warning")
        assert result is True
        assert route.called
        req = route.calls[0].request
        assert req.headers["Title"] == "Test Title"
        assert req.headers["Tags"] == "warning"
        assert req.headers["Priority"] == "3"
        assert req.content == b"Test body"

    @respx.mock
    async def test_send_with_auth_token(self):
        route = respx.post("https://ntfy.example.com/alerts").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        notifier = NtfyNotifier(
            url="https://ntfy.example.com/alerts",
            token="tk_secret123",
            priority=4,
        )
        result = await notifier.send("Title", "Body")
        assert result is True
        req = route.calls[0].request
        assert req.headers["Authorization"] == "Bearer tk_secret123"
        assert req.headers["Priority"] == "4"

    @respx.mock
    async def test_send_priority_override(self):
        respx.post("https://ntfy.example.com/alerts").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        notifier = NtfyNotifier(url="https://ntfy.example.com/alerts", priority=2)
        await notifier.send("Title", "Body", priority=5)
        req = respx.calls[0].request
        assert req.headers["Priority"] == "5"

    @respx.mock
    async def test_send_http_error_returns_false(self):
        respx.post("https://ntfy.example.com/alerts").mock(
            return_value=httpx.Response(403, text="forbidden"),
        )
        notifier = NtfyNotifier(url="https://ntfy.example.com/alerts")
        result = await notifier.send("Title", "Body")
        assert result is False

    @respx.mock
    async def test_send_network_error_returns_false(self):
        respx.post("https://ntfy.example.com/alerts").mock(
            side_effect=httpx.ConnectError("refused"),
        )
        notifier = NtfyNotifier(url="https://ntfy.example.com/alerts")
        result = await notifier.send("Title", "Body")
        assert result is False

    async def test_send_no_url_returns_false(self):
        notifier = NtfyNotifier(url="")
        result = await notifier.send("Title", "Body")
        assert result is False

    @respx.mock
    async def test_send_with_shared_client(self):
        route = respx.post("https://ntfy.example.com/alerts").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        async with httpx.AsyncClient() as client:
            notifier = NtfyNotifier(
                url="https://ntfy.example.com/alerts",
                http_client=client,
            )
            result = await notifier.send("Title", "Body")
        assert result is True
        assert route.called

    @respx.mock
    async def test_no_tags_header_when_empty(self):
        route = respx.post("https://ntfy.example.com/alerts").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        notifier = NtfyNotifier(url="https://ntfy.example.com/alerts")
        await notifier.send("Title", "Body", tags="")
        req = route.calls[0].request
        assert "Tags" not in req.headers
