"""Part 4 student implementation."""

from app.backends import ansible, netconf, netmiko_textfsm, restconf

# (method, action) -> (backend module, function name, argument kind).
# "name" passes the interface name; "interface" passes the whole
# desired interface dictionary.
ROUTES = {
    ("restconf", "status"): (restconf, "get_interface_state", "name"),
    ("restconf", "plan"): (restconf, "plan_interface", "interface"),
    ("restconf", "apply"): (restconf, "apply_interface", "interface"),
    ("netconf", "status"): (netconf, "get_interface_state", "name"),
    ("netconf", "plan"): (netconf, "plan_interface", "interface"),
    ("netconf", "apply"): (netconf, "apply_interface", "interface"),
    ("ansible", "apply"): (ansible, "apply_interface", "interface"),
    ("netmiko-textfsm", "status"): (
        netmiko_textfsm, "get_interface_state", "name",
    ),
    ("netmiko-textfsm", "delete"): (
        netmiko_textfsm, "delete_interface", "name",
    ),
}


def dispatch_request(data):
    module, function_name, argument = ROUTES[(data["method"], data["action"])]
    interface = data["desired"]["interface"]
    target = interface["name"] if argument == "name" else interface

    # Look the function up at call time so it can be replaced in tests.
    backend = getattr(module, function_name)
    return backend(data["router"], target)
