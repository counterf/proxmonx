"""Async Proxmox API client (read-only)."""

import logging

import httpx

from app.config import Settings
from app.models.guest import GuestInfo

logger = logging.getLogger(__name__)


class ProxmoxClient:
    """Read-only async client for the Proxmox VE API."""

    # Safety: only GET requests are allowed
    ALLOWED_METHODS = frozenset({"GET"})

    def __init__(self, settings: Settings) -> None:
        self._base_url = f"{settings.proxmox_host}/api2/json"
        self._node = settings.proxmox_node
        self._headers = {
            "Authorization": f"PVEAPIToken={settings.proxmox_token_id}={settings.proxmox_token_secret}",
        }
        self._verify_ssl = settings.verify_ssl
        self._discover_vms = settings.discover_vms

    async def _get(self, path: str) -> dict[str, list[dict[str, str | int | float | bool | None]] | dict[str, str | int | float | bool | None]]:
        """Execute a GET request against the Proxmox API."""
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=10.0) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            data: dict[str, list[dict[str, str | int | float | bool | None]] | dict[str, str | int | float | bool | None]] = response.json()
            return data

    async def list_guests(self) -> list[GuestInfo]:
        """Discover all LXC containers and optionally VMs."""
        guests: list[GuestInfo] = []

        # LXC containers
        try:
            data = await self._get(f"/nodes/{self._node}/lxc")
            raw_list = data.get("data", [])
            if isinstance(raw_list, list):
                for ct in raw_list:
                    guest = self._parse_guest(ct, "lxc")
                    if guest:
                        guests.append(guest)
            logger.info("Discovered %d LXC containers", len(guests))
        except Exception:
            logger.exception("Failed to list LXC containers")

        # VMs (optional)
        if self._discover_vms:
            vm_count = 0
            try:
                data = await self._get(f"/nodes/{self._node}/qemu")
                raw_list = data.get("data", [])
                if isinstance(raw_list, list):
                    for vm in raw_list:
                        guest = self._parse_guest(vm, "vm")
                        if guest:
                            guests.append(guest)
                            vm_count += 1
                logger.info("Discovered %d VMs", vm_count)
            except Exception:
                logger.exception("Failed to list VMs")

        return guests

    def _parse_guest(
        self,
        raw: dict[str, str | int | float | bool | None],
        guest_type: str,
    ) -> GuestInfo | None:
        """Parse a raw Proxmox API guest object into a GuestInfo."""
        try:
            vmid = str(raw.get("vmid", ""))
            name = str(raw.get("name", f"guest-{vmid}"))
            status_raw = str(raw.get("status", "stopped")).lower()
            status = "running" if status_raw == "running" else "stopped"

            # Parse tags (comma or semicolon separated)
            tags_raw = str(raw.get("tags", ""))
            tags = [t.strip() for t in tags_raw.replace(";", ",").split(",") if t.strip()]

            return GuestInfo(
                id=vmid,
                name=name,
                type=guest_type,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                tags=tags,
            )
        except Exception:
            logger.exception("Failed to parse guest: %s", raw)
            return None

    async def get_guest_network(self, vmid: str, guest_type: str) -> str | None:
        """Attempt to resolve a guest's IP address from Proxmox API."""
        try:
            endpoint = "lxc" if guest_type == "lxc" else "qemu"
            data = await self._get(f"/nodes/{self._node}/{endpoint}/{vmid}/config")
            config = data.get("data", {})
            if isinstance(config, dict):
                # LXC: parse net0 field like "name=eth0,bridge=vmbr0,ip=10.0.0.101/24,..."
                for key in ["net0", "net1", "ipconfig0", "ipconfig1"]:
                    net_str = str(config.get(key, ""))
                    if "ip=" in net_str:
                        for part in net_str.split(","):
                            if part.startswith("ip="):
                                ip = part[3:].split("/")[0]
                                if ip and ip != "dhcp":
                                    return ip
        except Exception:
            logger.debug("Could not resolve IP for guest %s", vmid)
        return None

    async def check_connection(self) -> bool:
        """Test connectivity to the Proxmox API."""
        try:
            await self._get("/version")
            return True
        except Exception:
            logger.warning("Proxmox API unreachable")
            return False
