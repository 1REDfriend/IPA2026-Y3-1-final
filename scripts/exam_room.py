"""
Talk to IPA2026-Reference in the exam room as the student, and check readiness.

    python scripts/exam_room.py preflight          # checks only, sends nothing
    python scripts/exam_room.py register           # dry run: shows the message
    python scripts/exam_room.py register --send    # really posts it
    python scripts/exam_room.py verify --send
    python scripts/exam_room.py grade --send       # uses 1 of 10 grade quota
    python scripts/exam_room.py score --send

Posts with WEBEX_TESTER_TOKEN (the student's own account). After sending it
follows the room: replies from IPA2026-Reference that concern STUDENT_ID,
grader requests that mention our bot, and our bot's answers.
"""

import argparse
import os
import re
import socket
import subprocess
import sys
import time

import requests

from student_env import ROOT, load_env, require

API = "https://webexapis.com/v1"

EXAM_ROOM = "IPA2026 Exam Room"
MANUAL_ROOM = "IPA2026"
REFERENCE_NAME = "IPA2026-Reference"
GRADING_ROUTER = "10.0.29.101"
ROUTER_PORTS = (22, 443, 830)

# How long to keep following the room after sending each command.
FOLLOW_SECONDS = {"register": 60, "score": 60, "verify": 180, "grade": 1800}
# The final grade report contains a line like "Live: 10/10".
GRADE_DONE = re.compile(r"^Live: \d+/10", re.MULTILINE)


class Webex:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, **params):
        response = self.session.get(API + path, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def room_id(self, title):
        for room in self.get("/rooms", type="group", max=200)["items"]:
            if room["title"] == title:
                return room["id"]
        return None

    def members(self, room_id):
        return self.get("/memberships", roomId=room_id, max=1000)["items"]


def repo_url():
    remote = subprocess.check_output(
        ["git", "-C", str(ROOT), "remote", "get-url", "origin"], text=True
    ).strip()
    return re.sub(r"\.git$", "", remote)


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label}{f' - {detail}' if detail else ''}")
    return ok


