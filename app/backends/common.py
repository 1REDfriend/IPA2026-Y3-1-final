"""Helpers shared by all backend adapters."""

import os
import re
from ipaddress import IPv4Interface


# Per-request network timeout in seconds. Live grading waits 20 seconds
# for router cases, so a single backend call must finish well before that.
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 12

LOOPBACK_PREFIX = "Loopback"


def error(code):
    return {"status": "error", "result": code}


def found(interface):
    return {"status": "ok", "result": "found", "interface": interface}


def not_found():
    return {"status": "ok", "result": "not_found", "interface": None}


def applied():
    return {"status": "ok", "result": "applied"}


def router_credentials():
    """Return (username, password) supplied through the environment."""
    return os.environ.get("ROUTER_USER", ""), os.environ.get("ROUTER_PASS", "")


INTERFACE_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9/.:-]{0,63}")
LOOPBACK_NAME_PATTERN = re.compile(r"Loopback[0-9]{1,10}")


def is_safe_interface_name(interface_name):
    """True for a plain IOS interface name with no spaces or CLI syntax."""
    return isinstance(interface_name, str) and bool(
        INTERFACE_NAME_PATTERN.fullmatch(interface_name)
    )


def is_loopback_name(interface_name):
    """True only for Loopback<number>; changes are restricted to these."""
    return isinstance(interface_name, str) and bool(
        LOOPBACK_NAME_PATTERN.fullmatch(interface_name)
    )


def loopback_number(interface_name):
    """Return the Cisco native Loopback key, e.g. Loopback123 -> 123."""
    if not is_loopback_name(interface_name):
        raise ValueError(f"not a Loopback interface: {interface_name}")
    return int(interface_name[len(LOOPBACK_PREFIX):])


def split_ipv4(cidr):
    """Return (address, netmask) for an IPv4 CIDR string."""
    ipv4 = IPv4Interface(cidr)
    return str(ipv4.ip), str(ipv4.network.netmask)


def to_cidr(address, netmask=None, prefix_length=None):
    """Return CIDR text from an address plus a netmask or prefix length."""
    if address is None:
        return None
    suffix = prefix_length if prefix_length is not None else netmask
    if suffix is None:
        return None
    return str(IPv4Interface(f"{address}/{suffix}"))


def _auth_exceptions():
    classes = [PermissionError]
    try:
        from ncclient.transport.errors import AuthenticationError
        classes.append(AuthenticationError)
    except ImportError:
        pass
    try:
        from netmiko.exceptions import NetmikoAuthenticationException
        classes.append(NetmikoAuthenticationException)
    except ImportError:
        pass
    try:
        from paramiko.ssh_exception import AuthenticationException
        classes.append(AuthenticationException)
    except ImportError:
        pass
    return tuple(classes)


def _backend_exceptions():
    # Checked before the connection group: these are protocol-level
    # failures whose classes may inherit from OSError.
    classes = []
    try:
        from requests.exceptions import (
            ConnectionError as RequestsConnectionError,
            RequestException,
            Timeout,
        )
    except ImportError:
        pass
    else:
        classes.append((RequestException, (RequestsConnectionError, Timeout)))
    try:
        from ncclient.operations.rpc import RPCError
        classes.append((RPCError, ()))
    except ImportError:
        pass
    return classes


def _connection_exceptions():
    classes = [ConnectionError, TimeoutError, OSError]
    try:
        from requests.exceptions import ConnectionError as RequestsConnectionError
        from requests.exceptions import Timeout
        classes += [RequestsConnectionError, Timeout]
    except ImportError:
        pass
    try:
        from ncclient.transport.errors import TransportError
        from ncclient.operations.errors import TimeoutExpiredError
        classes += [TransportError, TimeoutExpiredError]
    except ImportError:
        pass
    try:
        from netmiko.exceptions import NetmikoTimeoutException
        classes.append(NetmikoTimeoutException)
    except ImportError:
        pass
    try:
        from paramiko.ssh_exception import SSHException
        classes.append(SSHException)
    except ImportError:
        pass
    return tuple(classes)


def error_from_exception(exc):
    """Map any backend exception to the common backend error response."""
    if isinstance(exc, _auth_exceptions()):
        return error("authentication_failed")
    for backend_class, connection_subclasses in _backend_exceptions():
        if isinstance(exc, backend_class) and not isinstance(
            exc, connection_subclasses
        ):
            return error("backend_failed")
    if isinstance(exc, _connection_exceptions()):
        return error("connection_failed")
    return error("backend_failed")
