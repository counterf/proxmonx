"""Tests for API route helper functions."""

import pytest

from app.api.routes import _keep_or_replace


class TestKeepOrReplace:
    def test_none_incoming_keeps_existing(self) -> None:
        assert _keep_or_replace(None, "existing-secret") == "existing-secret"

    def test_empty_incoming_keeps_existing(self) -> None:
        assert _keep_or_replace("", "existing-secret") == "existing-secret"

    def test_masked_sentinel_keeps_existing(self) -> None:
        assert _keep_or_replace("***", "existing-secret") == "existing-secret"

    def test_new_value_replaces_existing(self) -> None:
        assert _keep_or_replace("new-secret", "old-secret") == "new-secret"

    def test_new_value_replaces_none(self) -> None:
        assert _keep_or_replace("new-secret", None) == "new-secret"

    def test_none_incoming_with_none_existing_returns_none(self) -> None:
        assert _keep_or_replace(None, None) is None

    def test_empty_incoming_with_none_existing_returns_none(self) -> None:
        assert _keep_or_replace("", None) is None

    def test_masked_sentinel_with_none_existing_returns_none(self) -> None:
        assert _keep_or_replace("***", None) is None

    def test_masked_sentinel_with_empty_existing_returns_none(self) -> None:
        assert _keep_or_replace("***", "") is None

    def test_whitespace_only_replaces(self) -> None:
        assert _keep_or_replace("  ", "old") == "  "
