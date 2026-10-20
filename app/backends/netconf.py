import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from app.backends import planning
from app.backends.common import (
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    applied,
    error,
    error_from_exception,
    found,
    loopback_number,
    not_found,
    router_credentials,
    split_ipv4,
    to_cidr,
)


NETCONF_PORT = 830

IF_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"


def _connect(router):
    from ncclient import manager

    username, password = router_credentials()
    session = manager.connect(
        host=router,
        port=NETCONF_PORT,
        username=username,
        password=password,
        hostkey_verify=False,
        look_for_keys=False,
        allow_agent=False,
        timeout=CONNECT_TIMEOUT,
    )
    session.timeout = READ_TIMEOUT
    return session


def _real_get_config(router, filter_xml):
    with _connect(router) as session:
        reply = session.get_config(
            source="running",
            filter=("subtree", filter_xml),
        )
        return reply.xml


def _real_edit_config(router, config_xml):
    with _connect(router) as session:
        session.edit_config(target="running", config=config_xml)


def _status_filter(interface_name):
    return (
        f'<interfaces xmlns="{IF_NS}">'
        "<interface>"
        f"<name>{escape(interface_name)}</name>"
        "</interface>"
        "</interfaces>"
    )


def _text(element, path):
    child = element.find(path)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _normalize(xml_text, interface_name):
    """Find the requested interface in ietf-interfaces XML and normalize it."""
    root = ET.fromstring(xml_text)

    for interface in root.iter(f"{{{IF_NS}}}interface"):
        if _text(interface, f"{{{IF_NS}}}name") != interface_name:
            continue

        address = interface.find(
            f"{{{IP_NS}}}ipv4/{{{IP_NS}}}address"
        )
        ipv4 = None
        if address is not None:
            ipv4 = to_cidr(
                _text(address, f"{{{IP_NS}}}ip"),
                netmask=_text(address, f"{{{IP_NS}}}netmask"),
                prefix_length=_text(address, f"{{{IP_NS}}}prefix-length"),
            )

        # ietf-interfaces defaults "enabled" to true when absent.
        enabled = _text(interface, f"{{{IF_NS}}}enabled") or "true"

        return {
            "name": interface_name,
            "ipv4": ipv4,
            "description": _text(interface, f"{{{IF_NS}}}description"),
            "admin_state": "up" if enabled == "true" else "down",
        }

    return None


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    netconf_get_config = netconf_get_config or _real_get_config

    try:
        xml_text = netconf_get_config(router, _status_filter(interface_name))
    except Exception as exc:
        return error_from_exception(exc)

    try:
        interface = _normalize(xml_text, interface_name)
    except Exception:
        return error("backend_failed")

    if interface is None:
        return not_found()
    return found(interface)


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, netconf_get_config),
    )


def build_config(desired_interface):
    number = loopback_number(desired_interface["name"])
    address, netmask = split_ipv4(desired_interface["ipv4"])
    shutdown = "<shutdown/>" if desired_interface["admin_state"] == "down" else ""

    return (
        '<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0"'
        ' xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
        '<native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">'
        "<interface>"
        '<Loopback nc:operation="replace">'
        f"<name>{number}</name>"
        f"<description>{escape(desired_interface['description'])}</description>"
        "<ip><address><primary>"
        f"<address>{address}</address>"
        f"<mask>{netmask}</mask>"
        "</primary></address></ip>"
        f"{shutdown}"
        "</Loopback>"
        "</interface>"
        "</native>"
        "</config>"
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    netconf_edit_config = netconf_edit_config or _real_edit_config

    try:
        config_xml = build_config(desired_interface)
    except (KeyError, TypeError, ValueError):
        return error("backend_failed")

    try:
        netconf_edit_config(router, config_xml)
    except Exception as exc:
        return error_from_exception(exc)

    return applied()
