"""Part 4 student implementation."""

import os
from urllib.parse import urlparse

import requests

WEBEX_API_BASE = 'https://webexapis.com/v1'

REQUEST_TIMEOUT = 10

# The bot token is only ever sent to Webex itself.
WEBEX_HOST_SUFFIX = "webexapis.com"


def _is_webex_url(url):
    host = urlparse(url).hostname or ""
    return host == WEBEX_HOST_SUFFIX or host.endswith("." + WEBEX_HOST_SUFFIX)


class WebexClient:
    def __init__(self, token=None, session=None):
        token = token or os.environ.get("WEBEX_BOT_TOKEN")
        if not token:
            raise PermissionError("WEBEX_BOT_TOKEN is not set")
        self._token = token
        self._session = session or requests.Session()

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, url, headers=None):
        response = self._session.get(
            url,
            headers=self.headers if headers is None else headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response

    def _post(self, url, payload):
        response = self._session.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def get_message(self, message_id):
        return self._get(f"{WEBEX_API_BASE}/messages/{message_id}").json()

    def download_file(self, file_url):
        headers = self.headers if _is_webex_url(file_url) else {}
        return self._get(file_url, headers=headers).content

    def send_message(self, room_id, text):
        return self._post(
            f"{WEBEX_API_BASE}/messages",
            {"roomId": room_id, "text": text},
        )

    def get_me(self):
        """Return the bot's own person record (its id is the personId)."""
        return self._get(f"{WEBEX_API_BASE}/people/me").json()

    def list_webhooks(self):
        return self._get(f"{WEBEX_API_BASE}/webhooks").json().get("items", [])

    def create_webhook(self, name, target_url, secret=None):
        payload = {
            "name": name,
            "targetUrl": target_url,
            "resource": "messages",
            "event": "created",
            # Deliver only messages that mention the bot, in every room
            # the bot belongs to (IPA2026, the exam room, test rooms).
            "filter": "mentionedPeople=me",
        }
        if secret:
            payload["secret"] = secret
        return self._post(f"{WEBEX_API_BASE}/webhooks", payload)

    def delete_webhook(self, webhook_id):
        response = self._session.delete(
            f"{WEBEX_API_BASE}/webhooks/{webhook_id}",
            headers=self.headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
