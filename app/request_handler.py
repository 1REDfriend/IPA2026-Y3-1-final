from app.core import error, process_request_file


def validate_webex_envelope(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the target bot's actual mention and YAML attachment.
    Return an error response, or None when the envelope is valid.
    """
    if (
        not isinstance(bot_person_id, str)
        or not bot_person_id
        or not isinstance(mentioned_people, list)
        or bot_person_id not in mentioned_people
    ):
        return error("missing_bot_mention")

    if attachment_path is None:
        return error("no_yaml")

    return None


def handle_webex_request(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the envelope, then validate the attached YAML request.
    Return a response dictionary. Do not dispatch to a router.
    """
    envelope_error = validate_webex_envelope(
        mentioned_people,
        attachment_path,
        bot_person_id,
    )
    if envelope_error is not None:
        return envelope_error

    return process_request_file(attachment_path)