def preflight(student_id):
    """Run every readiness check; return True when all pass."""
    results = []
    bot = Webex(require("WEBEX_BOT_TOKEN"))
    tester = Webex(require("WEBEX_TESTER_TOKEN"))
    bot_email = f"{student_id}@webex.bot"

    me = tester.get("/people/me")
    results.append(check("tester token", True, me.get("displayName")))
    bot_me = bot.get("/people/me")
    results.append(check(
        "bot display name is the student ID",
        bot_me.get("displayName") == student_id, bot_me.get("displayName"),
    ))

    for title in (MANUAL_ROOM, EXAM_ROOM):
        room_id = tester.room_id(title)
        member = bool(room_id) and any(
            m.get("personEmail") == bot_email for m in tester.members(room_id)
        )
        results.append(check(f"bot is a member of {title!r}", member))

    hooks = [w for w in bot.get("/webhooks")["items"] if w.get("status") == "active"]
    results.append(check("active Webex webhook", bool(hooks),
                         hooks[0]["targetUrl"] if hooks else "none"))

    port = os.environ.get("HOST_PORT", "28475")
    try:
        local = requests.get(f"http://127.0.0.1:{port}/health", timeout=5).ok
    except requests.RequestException:
        local = False
    results.append(check("local /health", local))

    if hooks:
        public = hooks[0]["targetUrl"].rsplit("/webhook", 1)[0] + "/health"
        try:
            remote = requests.get(public, timeout=10).ok
        except requests.RequestException:
            remote = False
        results.append(check("public /health through the tunnel", remote))

    head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    subprocess.run(["git", "-C", str(ROOT), "fetch", "-q", "origin"], check=False)
    remote_head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "origin/main"], text=True
    ).strip()
    results.append(check("local main is pushed", head == remote_head, head[:12]))
    try:
        ci = subprocess.check_output(
            ["gh", "run", "list", "--workflow", "student-ci.yaml",
             "--commit", remote_head, "--json", "conclusion",
             "-q", ".[0].conclusion"],
            text=True, cwd=ROOT,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        ci = "unknown"
    results.append(check("Student CI on main", ci == "success", ci or "not run"))

    for router_port in ROUTER_PORTS:
        try:
            socket.create_connection((GRADING_ROUTER, router_port), timeout=4).close()
            reachable = True
        except OSError:
            reachable = False
        results.append(check(
            f"{GRADING_ROUTER}:{router_port} reachable (VPN)", reachable
        ))

    return all(results)


def follow(webex, room_id, sent, me_id, student_id, bot_id, reference_id, command):
    """Print relevant room messages until the command looks finished."""
    seen = set()
    deadline = time.monotonic() + FOLLOW_SECONDS[command]
    last_activity = time.monotonic()
    got_reference_reply = False

    while time.monotonic() < deadline:
        items = webex.get("/messages", roomId=room_id, max=50)["items"]
        for message in reversed(items):
            if message["id"] in seen or message["created"] <= sent["created"]:
                continue
            seen.add(message["id"])
            text = message.get("text") or ""
            author = message["personId"]
            stamp = message["created"][11:19]

            if author == reference_id and bot_id in (message.get("mentionedPeople") or []):
                files = " + YAML" if message.get("files") else ""
                print(f"[{stamp}] grader -> bot{files}")
            elif author == reference_id and (
                student_id in text
                or me_id in (message.get("mentionedPeople") or [])
                or message.get("parentId") == sent["id"]
            ):
                print(f"[{stamp}] {REFERENCE_NAME}:\n{text}\n")
                got_reference_reply = True
                if command == "grade" and GRADE_DONE.search(text):
                    return
            elif author == bot_id:
                print(f"[{stamp}] bot: {text}")
            else:
                continue
            last_activity = time.monotonic()

        # Short commands are done once the reply has arrived and the room
        # has been quiet for a while (verify also waits for the bot test).
        quiet = time.monotonic() - last_activity
        if command != "grade" and got_reference_reply and quiet > 25:
            return
        time.sleep(3)
    print(f"(stopped following after {FOLLOW_SECONDS[command]} s)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_env()

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("command",
                        choices=("preflight", "register", "verify", "grade", "score"))
    parser.add_argument("--send", action="store_true",
                        help="really post the message (default is a dry run)")
    args = parser.parse_args()

    student_id = require("STUDENT_ID")

    if args.command == "preflight":
        sys.exit(0 if preflight(student_id) else 1)

    tester = Webex(require("WEBEX_TESTER_TOKEN"))
    room_id = tester.room_id(EXAM_ROOM)
    if not room_id:
        sys.exit(f"the tester is not in {EXAM_ROOM!r}")
    members = tester.members(room_id)
    reference = next(
        (m for m in members if m.get("personDisplayName") == REFERENCE_NAME), None
    )
    if reference is None:
        sys.exit(f"{REFERENCE_NAME} not found in {EXAM_ROOM!r}")
    bot = next(
        (m for m in members if m.get("personEmail") == f"{student_id}@webex.bot"),
        None,
    )

    text = args.command
    if args.command == "register":
        text = f"register {repo_url()}"
    markdown = f"<@personEmail:{reference['personEmail']}|{REFERENCE_NAME}> {text}"

    if not args.send:
        print(f"dry run - would post to {EXAM_ROOM!r}:\n  @{REFERENCE_NAME} {text}")
        print("add --send to post it")
        return

    if args.command in ("verify", "grade"):
        print("== preflight")
        if not preflight(student_id):
            sys.exit("preflight failed; not sending")
    if bot is None and args.command != "register":
        sys.exit(f"bot {student_id} is not in {EXAM_ROOM!r} yet")

    response = tester.session.post(
        API + "/messages",
        data={"roomId": room_id, "markdown": markdown},
        timeout=15,
    )
    response.raise_for_status()
    sent = response.json()
    print(f"[{sent['created'][11:19]}] sent: @{REFERENCE_NAME} {text}")

    me_id = tester.get("/people/me")["id"]
    follow(tester, room_id, sent, me_id, student_id,
           bot["personId"] if bot else None, reference["personId"], args.command)


if __name__ == "__main__":
    main()
