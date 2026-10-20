"""
Fill the instructor's manual Webex templates with values from .env.

    python scripts/make_manual_yaml.py

Reads STUDENT_ID, TEST_ROUTER and TEST_LOOPBACK_IPV4 and writes ready-to-send
files to manual-yaml/ (git-ignored), one file per Webex message.
"""

import sys
from ipaddress import IPv4Interface, ip_network

from student_env import ROOT, student_settings

TEMPLATES = ROOT / "sample-tests" / "webex-manual"
OUTPUT = ROOT / "manual-yaml"

# Reserved for official Live requests.
LIVE_RESERVED = ip_network("192.0.2.128/27")


def main():
    student_id, router, ipv4 = student_settings()

    interface = IPv4Interface(ipv4)
    if interface.network.prefixlen != 32:
        sys.exit("TEST_LOOPBACK_IPV4 must be a /32 address")
    if interface.ip in LIVE_RESERVED:
        sys.exit(f"{LIVE_RESERVED} is reserved for official Live tests")

    OUTPUT.mkdir(exist_ok=True)
    for template in sorted(TEMPLATES.glob("*.yaml")):
        text = (
            template.read_text(encoding="utf-8")
            .replace("<assigned-router-ip>", router)
            .replace("<student-id>", student_id)
            # Templates write "<unused-ipv4>/32".
            .replace("<unused-ipv4>/32", str(interface))
        )
        (OUTPUT / template.name).write_text(text, encoding="utf-8")
        print(f"wrote {OUTPUT.name}/{template.name}")


if __name__ == "__main__":
    main()
