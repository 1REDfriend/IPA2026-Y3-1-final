"""Read per-student test settings from .env (never hard-coded in the repo)."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Reserved for official Live grading; never used for self-tests.
GRADING_ROUTER = "10.0.29.101"


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def require(key):
    value = os.environ.get(key, "").strip()
    if not value:
        sys.exit(f"set {key} in .env (see .env.example)")
    return value


def student_settings():
    """Return (student_id, router, loopback_ipv4) for self-tests."""
    load_env()
    student_id = require("STUDENT_ID")
    if not (student_id.isdigit() and len(student_id) == 8):
        sys.exit("STUDENT_ID must be the 8-digit student ID")
    router = require("TEST_ROUTER")
    if router == GRADING_ROUTER:
        sys.exit(f"{GRADING_ROUTER} is reserved for official grading")
    return student_id, router, require("TEST_LOOPBACK_IPV4")
