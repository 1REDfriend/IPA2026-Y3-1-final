import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.backends.common import (
    applied,
    error,
    error_from_exception,
    is_loopback_name,
    router_credentials,
    split_ipv4,
)


ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"
PLAYBOOK = ANSIBLE_DIR / "apply_interface.yml"
INVENTORY = ANSIBLE_DIR / "inventory.ini"

# Must finish inside the 20 second Live window, including Ansible start-up.
PLAYBOOK_TIMEOUT = 18

# ansible-playbook exit code when a host is unreachable.
RC_UNREACHABLE = 4

AUTH_MARKERS = (
    "authentication failed",
    "authentication failure",
    "permission denied",
    "invalid credentials",
)
CONNECTION_MARKERS = (
    "unreachable",
    "timed out",
    "timeout",
    "connection refused",
    "no route to host",
    "unable to connect",
)


def build_variables(router, desired_interface):
    # The playbook writes raw IOS lines, so only Loopback<number> is allowed:
    # a typo must never reconfigure a physical or management interface.
    if not is_loopback_name(desired_interface["name"]):
        raise ValueError("Ansible apply is limited to Loopback interfaces")
    description = desired_interface["description"]
    if not isinstance(description, str) or not description.isprintable():
        # A newline here would inject extra IOS configuration lines.
        raise ValueError("description must be a single printable line")
    address, netmask = split_ipv4(desired_interface["ipv4"])
    return {
        "router": router,
        "interface_name": desired_interface["name"],
        "description": desired_interface["description"],
        "ipv4_address": address,
        "netmask": netmask,
        "shutdown": desired_interface["admin_state"] == "down",
    }


def _real_run_playbook(variables):
    username, password = router_credentials()
    env = {
        **os.environ,
        "ROUTER_USER": username,
        "ROUTER_PASS": password,
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        "ANSIBLE_RETRY_FILES_ENABLED": "False",
        "ANSIBLE_NOCOLOR": "1",
    }

    # Pass variables as a JSON file so types (e.g. the shutdown boolean)
    # and special characters in the description survive unchanged.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False
    ) as handle:
        json.dump(variables, handle)
        vars_file = handle.name

    try:
        completed = subprocess.run(
            [
                "ansible-playbook",
                "-i", str(INVENTORY),
                str(PLAYBOOK),
                "-e", f"@{vars_file}",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=PLAYBOOK_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("ansible-playbook timed out") from exc
    finally:
        os.unlink(vars_file)

    if completed.returncode == 0:
        return

    output = (completed.stdout + completed.stderr).lower()
    if any(marker in output for marker in AUTH_MARKERS):
        raise PermissionError("router rejected the credentials")
    if completed.returncode == RC_UNREACHABLE or any(
        marker in output for marker in CONNECTION_MARKERS
    ):
        raise ConnectionError("router unreachable")
    raise RuntimeError(f"ansible-playbook failed with rc={completed.returncode}")


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    run_playbook = run_playbook or _real_run_playbook

    try:
        variables = build_variables(router, desired_interface)
    except (KeyError, TypeError, ValueError):
        return error("backend_failed")

    try:
        run_playbook(variables)
    except Exception as exc:
        return error_from_exception(exc)

    return applied()
