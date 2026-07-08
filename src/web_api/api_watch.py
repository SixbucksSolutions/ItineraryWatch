import datetime
import functools
import json
import logging
import math
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
_logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="api.watch")
_logger.setLevel(level=logging.DEBUG)

_ssm_client = boto3.client("ssm",   region_name="us-east-2")
_s3_client = boto3.client("s3",     region_name="us-east-2")


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

    validation_response: dict[str, typing.Any] | uuid.UUID = _event_validation(event)

    if isinstance(validation_response, dict):
        return validation_response

    user_search_id: uuid.UUID = validation_response

    _logger.info(f"Caller passed valid UUIDv7 {str(user_search_id)}")

    db_response: dict | None = _do_db_query(event, user_search_id)

    if db_response is None:
        return {
            "statusCode"    : 404,
            "headers"       : {
                "Content-Type"  : "application/json"
            },
            "body"          : json.dumps(
                {
                    "error"         : f"search ID {user_search_id} not found or not associated with user",
                }
            ),
        }

    # Was the response an error?
    keys_to_check = ["statusCode", "headers", "body"]

    # Check if all keys exist -- if so, user failed to auth
    if all(key in db_response for key in keys_to_check):
        return db_response

    # Make sure they qualified they only want *latest* search result from the set
    #       of search results
    if not event.queryStringParameters                                      or \
            "search_result_timestamp" not in event.queryStringParameters    or \
            event.queryStringParameters["search_result_timestamp"] != "latest":
        return {
            "statusCode": 422,      # 422: "Unprocessable entity" meaning "I understand what you asked for,
                                    #           but I cannot fulfill it"
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(
                {
                    "error": "Callers must include search_result_timestamp=latest query parameter to be valid"
                }
            ),
        }

    if event.queryStringParameters:
        _logger.debug("Caller included query string parameters")

        supported_query_string_param_keys = {
            "search_result_timestamp",
        }

        # Make sure all query string parameters are supported values -- if any
        if not all(
                    query_string_param_key in supported_query_string_param_keys for query_string_param_key
                    in event.queryStringParameters
                ):
            return {
                "statusCode": 422,
                "headers": {
                    "Content-Type": "application/json"
                },
                "body": f"Unsupported query string parameter(s) in: {json.dumps(event.queryStringParameters)}",
            }

        if "search_result_timestamp" in event.queryStringParameters:
            requested_timestamp: str = event.queryStringParameters["search_result_timestamp"]
            if requested_timestamp != "latest":
                return {
                    "statusCode": 422,
                    "headers": {
                        "Content-Type": "application/json"
                    },
                    "body": f"Unsupported search result timestamp: {requested_timestamp}",
                }

            _logger.info( "Caller requested search result timestamp: "
                         f"{event.queryStringParameters["search_result_timestamp"]}")

    url_id: uuid.UUID = db_response["url_id"]

    # Remove that key from the db response, not going to expose it outside API
    del db_response["url_id"]

    api_response: dict[str, typing.Any] = {
        "summary": db_response,
    }

    sailings_data: tuple[datetime.datetime, list[dict[str, typing.Any]]] | None = _get_s3_data(url_id)

    if not sailings_data:
        api_response["search_result_sets"] = sailings_data
    else:
        api_response["search_result_sets"] = {
            sailings_data[0].isoformat(sep=" ", timespec="minutes"): sailings_data[1],
        }

    _logger.debug("Returning response")
    _logger.debug(json.dumps(api_response, indent=4))

    seconds_data_can_be_cached_in_browser: int
    if db_response["search_last_run_timestamp"] is None:
        # If we've never run the search, assume we're gonna scrape it real soon now
        seconds_data_can_be_cached_in_browser = 60
    else:
        # We can cache until the minute we're going to run the next data retrieve
        next_scrape_time: datetime.datetime = datetime.datetime.fromisoformat(
            db_response["search_last_run_timestamp"]) + datetime.timedelta(hours=24)
        time_difference_seconds: int = math.floor(
            (next_scrape_time - datetime.datetime.now(tz=datetime.timezone.utc)).total_seconds())

        # If result is positive, next scrape time is in the future
        if time_difference_seconds > 0:
            seconds_data_can_be_cached_in_browser = time_difference_seconds
        else:
            seconds_data_can_be_cached_in_browser = 60

    return {
        "statusCode"    : 200,
        "headers"       : {
            "Content-Type"  : "application/json",

            # *Aggressively* encourage browser to cache this response until next time data will be scraped
            "Cache-Control" : f"private, max-age={seconds_data_can_be_cached_in_browser}, immutable",
        },
        "body"          : json.dumps(api_response),
    }


