"""Generic Docker container detector.

Detects apps running as Docker containers by parsing image tags.
No upstream version check (no single GitHub repo).
"""

import logging

from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class DockerGenericDetector(BaseDetector):
    name = "docker"
    display_name = "Docker Container"
    github_repo = None
    aliases = []
    default_port = 0
    docker_images = []

    async def get_installed_version(self, host: str, port: int | None = None) -> str | None:
        # Generic Docker detector does not query a version endpoint.
        # Version is parsed from the image tag during Docker inspection.
        return None

    @staticmethod
    def parse_image_version(image: str) -> str | None:
        """Extract version tag from a Docker image string.

        Examples:
            "linuxserver/sonarr:4.0.0" -> "4.0.0"
            "nginx:latest" -> "latest"
            "nginx" -> None
        """
        if ":" in image:
            tag = image.split(":")[-1]
            return tag if tag != "latest" else None
        return None
