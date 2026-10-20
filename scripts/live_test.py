"""
Drive the student bot through real Webex messages and check its replies.

Messages are sent with the tester's own Personal Access Token
(WEBEX_TESTER_TOKEN), as a real @mention of the bot plus one YAML file,
exactly like a person would in the room.

    python scripts/live_test.py                      # validation cases only
    python scripts/live_test.py --router 10.0.29.103 # + full router sequence

Router cases only touch Loopback<student-id> and stop before any change if
that interface exists with a description that is not ours.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://webexapis.com/v1"
ROOT = Path(__file__).resolve().parents[1]

# Seconds Live grading waits for a reply.
LIMIT_NO_ROUTER = 10
LIMIT_ROUTER = 20


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class Tester:
    def __init__(self, token, room_title, bot_email):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.me = self._get("/people/me")["id"]
        self.room_id = self._find_room(room_title)
        self.bot_email = bot_email
        self.bot_id = self._get("/people", email=bot_email)["items"][0]["id"]

    def _get(self, path, **params):
        response = self.session.get(API + path, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def _find_room(self, title):
        rooms = self._get("/rooms", type="group", max=200)["items"]
        for room in rooms:
            if room["title"] == title:
                return room["id"]
        sys.exit(f"room not found for the tester: {title!r}")

    def send(self, yaml_text=None):
        mention = f"<@personEmail:{self.bot_email}|bot>"
        data = {"roomId": self.room_id, "markdown": mention}
        files = None
        if yaml_text is not None:
            files = {"files": ("request.yaml", yaml_text.encode(), "text/yaml")}
        response = self.session.post(
            API + "/messages", data=data, files=files, timeout=30
        )
        response.raise_for_status()
        return response.json()

    def wait_reply(self, sent, timeout):
        """Return (reply_dict, seconds) for the first bot message after `sent`."""
        start = time.monotonic()
        while time.monotonic() - start < timeout + 10:
            messages = self._get("/messages", roomId=self.room_id, max=10)["items"]
            for message in messages:
                if (
                    message["personId"] == self.bot_id
                    and message["created"] > sent["created"]
                ):
                    elapsed = time.monotonic() - start
                    try:
                        return json.loads(message.get("text", "")), elapsed
                    except ValueError:
                        return {"raw": message.get("text")}, elapsed
            time.sleep(1)
        return None, time.monotonic() - start


def request_yaml(router, method, action, name, ipv4=None, description=None,
                 admin_state=None, version="1"):
    lines = [
        f"version: {version}",
        f"router: {router}",
        f"method: {method}",
        f"action: {action}",
        "desired:",
        "  interface:",
        f"    name: {name}",
    ]
    if ipv4:
        lines += [
            f"    ipv4: {ipv4}",
            f"    description: {description}",
            f"    admin_state: {admin_state}",
        ]
    return "\n".join(lines) + "\n"


def subset(expected, actual):
    if not isinstance(actual, dict):
        return False
    return all(actual.get(key) == value for key, value in expected.items())


def validation_cases(router, name):
    def err(code):
        return {"status": "error", "result": code}

    return [
        ("mention without YAML", None, err("no_yaml")),
        ("invalid YAML", "version: 1\ndesired: [interface\n", err("invalid_yaml")),
        ("version as string", request_yaml(router, "restconf", "status", name,
                                           version='"1"'), err("invalid_version")),
        ("restconf + delete", request_yaml(router, "restconf", "delete", name),
         err("invalid_action")),
        ("ansible + status", request_yaml(router, "ansible", "status", name),
         err("invalid_action")),
        ("router not allowed", request_yaml("10.0.29.200", "restconf", "status",
                                            name), err("invalid_router")),
    ]


def router_cases(router, name, ipv4, description):
    full = dict(ipv4=ipv4, description=description, admin_state="up")
    down = dict(ipv4=ipv4, description=description, admin_state="down")
    interface = {"name": name, **full}
    not_found = {"status": "ok", "result": "not_found", "interface": None}
    found = {"status": "ok", "result": "found", "interface": interface}
    found_down = {"status": "ok", "result": "found",
                  "interface": {"name": name, **down}}
    applied = {"status": "ok", "result": "applied"}

    def plan(operation):
        return {"status": "ok", "result": "planned", "operation": operation}

    return [
        ("restconf status (absent)", request_yaml(router, "restconf", "status", name), not_found),
        ("restconf plan create", request_yaml(router, "restconf", "plan", name, **full), plan("create")),
        ("restconf apply", request_yaml(router, "restconf", "apply", name, **full), applied),
        ("restconf status (present)", request_yaml(router, "restconf", "status", name), found),
        ("restconf plan no_change", request_yaml(router, "restconf", "plan", name, **full),
         {**plan("no_change"), "changes": {}}),
        ("netconf status", request_yaml(router, "netconf", "status", name), found),
        ("netmiko status", request_yaml(router, "netmiko-textfsm", "status", name), found),
        ("netconf apply (down)", request_yaml(router, "netconf", "apply", name, **down), applied),
        ("netconf plan no_change", request_yaml(router, "netconf", "plan", name, **down),
         {**plan("no_change"), "changes": {}}),
        ("netmiko status (down)", request_yaml(router, "netmiko-textfsm", "status", name), found_down),
        ("ansible apply (up)", request_yaml(router, "ansible", "apply", name, **full), applied),
        ("restconf status (up again)", request_yaml(router, "restconf", "status", name), found),
        ("netmiko delete", request_yaml(router, "netmiko-textfsm", "delete", name),
         {"status": "ok", "result": "deleted"}),
        ("restconf status (deleted)", request_yaml(router, "restconf", "status", name), not_found),
        ("netmiko delete again", request_yaml(router, "netmiko-textfsm", "delete", name), not_found),
    ]


def run(tester, cases, limit):
    failures = 0
    for title, yaml_text, expected in cases:
        sent = tester.send(yaml_text)
        reply, elapsed = tester.wait_reply(sent, limit)
        ok = reply is not None and subset(expected, reply)
        slow = elapsed > limit
        mark = "PASS" if ok and not slow else "FAIL"
        failures += mark == "FAIL"
        note = " (too slow)" if ok and slow else ""
        print(f"{mark} {elapsed:5.1f}s  {title}{note}")
        if not ok:
            print(f"       expected {json.dumps(expected)}")
            print(f"       got      {json.dumps(reply)}")
    return failures


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--room", default="Testing Zone IPA2026-Y3-Final-Exam-project")
    parser.add_argument("--student-id", default="67070175")
    parser.add_argument("--router", help="run router cases on this router")
    parser.add_argument("--ipv4", default="172.31.175.1/32",
                        help="unused Loopback address on that router")
    args = parser.parse_args()

    token = os.environ.get("WEBEX_TESTER_TOKEN")
    if not token:
        sys.exit("set WEBEX_TESTER_TOKEN in .env (your own Personal Access Token)")

    name = f"Loopback{args.student_id}"
    description = f"IPA2026-{args.student_id}"
    tester = Tester(token, args.room, f"{args.student_id}@webex.bot")

    print("== validation cases (router not contacted)")
    failures = run(tester, validation_cases(args.router or "10.0.29.103", name),
                   LIMIT_NO_ROUTER)

    if args.router:
        if args.router == "10.0.29.101":
            sys.exit("10.0.29.101 is reserved for official grading")
        print(f"== router cases on {args.router} / {name} / {args.ipv4}")
        status_yaml = request_yaml(args.router, "restconf", "status", name)
        sent = tester.send(status_yaml)
        reply, _ = tester.wait_reply(sent, LIMIT_ROUTER)
        print(f"pre-check status: {json.dumps(reply)}")
        if not reply or reply.get("status") != "ok":
            sys.exit("pre-check failed; not touching the router")
        if reply.get("result") == "found":
            if reply["interface"].get("description") != description:
                sys.exit(f"{name} exists but is not ours; stopping")
            print(f"removing our leftover {name} first")
            tester.send(request_yaml(args.router, "netmiko-textfsm", "delete", name))
            time.sleep(LIMIT_ROUTER)
        try:
            failures += run(tester, router_cases(args.router, name, args.ipv4,
                                                 description), LIMIT_ROUTER)
        finally:
            # Never leave our test Loopback behind on the shared router.
            sent = tester.send(
                request_yaml(args.router, "netmiko-textfsm", "delete", name)
            )
            reply, _ = tester.wait_reply(sent, LIMIT_ROUTER)
            print(f"cleanup delete: {json.dumps(reply)}")

    print(f"== {'all passed' if not failures else f'{failures} failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