def _do_db_query(
        event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model,
        user_search_id: uuid.UUID ) -> dict | None:

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

                    start_time: float = time.perf_counter()

                    # Intentionally not wasting DB CPU sorting; that's compute the browser's JS will do
                    cur.execute(
                        """
                        SELECT  search_name,
                                monitored_urls.url_id,
                                monitored_urls.url,
                                monitored_urls.contents_changed_timestamp,
                                monitored_urls.last_scrape_timestamp
                        FROM    user_searches JOIN monitored_urls ON user_searches.watched_url = monitored_urls.url_id
                        WHERE   user_searches.user_id = %s      AND 
                                user_searches.user_search_id = %s;
                        """,

                        (authenticated_user_id, user_search_id)
                    )
                    end_time: float = time.perf_counter()
                    _logger.debug("DB query for user's watched searches completed in "
                                  f"{end_time - start_time:.03f} seconds")

                    watch_tuple: tuple | None = cur.fetchone()

                    if not watch_tuple:
                        _logger.warning(f"Caller requested details for non-existent user watch {str(user_search_id)}")
                        return None

                    watch_last_update_str: str = _get_timestamp_from_uuid7(user_search_id).isoformat(sep=" ",
                                                                                                     timespec="seconds")
                    change_timestamp: str
                    if watch_tuple[3] is not None:
                        change_timestamp = watch_tuple[3].isoformat(sep=" ", timespec="seconds")
                    else:
                        change_timestamp = watch_last_update_str
                    last_check_timestamp: str
                    if watch_tuple[4] is not None:
                        last_check_timestamp = watch_tuple[4].isoformat(sep=" ", timespec="seconds")
                    else:
                        last_check_timestamp = watch_last_update_str

                    watch_summary: dict[str, str | datetime.datetime] = {
                        "name"                                      : watch_tuple[0],
                        "url_id"                                    : watch_tuple[1],
                        "url"                                       : watch_tuple[2],
                        "last_updated_timestamp"                    : watch_last_update_str,
                        "search_contents_last_changed_timestamp"    : change_timestamp,
                        "search_last_run_timestamp"                 : last_check_timestamp,
                    }
                    _logger.info(f"Returning details for user watch {str(user_search_id)}")

                    return watch_summary

    except Exception as e:
        _logger.critical(f"Database error: {e}")
        raise


def _event_validation(
        event: aws_lambda_powertools.utilities.parser.models.APIGatewayProxyEventV2Model
) -> dict[str, typing.Any] | uuid.UUID:

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

    try:
        user_search_id: uuid.UUID = uuid.UUID(event.pathParameters["user_search_id"])
        if user_search_id.version != 7:
            raise ValueError("Not a v7 UUID")
    except ValueError as e:
        _logger.error("user_search_id path parameter passed was not a valid UUID")
        return {
            "statusCode"    : 400,
            "headers"       : {
                "Content-Type"  : "application/json"
            },
            "body"          : json.dumps(
                {
                    "error"         :  "user_search_id path parameter "
                                      f"\"{event.pathParameters["user_search_id"]}\" not a valid UUIDv7"
                }
            ),
        }

    return user_search_id


def _get_s3_data(monitored_url_id: uuid.UUID) -> tuple[datetime.datetime, list[dict[str, typing.Any]]] | None:
    # Get the monitored URL for this search
    s3_bucket_ssm_param: str = "/itinerary_watch/s3/bucket_name"
    ssm_response = _ssm_client.get_parameter(Name=s3_bucket_ssm_param)
    if not "Parameter" in ssm_response or "Value" not in ssm_response["Parameter"]:
        raise RuntimeError("Param Store did not have key \"{s3_bucket_ssm_param}\"")

    app_s3_bucket_name: str = ssm_response['Parameter']['Value']

    # Get latest search results for the monitored URL
    return _get_latest_serialized_search_results_for_query(app_s3_bucket_name, monitored_url_id)


def _get_latest_serialized_search_results_for_query(
        app_s3_bucket_name: str, url_id: uuid.UUID) -> tuple[datetime.datetime, list[dict[str, typing.Any]]] | None:

    # List *.json for this monitored URL
    prefix_to_search: str = f"db/monitored_urls/{str(url_id)}/"
    search_result_state_files: list[str] = list(_s3_glob(app_s3_bucket_name,
                                                prefix_to_search,
                                                ".json"))
    if len(search_result_state_files) == 0:
        return None

    # Filenames are ISO 8601 datetimes, return contents of not recent
    most_recent_state_file: str = sorted(search_result_state_files, reverse=True)[0]

    # Get just the filename after the last slash
    filename: str = most_recent_state_file.split("/")[-1]
    # Remove the '.json' extension
    timestamp_str: str = filename.replace(".json", "")

    state_file_timestamp: datetime.datetime = datetime.datetime.fromisoformat(timestamp_str)

    _logger.debug("Timestamp of most recent search results for this URL in S3: " +
                  state_file_timestamp.isoformat(sep=" ", timespec="minutes") )

    # Fetch the object from S3
    response = _s3_client.get_object(Bucket=app_s3_bucket_name, Key=most_recent_state_file)

    # Read the StreamingBody and decode bytes to a string
    file_content: str = response["Body"].read().decode("utf-8")

    parsed_json_contents: list[dict] = json.loads(file_content)

    return state_file_timestamp, parsed_json_contents


def _s3_glob(bucket_name: str, prefix_to_search: str, file_extension: str) -> typing.Iterator[str]:
    # Create a paginator to handle buckets with thousands of files
    paginator = _s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix_to_search):
       # Check if the prefix actually contains any objects
        if "Contents" in page:
            for obj in page["Contents"]:
                key = obj["Key"]
                # Filter for files ending in .json
                if key.endswith(file_extension):
                    yield key


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
    # Access the raw 128-bit integer value of the UUID
    uuid_int: int = target_uuid.int

    # Bit-shift 80 bits to the right to isolate the leading 48-bit timestamp
    timestamp_ms: int = uuid_int >> 80

    # Convert millisecond integer count down to a fractional second float
    timestamp_seconds: float = timestamp_ms / 1000.0

    extracted_timestamp: datetime.datetime = datetime.datetime.fromtimestamp(timestamp_seconds,
                                                                             tz=datetime.timezone.utc)

    return extracted_timestamp
