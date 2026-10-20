"""Keep the bot's Webex webhook pointed at the current public URL."""

import logging
import os
import time
from threading import Thread

import requests

logger = logging.getLogger("ipa2026.registration")

WEBHOOK_NAME = "ipa2026-bot"
POLL_SECONDS = 30
STARTUP_POLL_SECONDS = 3


def register(client, public_url, secret=None):
    """
    Make exactly one active webhook named WEBHOOK_NAME target
    <public_url>/webhook, removing stale registrations.
    """
    target_url = public_url.rstrip("/") + "/webhook"
    keep = None

    for webhook in client.list_webhooks():
        if webhook.get("name") != WEBHOOK_NAME:
            continue
        if (
            keep is None
            and webhook.get("targetUrl") == target_url
            and webhook.get("status") == "active"
            and not secret
        ):
            keep = webhook
            continue
        client.delete_webhook(webhook["id"])

    if keep is None:
        client.create_webhook(WEBHOOK_NAME, target_url, secret)
        logger.info("registered Webex webhook -> %s", target_url)
    else:
        logger.info("Webex webhook already active -> %s", target_url)


def _quick_tunnel_url(metrics_url):
    """Read the trycloudflare hostname from cloudflared's metrics server."""
    response = requests.get(metrics_url.rstrip("/") + "/quicktunnel", timeout=5)
    response.raise_for_status()
    hostname = response.json().get("hostname")
    return f"https://{hostname}" if hostname else None


def _watch_quick_tunnel(client, metrics_url, secret):
    current = None
    while True:
        try:
            url = _quick_tunnel_url(metrics_url)
            if url and url != current:
                register(client, url, secret)
                current = url
        except Exception as exc:
            logger.info("waiting for tunnel URL: %s", type(exc).__name__)
        # Retry quickly until the first registration, then just watch.
        time.sleep(POLL_SECONDS if current else STARTUP_POLL_SECONDS)


def start_registration(client, secret=None):
    """
    PUBLIC_URL: register a fixed public URL once.
    TUNNEL_METRICS_URL: follow a Cloudflare Quick Tunnel and re-register
    whenever its URL changes (e.g. after the tunnel restarts).
    """
    public_url = os.environ.get("PUBLIC_URL")
    metrics_url = os.environ.get("TUNNEL_METRICS_URL")

    if public_url:
        try:
            register(client, public_url, secret)
        except Exception:
            logger.exception("webhook registration failed")
    elif metrics_url:
        Thread(
            target=_watch_quick_tunnel,
            args=(client, metrics_url, secret),
            daemon=True,
        ).start()
    else:
        logger.info("no PUBLIC_URL or TUNNEL_METRICS_URL; skip registration")
