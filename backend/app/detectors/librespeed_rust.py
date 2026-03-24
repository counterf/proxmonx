"""LibreSpeed (Rust) — ProxmoxVE community-scripts style CT; no JSON version HTTP API."""

import re

import httpx

from app.detectors.base import BaseDetector


class LibreSpeedRustDetector(BaseDetector):
    """speedtest-rust (https://github.com/librespeed/speedtest-rust); default UI :8080.

    Upstream does not expose a semver over HTTP. Set per-guest ``ssh_version_cmd`` to a
    command that prints the installed version (e.g. the packaged binary's ``--version``).
    """

    name = "librespeed-rust"
    display_name = "LibreSpeed"
    github_repo = "librespeed/speedtest-rust"
    aliases = ["librespeed_rust", "speedtest-rust", "speedtest_rust"]
    default_port = 8080
    docker_images = [
        "librespeed/speedtest-rust",
        "ghcr.io/librespeed/speedtest-rust",
        "speedtest-rust",
    ]

    def _name_matches(self, guest_name: str) -> bool:
        tokens = set(re.split(r"[-_.\s]+", guest_name.lower()))
        if "librespeed" in tokens and "rust" in tokens:
            return True
        if "speedtest" in tokens and "rust" in tokens:
            return True
        return super()._name_matches(guest_name)

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
        http_client: httpx.AsyncClient | None = None,
    ) -> str | None:
        return None
