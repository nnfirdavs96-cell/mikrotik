"""Generate and apply the MikroTik firewall rules needed by the system.

All managed rules carry the comment prefix ``WAM:`` so they can be listed and
removed safely. The ``drop`` rule is scoped to the guest subnet only, so it can
never lock out the admin network or the API.
"""
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..config import settings
from ..mikrotik.client import MikroTikError
from ..mikrotik.service import build_client, get_active_device
from .logs import log_access

TAG = "WAM:"


def default_server() -> tuple:
    """Return (host, port) of the portal server derived from PUBLIC_BASE_URL."""
    base = settings.PUBLIC_BASE_URL or ""
    host, port = "", "8000"
    if base:
        p = urlparse(base if "//" in base else "//" + base)
        host = p.hostname or ""
        port = str(p.port or 8000)
    return host, port


def build_ruleset(
    guest_network: str,
    server_ip: str,
    server_port: str,
    wan: str,
    allowed_list: str,
    captive: bool,
):
    """Return (rules, preview_lines).

    rules: list of (section_tuple, kwargs) for apply_firewall_rules().
    preview_lines: human-readable RouterOS-style commands.
    """
    rules = []
    preview = []

    def filt(comment, **kw):
        kw["chain"] = "forward"
        kw["comment"] = f"{TAG} {comment}"
        rules.append((("ip", "firewall", "filter"), kw))

    def nat(comment, **kw):
        kw["comment"] = f"{TAG} {comment}"
        rules.append((("ip", "firewall", "nat"), kw))

    # --- filter (forward): accepts first, drop last (append order preserved) ---
    filt("allow paid clients", **{"src-address-list": allowed_list, "action": "accept"})
    filt("allow portal", **{"src-address": guest_network, "dst-address": server_ip, "action": "accept"})
    filt("allow DNS udp", **{"src-address": guest_network, "protocol": "udp", "dst-port": "53", "action": "accept"})
    filt("allow DNS tcp", **{"src-address": guest_network, "protocol": "tcp", "dst-port": "53", "action": "accept"})
    filt("allow DHCP", **{"src-address": guest_network, "protocol": "udp", "dst-port": "67,68", "action": "accept"})
    filt("block unpaid", **{"src-address": guest_network, "action": "drop"})

    # --- nat: no-nat to portal first, then masquerade ---
    nat("no-nat guest->portal", **{"chain": "srcnat", "src-address": guest_network, "dst-address": server_ip, "action": "accept"})
    masq = {"chain": "srcnat", "src-address": guest_network, "action": "masquerade"}
    if wan:
        masq["out-interface-list"] = wan
    nat("masquerade guest", **masq)

    if captive:
        nat(
            "captive redirect",
            **{
                "chain": "dstnat",
                "src-address": guest_network,
                "src-address-list": f"!{allowed_list}",
                "protocol": "tcp",
                "dst-port": "80",
                "action": "dst-nat",
                "to-addresses": server_ip,
                "to-ports": server_port,
            },
        )

    # Build preview text
    preview.append("/ip firewall filter")
    preview.append(f'add chain=forward src-address-list={allowed_list} action=accept comment="{TAG} allow paid clients"')
    preview.append(f'add chain=forward src-address={guest_network} dst-address={server_ip} action=accept comment="{TAG} allow portal"')
    preview.append(f'add chain=forward src-address={guest_network} protocol=udp dst-port=53 action=accept comment="{TAG} allow DNS udp"')
    preview.append(f'add chain=forward src-address={guest_network} protocol=tcp dst-port=53 action=accept comment="{TAG} allow DNS tcp"')
    preview.append(f'add chain=forward src-address={guest_network} protocol=udp dst-port=67,68 action=accept comment="{TAG} allow DHCP"')
    preview.append(f'add chain=forward src-address={guest_network} action=drop comment="{TAG} block unpaid"')
    preview.append("/ip firewall nat")
    preview.append(f'add chain=srcnat src-address={guest_network} dst-address={server_ip} action=accept comment="{TAG} no-nat guest->portal"')
    preview.append(f'add chain=srcnat src-address={guest_network} action=masquerade {("out-interface-list=" + wan + " ") if wan else ""}comment="{TAG} masquerade guest"')
    if captive:
        preview.append(f'add chain=dstnat src-address={guest_network} src-address-list=!{allowed_list} protocol=tcp dst-port=80 action=dst-nat to-addresses={server_ip} to-ports={server_port} comment="{TAG} captive redirect"')

    return rules, preview


def apply_ruleset(db: Session, **params) -> dict:
    device = get_active_device(db)
    if device is None:
        return {"success": False, "message": "No active MikroTik device configured"}
    rules, _ = build_ruleset(**params)
    client = build_client(device)
    try:
        res = client.apply_firewall_rules(rules)
        log_access(
            db,
            action="firewall_apply",
            mikrotik_id=device.id,
            actor="admin",
            mikrotik_result=f"added={res['added']} skipped={res['skipped']} errors={len(res['errors'])}",
            error_message="; ".join(res["errors"]) or None,
        )
        return {"success": True, **res}
    except MikroTikError as exc:
        log_access(db, action="firewall_apply", mikrotik_id=device.id, actor="admin", error_message=str(exc))
        return {"success": False, "message": "MikroTik API connection failed", "details": str(exc)}
    finally:
        client.close()


def remove_ruleset(db: Session) -> dict:
    device = get_active_device(db)
    if device is None:
        return {"success": False, "message": "No active MikroTik device configured"}
    client = build_client(device)
    try:
        res = client.remove_managed_firewall(TAG)
        log_access(db, action="firewall_remove", mikrotik_id=device.id, actor="admin",
                   mikrotik_result=f"removed={res.get('removed', 0)}")
        return {"success": True, **res}
    except MikroTikError as exc:
        log_access(db, action="firewall_remove", mikrotik_id=device.id, actor="admin", error_message=str(exc))
        return {"success": False, "message": "MikroTik API connection failed", "details": str(exc)}
    finally:
        client.close()


def current_rules(db: Session) -> dict:
    device = get_active_device(db)
    if device is None:
        return {"success": False, "message": "No active MikroTik device", "rules": []}
    client = build_client(device)
    try:
        return {"success": True, "rules": client.list_managed_firewall(TAG)}
    except MikroTikError as exc:
        return {"success": False, "message": "MikroTik API connection failed",
                "details": str(exc), "rules": []}
    finally:
        client.close()
