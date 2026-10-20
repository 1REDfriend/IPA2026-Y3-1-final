# Running the bot

## Ports

| What | Where | Port |
|---|---|---|
| Webhook server, inside the container | `webhook` service | 8000 (spec default) |
| Webhook server, on the host (loopback only) | `http://127.0.0.1:28475/health` | **28475** (`HOST_PORT`) |
| cloudflared metrics / Quick Tunnel URL (Compose network only) | `http://tunnel:41983/quicktunnel` | 41983 |

## Start

1. `cp .env.example .env` and fill in `WEBEX_BOT_TOKEN`, `ROUTER_USER`, `ROUTER_PASS`.
2. `docker compose up -d --build` starts `webhook` and `tunnel`.
3. `docker compose logs -f webhook` should show
   `registered Webex webhook -> https://<random>.trycloudflare.com/webhook`.

The webhook service reads the Quick Tunnel URL from cloudflared and
re-registers the Webex webhook (`mentionedPeople=me`, all rooms the bot is in)
whenever it changes. After restarting the tunnel, `docker compose restart
tunnel` is enough; set `PUBLIC_URL` instead to use a fixed HTTPS URL.

The bot must be a member of **IPA2026** and **IPA2026 Exam Room**; it replies
to whichever room sent the request.

## Check

```bash
python -m pytest -q tests
docker compose build webhook
python scripts/check_webhook_image.py
python scripts/live_test.py           # Webex validation cases
python scripts/live_test.py --router  # + router sequence on TEST_ROUTER
python scripts/make_manual_yaml.py    # ready-to-send YAML in manual-yaml/
```

The student ID, test router, Loopback IPv4 and test room are read from `.env`
(`STUDENT_ID`, `TEST_ROUTER`, `TEST_LOOPBACK_IPV4`, `TEST_ROOM`); nothing
student-specific is hard-coded in the scripts.

`scripts/live_test.py` posts as your own account (`WEBEX_TESTER_TOKEN`) in the
test room. Router cases only touch `Loopback<student-id>`, refuse
`10.0.29.101`, stop if that Loopback belongs to someone else, and always
delete it again at the end.

## Router safety

- Requests are processed one at a time; Webex re-deliveries are ignored.
- Ansible apply and Netmiko delete only accept `Loopback<number>`; names and
  descriptions that could inject IOS CLI are rejected.
- Netmiko leaves config mode after each change; every SSH/NETCONF session is
  closed, also on errors. Nothing saves the configuration (`write memory`).
