import json
import logging
import time
import typing
import uuid

import aws_lambda_powertools.utilities.parser.models


_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="auth")
_logger.setLevel(level=logging.INFO)



def authenticated_user(
        event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
        db_cursor
) -> uuid.UUID | None:

    # Access cookies directly via the built-in model property
    # Lambda powertools automatically extract cookies into a clean list of strings
    incoming_cookies = event.cookies or []

    # Find the target cookie string or default to None
    target_cookie: str| None = next((c for c in incoming_cookies if c.startswith("__Host-user_id=")), None)

    # None means header did not get passed
    if not target_cookie:
        return None

    try:
        raw_uuid: str = target_cookie.split("__Host-user_id=")[1]
        user_id: uuid.UUID = uuid.UUID(raw_uuid)

        if user_id.version != 7:
            _logger.warning(f"API call included user_id but it was a v{user_id.version} UUID instead of v7")
            return None

    except (ValueError, IndexError) as e:
        _logger.warning(f"API call included user_id header but it was not a UUID: {e}")
        return None

    # Now see if the DB has a user with that ID
    start_time: float = time.perf_counter()
    db_cursor.execute(
        """
        SELECT EXISTS(SELECT 1 FROM users WHERE user_id = %s);
        """,

        (user_id, )
    )
    end_time: float = time.perf_counter()
    _logger.debug(f"DB query for user_id {user_id} took {end_time - start_time:.03f} seconds")
    exists: bool = db_cursor.fetchone()[0]

    if not exists:
        _logger.warning(f"Got a user ID via cookie that was not found in DB: {str(user_id)} - !?!?!?!?!?!?")
        return None

    _logger.info(f"Successfully authenticated user w/ ID {str(user_id)} via \"__Host-user_id\" cookie")
    return user_id


def lambda_response_auth_failed() -> dict[str, typing.Any]:
    return {
        "statusCode"    : 401,
        "headers"       : {
            "Content-Type"      : "application/json",
            "WWW-Authenticate"  : "Cookie realm=\"://api.itinerarywatch.com\""
        },
        "body"          : json.dumps(
            {
                "error"         : "Unauthorized",
                "message"       : "Auth failed; secure session context is missing or invalid"
            }
        ),
    }
