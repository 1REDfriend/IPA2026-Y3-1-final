import yaml


ALLOWED_ROUTERS = (
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
)

# Capability matrix: which actions each method supports.
METHOD_ACTIONS = {
    "restconf": ("status", "plan", "apply"),
    "netconf": ("status", "plan", "apply"),
    "ansible": ("apply",),
    "netmiko-textfsm": ("status", "delete"),
}

# Actions that require a complete desired interface definition.
FULL_STATE_ACTIONS = ("plan", "apply")

ADMIN_STATES = ("up", "down")


def error(code):
    return {"status": "error", "result": code}


def _missing(mapping, key):
    return mapping.get(key) is None


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    if not isinstance(data, dict):
        return error("invalid_yaml")

    # bool is a subclass of int, so check the exact type.
    version = data.get("version")
    if type(version) is not int or version != 1:
        return error("invalid_version")

    if _missing(data, "router"):
        return error("missing_router")
    if data["router"] not in ALLOWED_ROUTERS:
        return error("invalid_router")

    if _missing(data, "method"):
        return error("missing_method")
    method = data["method"]
    if not isinstance(method, str) or method not in METHOD_ACTIONS:
        return error("invalid_method")

    if _missing(data, "action"):
        return error("missing_action")
    action = data["action"]
    if action not in METHOD_ACTIONS[method]:
        return error("invalid_action")

    if _missing(data, "desired"):
        return error("missing_desired")
    desired = data["desired"]
    if not isinstance(desired, dict) or _missing(desired, "interface"):
        return error("missing_interface")
    interface = desired["interface"]
    if not isinstance(interface, dict) or _missing(interface, "name"):
        return error("missing_interface_name")

    if action in FULL_STATE_ACTIONS:
        for field in ("ipv4", "description", "admin_state"):
            if _missing(interface, field):
                return error(f"missing_{field}")
        if interface["admin_state"] not in ADMIN_STATES:
            return error("invalid_admin_state")

    return {"status": "ok", "result": "accepted"}


def load_request_file(path):
    """
    Read and parse a YAML request file.

    Return (data, None) on success, or (None, error_response) when the
    file cannot be read or parsed.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f), None
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None, error("invalid_yaml")


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    data, load_error = load_request_file(path)
    if load_error is not None:
        return load_error
    return validate_request(data)
