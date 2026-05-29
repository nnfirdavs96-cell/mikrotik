"""MikroTik RouterOS API client.

All MikroTik management is performed exclusively through the RouterOS API
(ports 8728 / 8729-SSL). No SSH / telnet / WinBox / CLI is used.

The client is intentionally defensive: every method raises a MikroTikError on
failure so the calling service layer can log it and keep the application
running even when the router is unreachable.
"""
import ssl
from typing import Any, Dict, List, Optional

from ..config import settings

try:  # librouteros is optional at import time so the app can boot without it.
    from librouteros import connect as ros_connect

    LIBROUTEROS_AVAILABLE = True
except Exception:  # pragma: no cover - only triggered when lib is missing
    ros_connect = None
    LIBROUTEROS_AVAILABLE = False


class MikroTikError(Exception):
    """Raised for any MikroTik API related failure."""


class MikroTikAPIClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: Optional[int] = None,
        use_ssl: bool = False,
        timeout: Optional[int] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.use_ssl = bool(use_ssl)
        self.port = int(port or (8729 if self.use_ssl else 8728))
        self.timeout = timeout or settings.MIKROTIK_TIMEOUT
        self._api = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def connect(self):
        """1. connect() — open a RouterOS API connection."""
        if not LIBROUTEROS_AVAILABLE:
            raise MikroTikError(
                "librouteros library is not installed (pip install librouteros)"
            )
        try:
            kwargs: Dict[str, Any] = dict(
                username=self.username,
                password=self.password,
                host=self.host,
                port=self.port,
                timeout=self.timeout,
            )
            if self.use_ssl:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                kwargs["ssl_wrapper"] = lambda sock: ctx.wrap_socket(
                    sock, server_hostname=self.host
                )
            self._api = ros_connect(**kwargs)
            return self._api
        except Exception as exc:  # noqa: BLE001
            raise MikroTikError(f"Connection failed: {exc}") from exc

    @property
    def api(self):
        if self._api is None:
            self.connect()
        return self._api

    def close(self):
        try:
            if self._api is not None:
                self._api.close()
        except Exception:  # pragma: no cover
            pass
        finally:
            self._api = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def check_connection(self) -> Dict[str, Any]:
        """2. check_connection() — verify the router is reachable."""
        try:
            resource = self.get_system_resource()
            return {"success": True, "message": "Connected", "data": resource}
        except MikroTikError as exc:
            return {
                "success": False,
                "message": "MikroTik API connection failed",
                "details": str(exc),
            }
        finally:
            self.close()

    def get_system_resource(self) -> Dict[str, Any]:
        """3. get_system_resource() — read /system/resource."""
        try:
            data = list(self.api.path("system", "resource"))
            return data[0] if data else {}
        except MikroTikError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MikroTikError(f"get_system_resource failed: {exc}") from exc

    # ------------------------------------------------------------------
    # DHCP leases
    # ------------------------------------------------------------------
    def get_dhcp_leases(self) -> List[Dict[str, Any]]:
        """4. get_dhcp_leases() — list /ip/dhcp-server/lease."""
        try:
            leases = []
            for item in self.api.path("ip", "dhcp-server", "lease"):
                leases.append(
                    {
                        "address": item.get("address"),
                        "mac_address": item.get("mac-address"),
                        "hostname": item.get("host-name"),
                        "status": item.get("status"),
                        "dynamic": item.get("dynamic"),
                        "comment": item.get("comment"),
                    }
                )
            return leases
        except MikroTikError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MikroTikError(f"get_dhcp_leases failed: {exc}") from exc

    def find_lease_by_ip(self, ip_address: str) -> Optional[Dict[str, Any]]:
        """5. find_lease_by_ip(ip_address)."""
        for lease in self.get_dhcp_leases():
            if lease.get("address") == ip_address:
                return lease
        return None

    def find_lease_by_mac(self, mac_address: str) -> Optional[Dict[str, Any]]:
        """6. find_lease_by_mac(mac_address)."""
        target = (mac_address or "").upper()
        for lease in self.get_dhcp_leases():
            if (lease.get("mac_address") or "").upper() == target:
                return lease
        return None

    def get_online_clients(self) -> List[Dict[str, Any]]:
        """7. get_online_clients() — devices that currently hold a lease."""
        leases = self.get_dhcp_leases()
        bound = [l for l in leases if (l.get("status") or "bound") == "bound"]
        # If RouterOS does not report status, fall back to all leases.
        return bound or leases

    # ------------------------------------------------------------------
    # Firewall address-list
    # ------------------------------------------------------------------
    def _find_addr_list_entry(
        self, ip_address: str, list_name: str
    ) -> Optional[Dict[str, Any]]:
        for item in self.api.path("ip", "firewall", "address-list"):
            if item.get("address") == ip_address and item.get("list") == list_name:
                return item
        return None

    def add_ip_to_allowed_list(
        self,
        ip_address: str,
        phone: Optional[str],
        mac_address: Optional[str],
        client_id: Optional[int],
        list_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """8. add_ip_to_allowed_list(...) — never creates a duplicate."""
        list_name = list_name or settings.DEFAULT_ALLOWED_LIST
        try:
            existing = self._find_addr_list_entry(ip_address, list_name)
            if existing:
                return {
                    "success": True,
                    "already": True,
                    "message": "IP already in list",
                    "id": existing.get(".id"),
                }
            comment = (
                f"wifi-client | phone={phone} | mac={mac_address} "
                f"| client_id={client_id}"
            )
            path = self.api.path("ip", "firewall", "address-list")
            new_id = path.add(list=list_name, address=ip_address, comment=comment)
            return {"success": True, "message": "IP added", "id": new_id}
        except MikroTikError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MikroTikError(f"add_ip_to_allowed_list failed: {exc}") from exc

    def remove_ip_from_allowed_list(
        self, ip_address: str, list_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """9. remove_ip_from_allowed_list(...) — missing IP is not an error."""
        list_name = list_name or settings.DEFAULT_ALLOWED_LIST
        try:
            entry = self._find_addr_list_entry(ip_address, list_name)
            if not entry:
                return {
                    "success": True,
                    "not_found": True,
                    "message": "IP was not found in allowed_clients",
                }
            path = self.api.path("ip", "firewall", "address-list")
            path.remove(entry.get(".id"))
            return {"success": True, "message": "IP removed"}
        except MikroTikError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MikroTikError(f"remove_ip_from_allowed_list failed: {exc}") from exc

    def is_ip_in_allowed_list(
        self, ip_address: str, list_name: Optional[str] = None
    ) -> bool:
        """10. is_ip_in_allowed_list(...)."""
        list_name = list_name or settings.DEFAULT_ALLOWED_LIST
        return self._find_addr_list_entry(ip_address, list_name) is not None

    def get_allowed_clients(
        self, list_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """11. get_allowed_clients(...) — entries currently in the list."""
        list_name = list_name or settings.DEFAULT_ALLOWED_LIST
        try:
            out = []
            for item in self.api.path("ip", "firewall", "address-list"):
                if item.get("list") == list_name:
                    out.append(
                        {
                            "id": item.get(".id"),
                            "address": item.get("address"),
                            "comment": item.get("comment"),
                        }
                    )
            return out
        except MikroTikError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MikroTikError(f"get_allowed_clients failed: {exc}") from exc

    def sync_allowed_clients(
        self,
        active_clients: List[Dict[str, Any]],
        list_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """12. sync_allowed_clients(...) — reconcile the list with the DB.

        ``active_clients`` is a list of dicts: {ip, phone, mac, client_id}.
        """
        list_name = list_name or settings.DEFAULT_ALLOWED_LIST
        result = {"added": 0, "removed": 0, "already": 0, "errors": []}

        desired = {c["ip"]: c for c in active_clients if c.get("ip")}
        current = {e["address"]: e for e in self.get_allowed_clients(list_name)}

        # Add the IPs that should be present but are missing.
        for ip, client in desired.items():
            if ip in current:
                result["already"] += 1
                continue
            try:
                self.add_ip_to_allowed_list(
                    ip,
                    client.get("phone"),
                    client.get("mac"),
                    client.get("client_id"),
                    list_name,
                )
                result["added"] += 1
            except MikroTikError as exc:
                result["errors"].append(str(exc))

        # Remove entries that should no longer be there.
        for ip in current:
            if ip not in desired:
                try:
                    self.remove_ip_from_allowed_list(ip, list_name)
                    result["removed"] += 1
                except MikroTikError as exc:
                    result["errors"].append(str(exc))

        return result
