"""Tests for auth utilities and session store."""

import pytest

from app.core.auth import hash_password, verify_password
from app.core.session_store import SessionStore


class TestPasswordHashing:
    def test_hash_and_verify_password(self) -> None:
        hashed = hash_password("secret123")
        assert verify_password("secret123", hashed) is True

    def test_wrong_password_rejected(self) -> None:
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_hash_format(self) -> None:
        hashed = hash_password("test")
        parts = hashed.split(":")
        assert len(parts) == 3
        assert parts[0] == "scrypt"

    def test_different_salts_produce_different_hashes(self) -> None:
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # different salts
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_invalid_hash_format_returns_false(self) -> None:
        assert verify_password("pass", "invalid") is False
        assert verify_password("pass", "scrypt:bad") is False
        assert verify_password("pass", "") is False


class TestSessionStore:
    def test_session_create_and_validate(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path / "test.db"))
        token = store.create()
        assert store.is_valid(token) is True

    def test_session_expired(self, tmp_path) -> None:
        # ttl_seconds=-1 places expires_at in the past without any sleep.
        store = SessionStore(str(tmp_path / "test.db"), ttl_seconds=-1)
        token = store.create()
        assert store.is_valid(token) is False

    def test_session_revoke(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path / "test.db"))
        token = store.create()
        assert store.is_valid(token) is True
        store.revoke(token)
        assert store.is_valid(token) is False

    def test_invalid_token_returns_false(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path / "test.db"))
        assert store.is_valid("nonexistent") is False

    def test_cleanup_expired(self, tmp_path) -> None:
        store = SessionStore(str(tmp_path / "test.db"), ttl_seconds=-1)
        store.create()
        store.create()
        store.cleanup_expired()
        # All tokens should be gone -- creating a new one should work fine
        new_token = SessionStore(str(tmp_path / "test.db"), ttl_seconds=3600).create()
        assert SessionStore(str(tmp_path / "test.db")).is_valid(new_token) is True
