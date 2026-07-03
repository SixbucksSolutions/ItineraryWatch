import logging
import typing
import uuid

import aws_lambda_powertools.utilities.parser.models


_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="auth")
_logger.setLevel(level=logging.INFO)


def authenticated_user(
        event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model
) -> dict[str, typing.Any] | None:

    # Access cookies directly via the built-in model property
    # Lambda powertools automatically extract cookies into a clean list of strings
    incoming_cookies = event.cookies or []

    # Find the target cookie string or default to None
    target_cookie: str| None = next((c for c in incoming_cookies if c.startswith("__Host-user_id=")), None)

    # None means header did not get passed
    if not target_cookie:
        return None

    try:
        raw_uuid = target_cookie.split("__Host-user_id=")[1]
        user_id = uuid.UUID(raw_uuid)

        if user_id.version != 7:
            _logger.warning(f"API call included user_id but it was a v{user_id.version} UUID instead of v7")
            return None

    except (ValueError, IndexError) as e:
        _logger.warning(f"API call included user_id header but it was not a UUID: {e}")
        return None

    return {
        "user_id"       : user_id,
        "email_address" : "booya@gramma.com",
    }