import datetime
import json
import logging
import typing
import urllib.parse
import uuid

import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.data_classes.sns_event
import aws_lambda_powertools.utilities.typing
import boto3
import psycopg

import cruise_lines
import cruise_sailing


_logger: logging.Logger = logging.getLogger("itinerary_watch")
_logger.setLevel(logging.DEBUG)

_ssm_client = boto3.client("ssm", region_name="us-east-2")
_s3_client = boto3.client("s3", region_name="us-east-2")


def sns_message_entry_point(event: aws_lambda_powertools.utilities.data_classes.SNSEvent,
                            _context: aws_lambda_powertools.utilities.typing.LambdaContext | None) -> None:

    for curr_event_record in event.records:
        _process_sns_event_record(curr_event_record)


def _process_sns_event_record(
        curr_record: aws_lambda_powertools.utilities.data_classes.sns_event.SNSEventRecord) -> None:

    curr_sns_message_id: uuid.UUID = uuid.UUID(curr_record.sns.message_id)
    _logger.info(f"Starting to process new SNS message with ID {str(curr_sns_message_id)}")

    try:
        parsed_payload: dict[str, int | str] = json.loads(curr_record.sns.message)
    except Exception as e:
        _logger.warning(f"Could not parse JSON from SNS message payload, error: {e}")
        return

    _logger.debug(f"Got scrape start message: {json.dumps(parsed_payload, indent=4, sort_keys=True)}")

    # Make sure it's a valid message
    if not _valid_json(parsed_payload):
        _logger.warning(f"Got invalid JSON, aborting: {json.dumps(parsed_payload, indent=4, sort_keys=True)}")
        return

    valid_search_url: str = str(parsed_payload["monitored_url"])
    valid_search_url_id: uuid.UUID = uuid.UUID(str(parsed_payload["monitored_url_id"]))

    _logger.info(f"SNS message ID {str(curr_sns_message_id)} contains monitored URL: \"{valid_search_url}\" "
                 f"(URL ID: \"{valid_search_url_id}\")")

    _scrape_search_url(valid_search_url, valid_search_url_id)


def _valid_json(parsed_payload: dict[str, int | str]) -> bool:

    # Needs to be a dict with proper keys and values

    if not isinstance(parsed_payload, dict):
        _logger.warning("Parsed JSON was not a dict")
        return False

    if not len(parsed_payload) == 3:
        _logger.warning("Dict did not have exactly two keys")
        return False

    check_keys: list[str] = ["monitored_url", "monitored_url_id", "schema_datetime"]
    if not all(key in parsed_payload for key in check_keys):
        _logger.warning(f"Dict did not contain all of the expected keys: {sorted(check_keys)}")
        return False

    if not isinstance(parsed_payload["schema_datetime"], str):
        _logger.warning("Schema version value not a string")
        return False

    supported_schema_datetimes: set[str] = {
        "2026-06-24 15:00+00:00",
    }
    if parsed_payload["schema_datetime"] not in supported_schema_datetimes:
        _logger.warning("Unsupported schema version")
        return False

    if not isinstance(parsed_payload["monitored_url"], str):
        _logger.warning("monitored_url value not a string")
        return False

    if not _valid_url(typing.cast(str, parsed_payload["monitored_url"])):
        _logger.warning("monitored_url value not a valid URL")
        return False

    if not isinstance(parsed_payload["monitored_url_id"], str):
        _logger.warning("monitored_url_id value not a string")
        return False

    try:
        uuid.UUID(str(parsed_payload["monitored_url_id"]))
    except Exception as e:
        _logger.warning(f"monitored_url_id value not a valid UUID: \"{parsed_payload["monitored_url_id"]}\"")
        return False

    return True


def _valid_url(possible_url: str) -> bool:
    try:
        result = urllib.parse.urlparse(possible_url)
        # Ensure it has a scheme (e.g., http/https) and a domain name
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def _scrape_search_url(url: str, url_id: uuid.UUID) -> None:
    _logger.info(f"Running search on URL {url}")

    returned_matches: list[cruise_sailing.CruiseSailing] = cruise_lines.Celebrity.perform_itinerary_search(url)
    # _logger.debug(json.dumps(returned_matches, indent=4, sort_keys=True, default=str))

    serialized_matches: list[dict] = [
        cruise_sailing.serialize_cruise_sailing(sailing) for sailing in returned_matches
    ]

    app_s3_bucket_name: str = _read_parameter_store_param("/itinerary_watch/s3/bucket_name")
    # _logger.debug(f"S3 bucket name for DB: {app_s3_bucket_name}")

    # Retrieve latest unique search results for this search from DB, if any
    search_results_to_compare_against: list[dict] | None = _get_latest_serialized_search_results_for_query(
        app_s3_bucket_name, url_id
    )

    # Did search results change?
    if serialized_matches == search_results_to_compare_against:
        _logger.info("Our serialized data exactly matches most recent state S3, nothing more to do")
        return

    _logger.info("Search results have changed since latest previous data, or this is first run for this URL")

    # Write these search results out
    # TODO: uncomment!
    # _write_new_search_results(url_id, serialized_matches, app_s3_bucket_name)

    # Update last run timestamp for this search URL in app DB
    _update_db_last_search_time(url_id)

    # TODO: Notify customers monitoring this search
    # raise NotImplementedError("Don't not exist yet nossir")


