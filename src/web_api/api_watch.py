import datetime
import functools
import json
import logging
import time
import typing
import uuid
from ctypes import cast

import aws_lambda_powertools.utilities.typing
import aws_lambda_powertools.utilities.parser
import aws_lambda_powertools.utilities.parser.models
import boto3
import psycopg

from . import auth

# Root powertools package gets imported by submodules, doesn't need explicit import
_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="api.watch")
_logger.setLevel(level=logging.INFO)

_ssm_client = boto3.client("ssm", region_name="us-east-2")


def avoid_warmup_errors(handler):
    @functools.wraps(handler)
    def wrapper(event, context, *args, **kwargs):
        # Intercept the warmer payload before Pydantic parses it
        if isinstance(event, dict) and event.get("source") == "serverless-plugin-warmup":
            _logger.debug("WarmUp: Intercepted ping before Pydantic parser, exiting early")
            return{
                "statusCode"    : 200,
                "body"          : "",
            }

        return handler(event, context, *args, **kwargs)
    return wrapper


@_logger.inject_lambda_context(log_event=True)  # Log all function invocations, even warmup
@avoid_warmup_errors                            # This docorator executes BEFORE the parser middleware
@aws_lambda_powertools.utilities.parser.event_parser(
        model=aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model)
def lambda_handler_apigw(event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
                         _context: aws_lambda_powertools.utilities.typing.LambdaContext) -> dict[str, typing.Any]:

    if not event.pathParameters or "user_search_id" not in event.pathParameters:
        _logger.error("Endpoint got invoked without user_search_id path parameter")
        return {
            "statusCode"    : 400,
            "headers"       : {
                "Content-Type"  : "application/json"
            },
            "body"          : json.dumps(
                {
                    "error"         : "Invoked without user_search_id path parameter"
                }
            ),
        }

    user_search_id: uuid.UUID = uuid.UUID(event.pathParameters["user_search_id"])

    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()

    try:
        # Context manager syntax ("with") gets the connection auto-closed at scope exit, commits if no errors
        #       during connection
        with psycopg.connect(
                host=postgres_connection_params["db_hostname"],
                dbname=postgres_connection_params["db_dbname"],
                user=postgres_connection_params["db_user"],
                password=postgres_connection_params["db_password"],
                sslmode="verify-full",
                sslrootcert="src/aws-rds-global-bundle.pem",
        ) as conn:

            # Chaining multiple queries, so we need a transaction
            with conn.transaction():

                # Context managers for cursors ensure they *also* close automatically
                with conn.cursor() as cur:

                    authenticated_user_id: uuid.UUID | None = auth.authenticated_user(event, cur)

                    if authenticated_user_id is None:
                        return auth.lambda_response_auth_failed()

                    _logger.debug(f"Auth user ID: {str(authenticated_user_id)}")

                    # Get the user's info from the DB
                    start_time: float = time.perf_counter()

                    # Intentionally not wasting DB CPU sorting; that's compute the browser's JS will do
                    cur.execute(
                        """
                        SELECT      search_name, 
                                    monitored_urls.url,
                                    monitored_urls.contents_changed_timestamp,
                                    monitored_urls.last_scrape_timestamp
                        FROM        user_searches
                        JOIN        monitored_urls ON user_searches.watched_url = monitored_urls.url_id 
                        WHERE       user_searches.user_id = %s
                                    AND
                                    user_searches.user_search_id = %s;
                        """,

                        (authenticated_user_id, user_search_id)
                    )
                    end_time: float = time.perf_counter()
                    _logger.debug( "DB query for user's watched searches completed in "
                                  f"{end_time - start_time:.03f} seconds" )

                    watch_tuple: tuple | None = cur.fetchone()
    except Exception as e:
        _logger.critical(f"Database error: {e}")
        raise

    watch_details: dict = {}

    if watch_tuple:
        watch_last_update_str: str = _get_timestamp_from_uuid7(user_search_id).isoformat(sep=" ", timespec="seconds")
        change_timestamp: str
        if watch_tuple[2] is not None:
            change_timestamp = watch_tuple[2].isoformat(sep=" ", timespec="seconds")
        else:
            change_timestamp = watch_last_update_str
        last_check_timestamp: str
        if watch_tuple[3] is not None:
            last_check_timestamp = watch_tuple[3].isoformat(sep=" ", timespec="seconds")
        else:
            last_check_timestamp = watch_last_update_str

        watch_details = {
            "watch_last_updated_timestamp"      : watch_last_update_str,
            "watch_name"                        : watch_tuple[0],
            "url"                               : watch_tuple[1],
            "search_contents_changed_timestamp" : change_timestamp,
            "search_last_checked_timestamp"     : last_check_timestamp,

            # TODO: Get this from S3 along with a bunch of other data
            # "matching_sailings_found"           : None,
        }
        _logger.info(f"Returning details for user watch {str(user_search_id)}")

    else:
        _logger.warning(f"Caller requested details for non-existent user watch {str(user_search_id)}")

    return {
        "statusCode"    : 200,
        "headers"       : {
            "Content-Type"  : "application/json"
        },
        "body"          : json.dumps(watch_details, default=str),
    }


def _get_pg_server_connection_details() -> dict[str, str]:
    db_params_keys: list[str] = [
        "/itinerary_watch/postgres/db_hostname",
        "/itinerary_watch/postgres/db_dbname",
        "/itinerary_watch/postgres/db_user",
        "/itinerary_watch/postgres/db_password",
    ]

    returned_params: dict[str, str] = _read_parameter_store_params(db_params_keys)

    return_dict: dict[str, str] = {}
    for curr_key in db_params_keys:
        # shorten to final token
        return_dict[curr_key.split("/")[-1]] = returned_params[curr_key]

    return return_dict


def _read_parameter_store_params(parameter_names: list[str]) -> dict[str, str]:
    retrieved_params: list[dict] = _ssm_client.get_parameters(Names=parameter_names)['Parameters']
    # _logger.debug(f"Retrieved params: {retrieved_params}")
    return_dict: dict[str, str] = {}
    for param_idx, param_details in enumerate(retrieved_params):
        return_dict[param_details['Name']] = retrieved_params[param_idx]['Value']
    return return_dict


def _get_timestamp_from_uuid7(target_uuid: uuid.UUID) -> datetime.datetime:
    # 1. Access the raw 128-bit integer value of the UUID
    uuid_int: int = target_uuid.int

    # 2. Bit-shift 80 bits to the right to isolate the leading 48-bit timestamp
    timestamp_ms: int = uuid_int >> 80

    # 3. Convert millisecond integer count down to a fractional second float
    timestamp_seconds: float = timestamp_ms / 1000.0

    # 4. Construct a timezone-aware datetime instance using UTC baseline
    extracted_timestamp: datetime.datetime = datetime.datetime.fromtimestamp(timestamp_seconds,
                                                                             tz=datetime.timezone.utc)

    # 5. Extract and return the localized calendar date component
    return extracted_timestamp
