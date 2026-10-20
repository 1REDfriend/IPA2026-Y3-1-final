from urllib.parse import quote

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


YANG_JSON = "application/yang-data+json"
HEADERS = {"Accept": YANG_JSON, "Content-Type": YANG_JSON}

SUCCESS_CODES = (200, 201, 204)
AUTH_FAILURE_CODES = (401, 403)


def _status_url(router, interface_name):
    name = quote(interface_name, safe="")
    return (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={name}"
    )


def _apply_url(router, number):
    return (
        f"https://{router}/restconf/data/"
        f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
    )


def _session():
    import requests
    import urllib3

    # Lab routers use self-signed certificates.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.auth = router_credentials()
    session.headers.update(HEADERS)
    session.verify = False
    return session


def _real_http_get(url):
    with _session() as session:
        return session.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))


def _real_http_put(url, json):
    with _session() as session:
        return session.put(
            url, json=json, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )


def _normalize(raw, interface_name):
    """Convert ietf-interfaces JSON into the normalized interface dict."""
    data = raw["ietf-interfaces:interface"]
    if isinstance(data, list):
        data = next(
            (item for item in data if item.get("name") == interface_name),
            None,
        )
        if data is None:
            return None

    addresses = (data.get("ietf-ip:ipv4") or {}).get("address") or []
    ipv4 = None
    if addresses:
        first = addresses[0]
        ipv4 = to_cidr(
            first.get("ip"),
            netmask=first.get("netmask"),
            prefix_length=first.get("prefix-length"),
        )

    return {
        "name": data["name"],
        "ipv4": ipv4,
        "description": data.get("description"),
        # ietf-interfaces defaults "enabled" to true when absent.
        "admin_state": "up" if data.get("enabled", True) else "down",
    }


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    http_get = http_get or _real_http_get

    try:
        response = http_get(_status_url(router, interface_name))
    except Exception as exc:
        return error_from_exception(exc)

    if response.status_code == 404:
        return not_found()
    if response.status_code in AUTH_FAILURE_CODES:
        return error("authentication_failed")
    if response.status_code != 200:
        return error("backend_failed")

    try:
        interface = _normalize(response.json(), interface_name)
    except Exception:
        return error("backend_failed")

    if interface is None:
        return not_found()
    return found(interface)


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, http_get),
    )


def build_payload(desired_interface):
    number = loopback_number(desired_interface["name"])
    address, netmask = split_ipv4(desired_interface["ipv4"])

    loopback = {
        "name": number,
        "description": desired_interface["description"],
        "ip": {
            "address": {
                "primary": {
                    "address": address,
                    "mask": netmask,
                }
            }
        },
    }
    if desired_interface["admin_state"] == "down":
        loopback["shutdown"] = [None]

    return number, {"Cisco-IOS-XE-native:Loopback": loopback}


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    http_put = http_put or _real_http_put

    try:
        number, payload = build_payload(desired_interface)
    except (KeyError, TypeError, ValueError):
        return error("backend_failed")

    try:
        response = http_put(_apply_url(router, number), json=payload)
    except Exception as exc:
        return error_from_exception(exc)

    if response.status_code in SUCCESS_CODES:
        return applied()
    if response.status_code in AUTH_FAILURE_CODES:
        return error("authentication_failed")
    return error("backend_failed")
