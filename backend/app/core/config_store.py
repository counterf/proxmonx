"""Config file persistence layer for UI-driven settings."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node")


class ConfigStore:
    """Manages reading/writing of /app/data/config.json."""

    def __init__(self, path: str = "/app/data/config.json") -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, str | int | bool | None]:
        """Read config file if it exists, return its contents as a dict."""
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                logger.error("Config file is not a JSON object, ignoring: %s", self._path)
                return {}
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to read config file %s: %s", self._path, exc)
            return {}

    def save(self, data: dict[str, str | int | bool | None]) -> None:
        """Atomic write: write to .tmp then rename. Sets 0o600 permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self._path)
            logger.info("Settings saved via UI")
        except OSError as exc:
            # Clean up temp file on failure
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to write config file: {exc}") from exc

    def is_configured(self) -> bool:
        """True if all required Proxmox fields are non-empty (from file or env)."""
        return len(self.get_missing_fields()) == 0

    def get_missing_fields(self) -> list[str]:
        """Return names of required fields that are missing or empty."""
        file_data = self.load()
        missing: list[str] = []
        for field in REQUIRED_FIELDS:
            # Check config file first, then env var
            value = file_data.get(field) or os.environ.get(field.upper(), "") or os.environ.get(field, "")
            if not value:
                missing.append(field)
        return missing

    def merge_into_settings(self, settings: Settings) -> Settings:
        """Return a new Settings instance with config file values taking priority over env/defaults."""
        from app.config import Settings as SettingsCls  # local import avoids circular dep at module level

        config_data = self.load()
        if not config_data:
            return settings
        current = settings.model_dump()
        for key, value in config_data.items():
            if key in current and value is not None:
                current[key] = value
        return SettingsCls(**current)
