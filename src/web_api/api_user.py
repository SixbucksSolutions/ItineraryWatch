import functools
import json
import logging
import time
import typing
import uuid

import aws_lambda_powertools.utilities.typing
import aws_lambda_powertools.utilities.parser
import aws_lambda_powertools.utilities.parser.models
import boto3
import psycopg

from . import auth

# Root powertools package gets imported by submodules, doesn't need explicit import
_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="api")
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

                    # Get the user's info from the DB
                    start_time: float = time.perf_counter()
                    cur.execute(
                        """
                        SELECT      email
                        FROM        users
                        WHERE       user_id = %s;
                        """,

                        (authenticated_user_id, )
                    )
                    end_time: float = time.perf_counter()
                    _logger.debug( "DB query for full user info based on user ID completed in "
                                  f"{end_time - start_time:.03f} seconds" )

                    user_info_row: tuple = cur.fetchone()

    except Exception as e:
        _logger.critical(f"Database error: {e}")
        raise

    authenticated_user_info: dict[str, str] = {
        "email_address" : user_info_row[0],
    }

    return {
        "statusCode"    : 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body"          : json.dumps(authenticated_user_info, default=str),
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
