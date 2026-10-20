from app.backends.common import (
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    error,
    error_from_exception,
    found,
    not_found,
    router_credentials,
    to_cidr,
)


# IOS abbreviations seen in "show interfaces description".
ABBREVIATIONS = {
    "lo": "loopback",
    "gi": "gigabitethernet",
    "te": "tengigabitethernet",
    "fa": "fastethernet",
    "et": "ethernet",
    "tu": "tunnel",
    "vl": "vlan",
    "po": "port-channel",
}


def canonical_name(name):
    """Normalize an IOS interface name so Lo123 matches Loopback123."""
    name = (name or "").strip().lower()
    index = 0
    while index < len(name) and name[index].isalpha():
        index += 1
    prefix, rest = name[:index], name[index:]
    return ABBREVIATIONS.get(prefix, prefix) + rest


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_interface(interface_name, ip_info, descriptions):
    """
    Build the normalized interface from parsed TextFSM records.
    Return None when the interface is absent.
    """
    target = canonical_name(interface_name)

    record = next(
        (r for r in ip_info if canonical_name(r.get("interface")) == target),
        None,
    )
    if record is None:
        return None

    addresses = _as_list(record.get("ip_address"))
    prefixes = _as_list(record.get("prefix_length"))
    ipv4 = None
    if addresses and prefixes:
        ipv4 = to_cidr(addresses[0], prefix_length=prefixes[0])

    link_status = (record.get("link_status") or "").lower()
    admin_state = "down" if "administratively down" in link_status else "up"

    description = None
    for entry in descriptions:
        if canonical_name(entry.get("port")) == target:
            description = (entry.get("description") or "").strip() or None
            break

    return {
        "name": interface_name,
        "ipv4": ipv4,
        "description": description,
        "admin_state": admin_state,
    }


def _connect(router):
    from netmiko import ConnectHandler

    username, password = router_credentials()
    return ConnectHandler(
        device_type="cisco_ios",
        host=router,
        username=username,
        password=password,
        conn_timeout=CONNECT_TIMEOUT,
        auth_timeout=CONNECT_TIMEOUT,
        banner_timeout=CONNECT_TIMEOUT,
        read_timeout_override=READ_TIMEOUT,
    )


def _parse(command, output):
    from ntc_templates.parse import parse_output

    try:
        return parse_output(platform="cisco_ios", command=command, data=output)
    except Exception as exc:
        raise RuntimeError(f"TextFSM could not parse '{command}'") from exc


def _read_state(connection, interface_name):
    """Run the two read-only commands and return parsed records."""
    output = connection.send_command(f"show ip interface {interface_name}")
    # IOS rejects the name when the interface does not exist.
    if "% Invalid" in output or not output.strip():
        ip_info = []
    else:
        ip_info = _parse("show ip interface", output)

    output = connection.send_command("show interfaces description")
    descriptions = _parse("show interfaces description", output)
    return ip_info, descriptions


def _real_netmiko_get(router, interface_name):
    with _connect(router) as connection:
        return _read_state(connection, interface_name)


def _real_netmiko_delete(router, interface_name):
    with _connect(router) as connection:
        if normalize_interface(
            interface_name, *_read_state(connection, interface_name)
        ) is None:
            return "not_found"

        connection.send_config_set([f"no interface {interface_name}"])

        if normalize_interface(
            interface_name, *_read_state(connection, interface_name)
        ) is not None:
            raise RuntimeError(f"{interface_name} still present after delete")
        return "deleted"


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    netmiko_get = netmiko_get or _real_netmiko_get

    try:
        ip_info, descriptions = netmiko_get(router, interface_name)
    except Exception as exc:
        return error_from_exception(exc)

    try:
        interface = normalize_interface(interface_name, ip_info, descriptions)
    except Exception:
        return error("backend_failed")

    if interface is None:
        return not_found()
    return found(interface)


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    netmiko_delete = netmiko_delete or _real_netmiko_delete

    try:
        result = netmiko_delete(router, interface_name)
    except Exception as exc:
        return error_from_exception(exc)

    if result == "deleted":
        return {"status": "ok", "result": "deleted"}
    if result == "not_found":
        return not_found()
    return error("backend_failed")
