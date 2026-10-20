MANAGED_FIELDS = ("ipv4", "description", "admin_state")


def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    if current_interface is None:
        operation = "create"
        changes = {
            field: {"to": desired_interface[field]}
            for field in MANAGED_FIELDS
        }
    else:
        changes = {
            field: {
                "from": current_interface.get(field),
                "to": desired_interface[field],
            }
            for field in MANAGED_FIELDS
            if current_interface.get(field) != desired_interface[field]
        }
        operation = "update" if changes else "no_change"

    return {
        "status": "ok",
        "result": "planned",
        "operation": operation,
        "changes": changes,
    }
