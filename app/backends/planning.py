from app.planner import build_plan


def plan_interface(
    router,
    desired_interface,
    get_interface_state,
):
    """Build a Part 2 plan from backend status."""
    status = get_interface_state(router, desired_interface["name"])

    if status.get("status") != "ok":
        return status

    if status.get("result") == "found":
        current_interface = status["interface"]
    else:
        current_interface = None

    return build_plan(desired_interface, current_interface)