def _get_search_url_details(url: str) -> dict[str, typing.Any]:
    return {
        "last_scrape_attempt": datetime.datetime(
            year=1970,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            tzinfo=datetime.timezone.utc),
    }


def _read_parameter_store_param(parameter_name: str) -> str:
    return _ssm_client.get_parameter(Name=parameter_name)['Parameter']['Value']


def _read_parameter_store_params(parameter_names: list[str]) -> dict[str, str]:
    retrieved_params: list[dict] = _ssm_client.get_parameters(Names=parameter_names)['Parameters']
    # _logger.debug(f"Retrieved params: {retrieved_params}")
    return_dict: dict[str, str] = {}
    for param_idx, param_details in enumerate(retrieved_params):
        return_dict[param_details['Name']] = retrieved_params[param_idx]['Value']
    return return_dict


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


def _get_latest_serialized_search_results_for_query(app_s3_bucket_name: str, url_id: uuid.UUID) -> list[dict] | None:

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

    return parsed_json_contents


def _write_new_search_results(url_id: uuid.UUID,
                              serializable_search_results: list[dict],
                              s3_bucket_name: str) -> None:

    s3_key: str = f"db/monitored_urls/{str(url_id)}/" + \
                  f"{datetime.datetime.now(tz=datetime.timezone.utc).isoformat(sep=" ", timespec="minutes")}.json"

    serialized_contents: str = json.dumps(serializable_search_results)

    _s3_client.put_object(
        Bucket=s3_bucket_name,
        Key=s3_key,
        Body=serialized_contents,
        ContentType="application/json"  # Adjust content type based on your file format
    )

    _logger.info(f"Wrote new search results for URL {str(url_id)} to s3://{s3_bucket_name}/{s3_key}")


def _update_db_last_search_time(url_id: uuid.UUID) -> None:
    # Read Postgres connection details from Parameter Store
    postgres_connection_params: dict[str, str] = _get_pg_server_connection_details()
    # _logger.debug(f"Postgres connection params: {json.dumps(postgres_connection_params, indent=4)}")

    try:
        # Context manager syntax ("with") gets the connection auto-closed at scope exit
        with psycopg.connect(
                    host=postgres_connection_params["db_hostname"],
                    dbname=postgres_connection_params["db_dbname"],
                    user=postgres_connection_params["db_user"],
                    password=postgres_connection_params["db_password"],
                    sslmode="verify-full",
                    sslrootcert="./aws-rds-global-bundle.pem",
                ) as conn:

            # Context managers for cursors ensure they *also* close automatically
            with conn.cursor() as cur:
                cur.execute("UPDATE version();")
                print(cur.fetchone()[0])

    except Exception as e:
        _logger.critical(f"Database error: {e}")
        raise


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


if __name__ == "__main__":

    def _create_fake_sns_event() -> aws_lambda_powertools.utilities.data_classes.SNSEvent:
        return aws_lambda_powertools.utilities.data_classes.SNSEvent(
            {
                "Records": [
                    {
                        "EventVersion": "1.0",
                        "EventSubscriptionArn": "arn:aws:sns:us-east-1:123456789012:ExampleTopic:xxxx",
                        "EventSource": "aws:sns",
                        "Sns": {
                            "SignatureVersion": "1",
                            "Signature": "EXAMPLE",
                            "SigningCertUrl": "EXAMPLE",
                            "MessageId": "95df01b4-ee98-5cb9-9903-4c221d41eb5e",
                            "Message": "{" + \
                                "\"schema_datetime\": \"2026-06-24 15:00+00:00\", " + \
                                "\"monitored_url_id\": \"019ef9cf-e013-79bf-a299-a25f20e2f495\", " + \
                                "\"monitored_url\": \"https://www.celebritycruises.com/cruises?search=nights:9~11,gte12|startDate:2028-01-01~2028-01-31|visiting:CARI&sort=by:NIGHTS|order:DESC&country=USA&currency=USD\"}",
                            "MessageAttributes": {},
                            "Timestamp": "1970-01-01T00:00:00.000Z",
                            "TopicArn": "arn:aws:sns:us-east-1:123456789012:ExampleTopic",
                            "UnsubscribeUrl": "EXAMPLE"
                        }
                    }
                ]
            }
        )

    logging.basicConfig()
    sns_message_entry_point(_create_fake_sns_event(), None)
