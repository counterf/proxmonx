"""Tests for API route helper functions."""

import pytest
from pydantic import ValidationError

from app.api.routes import _AppConfigBase, GuestConfigSaveRequest, _keep_or_replace


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


class TestAppConfigGithubRepo:
    def test_normalizes_https_url(self) -> None:
        m = _AppConfigBase(github_repo="https://github.com/owner/repo")
        assert m.github_repo == "owner/repo"

    def test_passthrough_owner_repo(self) -> None:
        m = _AppConfigBase(github_repo="owner/repo")
        assert m.github_repo == "owner/repo"

    def test_garbage_raises(self) -> None:
        with pytest.raises(ValidationError):
            _AppConfigBase(github_repo="not-a-valid-repo")


class TestGuestConfigForcedDetector:
    def test_valid_forced_detector(self) -> None:
        m = GuestConfigSaveRequest(forced_detector="sonarr")
        assert m.forced_detector == "sonarr"

    def test_empty_normalized_to_none(self) -> None:
        m = GuestConfigSaveRequest(forced_detector="")
        assert m.forced_detector is None

    def test_unknown_detector_raises(self) -> None:
        with pytest.raises(ValidationError):
            GuestConfigSaveRequest(forced_detector="not-a-detector")
