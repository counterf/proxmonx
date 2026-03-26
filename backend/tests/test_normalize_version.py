"""Tests for normalize_version utility."""

import pytest

from app.detectors.utils import normalize_version


class TestNormalizeVersion:
    def test_plex_hash_suffix_stripped(self) -> None:
        assert normalize_version("1.40.0.7998-c29d4c0c8") == "1.40.0.7998"

    def test_prerelease_tag_preserved(self) -> None:
        assert normalize_version("1.41.0-rc.1") == "1.41.0-rc.1"

    def test_v_prefix_stripped(self) -> None:
        assert normalize_version("v1.2.3", strip_v=True) == "1.2.3"

    def test_v_prefix_kept(self) -> None:
        assert normalize_version("v1.2.3", strip_v=False) == "v1.2.3"

    def test_short_hex_suffix_preserved(self) -> None:
        # Only 3 hex chars -- not long enough to be a build hash
        assert normalize_version("1.2.3-abc") == "1.2.3-abc"

    def test_already_clean(self) -> None:
        assert normalize_version("1.2.3") == "1.2.3"

    def test_long_hex_suffix_stripped(self) -> None:
        assert normalize_version("2.0.0-deadbeef") == "2.0.0"

    def test_v_prefix_and_hash(self) -> None:
        assert normalize_version("v1.40.0.7998-c29d4c0c8", strip_v=True) == "1.40.0.7998"
