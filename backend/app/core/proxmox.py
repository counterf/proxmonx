"""Async Proxmox API client (read-only)."""

import logging

import httpx

from app.config import ProxmoxHostConfig
from app.models.guest import GuestInfo

logger = logging.getLogger(__name__)


class DiscoveryError(Exception):
    """Raised when guest discovery fails completely (no data from any endpoint)."""


class ProxmoxClient:
    """Read-only async client for the Proxmox VE API."""

    def __init__(
        self,
        host_config: ProxmoxHostConfig,
        discover_vms: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = f"{host_config.host}/api2/json"
        self._node = host_config.node
        self._headers = {
            "Authorization": f"PVEAPIToken={host_config.token_id}={host_config.token_secret}",
        }
        self._discover_vms = discover_vms
        self._http_client = http_client

    async def _get(self, path: str) -> dict[str, list[dict[str, str | int | float | bool | None]] | dict[str, str | int | float | bool | None]]:
        """Execute a GET request against the Proxmox API."""
        url = f"{self._base_url}{path}"
        if self._http_client:
            response = await self._http_client.get(url, headers=self._headers)
            response.raise_for_status()
            return response.json()
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            data: dict[str, list[dict[str, str | int | float | bool | None]] | dict[str, str | int | float | bool | None]] = response.json()
            return data

    async def _post(self, path: str, data: dict | None = None) -> dict:
        """Execute a POST request against the Proxmox API."""
        url = f"{self._base_url}{path}"
        if self._http_client:
            response = await self._http_client.post(url, headers=self._headers, json=data or {})
            response.raise_for_status()
            return response.json()
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            response = await client.post(url, headers=self._headers, json=data or {})
            response.raise_for_status()
            return response.json()

    async def guest_action(
        self,
        vmid: str,
        guest_type: str,   # "lxc" or "qemu"
        action: str,       # "start"|"stop"|"shutdown"|"restart"|"snapshot"
        snapshot_name: str | None = None,
    ) -> str:
        """Execute a lifecycle action on a guest. Returns the UPID task string."""
        resource = "lxc" if guest_type == "lxc" else "qemu"
        base = f"/nodes/{self._node}/{resource}/{vmid}"

        if action == "snapshot":
            result = await self._post(f"{base}/snapshot", {
                "snapname": snapshot_name,
                "description": "Created by proxmon",
            })
        else:
            # Both LXC and QEMU use "reboot" instead of "restart"
            pve_action = "reboot" if action == "restart" else action
            result = await self._post(f"{base}/status/{pve_action}")

        return str(result.get("data", ""))

    async def list_guests(self) -> list[GuestInfo]:
        """Discover all LXC containers and optionally VMs."""
        guests: list[GuestInfo] = []
        any_success = False

        # LXC containers
        try:
            data = await self._get(f"/nodes/{self._node}/lxc")
            raw_list = data.get("data", [])
            if isinstance(raw_list, list):
                for ct in raw_list:
                    guest = self._parse_guest(ct, "lxc")
                    if guest:
                        guests.append(guest)
            any_success = True
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
                any_success = True
                logger.info("Discovered %d VMs", vm_count)
            except Exception:
                logger.exception("Failed to list VMs")

        if not any_success:
            raise DiscoveryError(
                f"Failed to discover any guests from {self._node}"
            )

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

            # For LXCs, "disk" is actual used bytes; for VMs it's cumulative I/O — unusable.
            # VM disk usage is populated later from agent/get-fsinfo in _process_guest.
            if guest_type == "lxc":
                disk_used = int(raw.get("disk", 0)) or None
            else:
                disk_used = None
            disk_total = int(raw.get("maxdisk", 0)) or None

            return GuestInfo(
                id=vmid,
                name=name,
                type=guest_type,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                tags=tags,
                disk_used=disk_used,
                disk_total=disk_total,
            )
        except Exception:
            logger.exception("Failed to parse guest: %s", raw)
            return None

    async def create_backup(
        self,
        vmid: str,
        storage: str,
        compress: str = "zstd",
        mode: str = "snapshot",
    ) -> str:
        """Trigger a vzdump backup via Proxmox API. Returns UPID."""
        result = await self._post(f"/nodes/{self._node}/vzdump", {
            "vmid": vmid,
            "storage": storage,
            "compress": compress,
            "mode": mode,
        })
        return str(result.get("data", ""))

    async def get_task_status(self, upid: str) -> dict:
        """Poll a Proxmox task by UPID. Returns data dict with 'status' and 'exitstatus'."""
        result = await self._get(f"/nodes/{self._node}/tasks/{upid}/status")
        data = result.get("data", {})
        return data if isinstance(data, dict) else {}

    async def list_backup_storages(self) -> list[dict]:
        """Return storages on this node that support backup content."""
        result = await self._get(f"/nodes/{self._node}/storage?content=backup")
        raw = result.get("data", [])
        if not isinstance(raw, list):
            return []
        return [{"storage": s.get("storage"), "type": s.get("type"), "avail": s.get("avail")} for s in raw if s.get("storage")]

    async def get_guest_network(self, vmid: str, guest_type: str) -> tuple[str | None, str | None]:
        """Resolve a guest's IP address and OS type from the Proxmox API.

        Returns (ip, os_type).

        Strategy 1: parse static IP from LXC/VM config (net0 ip= field).
        Strategy 2: query /interfaces endpoint for live IPs (works with DHCP).
        """
        endpoint = "lxc" if guest_type == "lxc" else "qemu"
        os_type: str | None = None
        ip: str | None = None

        try:
            data = await self._get(f"/nodes/{self._node}/{endpoint}/{vmid}/config")
            config = data.get("data", {})
            if isinstance(config, dict):
                raw_os = config.get("ostype")
                if raw_os:
                    os_type = str(raw_os)

                for key in ["net0", "net1", "ipconfig0", "ipconfig1"]:
                    net_str = str(config.get(key, ""))
                    if "ip=" in net_str:
                        for part in net_str.split(","):
                            if part.startswith("ip="):
                                candidate = part[3:].split("/")[0]
                                if candidate and candidate != "dhcp":
                                    ip = candidate
                                    break
                    if ip:
                        break
        except Exception:
            logger.debug("Could not resolve IP from config for guest %s", vmid)

        if ip:
            return ip, os_type

        # Fallback: live interface list (handles DHCP-assigned IPs)
        if guest_type == "lxc":
            # LXC: /lxc/{vmid}/interfaces — flat list with inet field
            try:
                ifaces_data = await self._get(
                    f"/nodes/{self._node}/lxc/{vmid}/interfaces"
                )
                ifaces = ifaces_data.get("data", [])
                if isinstance(ifaces, list):
                    for iface in ifaces:
                        name = str(iface.get("name", ""))
                        inet = str(iface.get("inet", ""))
                        if inet and name != "lo" and not inet.startswith("127."):
                            candidate = inet.split("/")[0]
                            if candidate:
                                return candidate, os_type
            except Exception:
                logger.debug("Could not resolve IP from interfaces for guest %s", vmid)
        else:
            # VM: /qemu/{vmid}/agent/network-get-interfaces — requires QEMU guest agent
            try:
                data = await self._get(
                    f"/nodes/{self._node}/qemu/{vmid}/agent/network-get-interfaces"
                )
                result = data.get("data", {})
                if isinstance(result, dict):
                    result = result.get("result", [])
                if isinstance(result, list):
                    for iface in result:
                        name = str(iface.get("name", ""))
                        if name == "lo":
                            continue
                        for addr in iface.get("ip-addresses", []):
                            if addr.get("ip-address-type") == "ipv4":
                                candidate = str(addr.get("ip-address", ""))
                                if candidate and not candidate.startswith("127."):
                                    return candidate, os_type
            except Exception:
                logger.debug("Could not resolve IP from guest agent for VM %s", vmid)

        return None, os_type

    async def get_vm_disk_usage(self, vmid: str) -> tuple[int | None, int | None]:
        """Return (used_bytes, total_bytes) for a VM via agent/get-fsinfo.

        Uses the root filesystem ('/') only. Returns (None, None) if the
        guest agent is unavailable or no root filesystem is reported.
        """
        try:
            data = await self._get(
                f"/nodes/{self._node}/qemu/{vmid}/agent/get-fsinfo"
            )
            result = data.get("data", {})
            if isinstance(result, dict):
                result = result.get("result", [])
            if not isinstance(result, list):
                return None, None

            VIRTUAL_TYPES = {"tmpfs", "devtmpfs", "proc", "sysfs",
                             "cgroup", "cgroup2", "overlay", "squashfs", "devpts"}

            fs = next(
                (
                    f for f in result
                    if f.get("mountpoint") == "/"
                    and f.get("type", "").lower() not in VIRTUAL_TYPES
                    and int(f.get("total-bytes", 0)) > 0
                ),
                None,
            )
            if fs is None:
                return None, None

            used = int(fs.get("used-bytes", 0)) or None
            total = int(fs.get("total-bytes", 0)) or None
            return used, total
        except Exception:
            logger.debug("Could not get disk usage from guest agent for VM %s", vmid)
            return None, None
