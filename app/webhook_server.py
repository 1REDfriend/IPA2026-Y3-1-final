"""Part 4 student implementation."""

import hashlib

import hmac

import json

import logging

import os

import time

from collections import OrderedDict

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from tempfile import TemporaryDirectory

from threading import Lock

from app.integration import process_request

from app.webex_client import WEBEX_API_BASE, WebexClient

logger = logging.getLogger("ipa2026.webhook")

MAX_BODY_BYTES = 1_000_000
RECENT_MESSAGE_LIMIT = 500
BOT_LOOKUP_RETRY_SECONDS = 5


def _error(code):
    return {"status": "error", "result": code}


class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def handle_event(self, event):
        if not isinstance(event, dict):
            return None
        if event.get("resource") != "messages" or event.get("event") != "created":
            return None
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        message_id = data.get("id")
        if not isinstance(message_id, str) or not message_id:
            return None

        # Skip our own replies before any API call to avoid reply loops.
        if data.get("personId") == self.bot_person_id:
            return None

        message = self.client.get_message(message_id)
        if message.get("personId") == self.bot_person_id:
            return None
        room_id = message.get("roomId")
        if not room_id:
            return None

        result = self._process(message)
        self.client.send_message(room_id, json.dumps(result))
        return result

    def _process(self, message):
        mentioned_people = message.get("mentionedPeople") or []
        files = message.get("files") or []

        if len(files) > 1:
            return _error("multiple_attachments")

        if not files:
            return self._run(mentioned_people, None)

        content = self.client.download_file(files[0])
        with TemporaryDirectory(prefix="ipa2026-") as directory:
            path = Path(directory) / "request.yaml"
            path.write_bytes(content)
            return self._run(mentioned_people, path)

    def _run(self, mentioned_people, path):
        try:
            return self.processor(mentioned_people, path, self.bot_person_id)
        except Exception:
            logger.exception("request processing failed")
            return _error("backend_failed")


def _valid_signature(secret, body, signature):
    expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def make_http_handler(submit_event, secret=None):
    class WebhookHTTPHandler(BaseHTTPRequestHandler):
        server_version = "IPA2026Webhook/1"

        def _reply(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/health":
                self._reply(200, {"status": "ok", "result": "healthy"})
            else:
                self._reply(404, _error("not_found"))

        def do_POST(self):
            if self.path != "/webhook":
                self._reply(404, _error("not_found"))
                return

            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if not 1 <= length <= MAX_BODY_BYTES:
                self._reply(400, _error("invalid_event"))
                return

            body = self.rfile.read(length)

            if secret and not _valid_signature(
                secret, body, self.headers.get("X-Spark-Signature")
            ):
                self._reply(403, _error("invalid_signature"))
                return

            try:
                event = json.loads(body)
            except (UnicodeDecodeError, ValueError):
                event = None
            if not isinstance(event, dict):
                self._reply(400, _error("invalid_event"))
                return

            # Acknowledge immediately; processing happens in the background.
            submit_event(event)
            self._reply(200, {"status": "ok", "result": "accepted"})

        def log_message(self, format, *args):
            logger.debug("%s - %s", self.address_string(), format % args)

    return WebhookHTTPHandler


class SequentialSubmitter:
    """
    Run events one at a time so router changes never overlap, and drop
    re-deliveries of a message that was already queued.
    """

    def __init__(self, handler):
        self._handler = handler
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._recent = OrderedDict()
        self._lock = Lock()

    def __call__(self, event):
        data = event.get("data")
        message_id = data.get("id") if isinstance(data, dict) else None
        if message_id:
            with self._lock:
                if message_id in self._recent:
                    logger.info("skip duplicate delivery of %s", message_id)
                    return
                self._recent[message_id] = True
                if len(self._recent) > RECENT_MESSAGE_LIMIT:
                    self._recent.popitem(last=False)
        self._executor.submit(self._safe_handle, event)

    def _safe_handle(self, event):
        try:
            result = self._handler.handle_event(event)
            if result is not None:
                logger.info("replied %s", json.dumps(result))
        except Exception:
            logger.exception("event handling failed")


def _resolve_bot_person_id(client):
    while True:
        try:
            me = client.get_me()
            logger.info("bot %s (%s) ready", me.get("displayName"), me["id"])
            return me["id"]
        except Exception as exc:
            logger.warning(
                "cannot read bot identity from %s/people/me: %s",
                WEBEX_API_BASE,
                exc,
            )
            time.sleep(BOT_LOOKUP_RETRY_SECONDS)


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8000"))
    secret = os.environ.get("WEBEX_WEBHOOK_SECRET") or None

    client = WebexClient()
    bot_person_id = _resolve_bot_person_id(client)
    submit = SequentialSubmitter(WebexEventHandler(client, bot_person_id))

    from app.webhook_registration import start_registration

    start_registration(client, secret)

    server = ThreadingHTTPServer((host, port), make_http_handler(submit, secret))
    logger.info("listening on %s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
