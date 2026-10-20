"""Part 4 student implementation."""

import logging

from app.core import error, load_request_file, validate_request
from app.dispatcher import dispatch_request

from app.request_handler import validate_webex_envelope

logger = logging.getLogger(__name__)


def process_request(mentioned_people, attachment_path, bot_person_id):
    envelope_error = validate_webex_envelope(
        mentioned_people,
        attachment_path,
        bot_person_id,
    )
    if envelope_error is not None:
        return envelope_error

    data, load_error = load_request_file(attachment_path)
    if load_error is not None:
        return load_error

    validation = validate_request(data)
    if validation["result"] != "accepted":
        return validation

    try:
        return dispatch_request(data)
    except Exception:
        # Backends map their own failures; this only guards the bot
        # against an unexpected bug so it still answers the room.
        logger.exception("dispatch failed")
        return error("backend_failed")
