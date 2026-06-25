import datetime
import json
import logging
import pathlib
import typing
import urllib.parse
import uuid

import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.data_classes.sns_event
import aws_lambda_powertools.utilities.typing

import cruise_lines
import cruise_sailing


_logger: logging.Logger = logging.getLogger("itinerary_watch")
_logger.setLevel(logging.DEBUG)


def sns_message_entry_point(event: aws_lambda_powertools.utilities.data_classes.SNSEvent,
                            _context: aws_lambda_powertools.utilities.typing.LambdaContext | None) -> None:

    for curr_event_record in event.records:
        _process_sns_event_record(curr_event_record)


def _process_sns_event_record(curr_record: aws_lambda_powertools.utilities.data_classes.sns_event.SNSEventRecord) -> None:
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
        "2026-06-24T15:00Z",
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
    try:
        search_url_details: dict[str, typing.Any] = _get_search_url_details(url)
    except Exception as e:
        _logger.warning(f"Could not get last scrape time for URL {url}, error: {e}")
        return

    last_scrape_attempt: datetime.datetime = search_url_details["last_scrape_attempt"]

    if last_scrape_attempt is not None:
        now_utc: datetime.datetime = datetime.datetime.now(tz=datetime.timezone.utc)
        time_difference: datetime.timedelta = now_utc - last_scrape_attempt

        if time_difference < datetime.timedelta(hours=24):
            _logger.info(f"Ignoring scrape request for URL {url}, has not been 24 hours since previous")
            return

    _logger.info(f"Running search on URL {url} as it's never been scraped or >= 24 hours ago")

    returned_matches: list[cruise_sailing.CruiseSailing] = cruise_lines.Celebrity.perform_itinerary_search(url)
    # _logger.debug(json.dumps(returned_matches, indent=4, sort_keys=True, default=str))

    serialized_matches: list[dict] = [
        cruise_sailing.serialize_cruise_sailing(sailing) for sailing in returned_matches
    ]

    # Retrieve latest unique search results for this search from DB, if any
    search_results_to_compare_against: list[dict] | None = _get_latest_serialized_search_results_for_query(
        url_id
    )

    # Did search results change?
    if serialized_matches == search_results_to_compare_against:
        _logger.info("Our serialized data exactly matches most recent from \"DB\", nothing more to do")
        return

    # Write these search results out
    _write_new_search_results_to_db(url_id, serialized_matches)

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


def _get_latest_serialized_search_results_for_query(url_id: uuid.UUID) -> list[dict] | None:
    # May be S3 in the future, local disk for now
    dir_for_this_url: pathlib.Path = pathlib.Path("db/monitored_urls") / str(url_id)

    if not dir_for_this_url.exists():
        return None

    # Make sure it IS a dir
    if not dir_for_this_url.is_dir():
        raise RuntimeError(f"\"DB\" path for monitored URL {str(url_id)} exists but isn't a directory!?!?!?!")

    dir_json_contents: list[pathlib.Path] = list(dir_for_this_url.glob("*.json"))

    if len(dir_json_contents) == 0:
        return None

    # Filenames are ISO 8601 datetimes, return contents of not recent
    most_recent_json_path: pathlib.Path = sorted(dir_json_contents, reverse=True)[0]

    _logger.debug(f"Most recent search results for search URL {str(url_id)}: {most_recent_json_path.stem}")

    with open(most_recent_json_path) as state_json_handle:
        parsed_json_contents: list[dict] = json.load(state_json_handle)

    return parsed_json_contents


def _write_new_search_results_to_db(url_id: uuid.UUID, serializable_search_results: list[dict]) -> None:
    dir_for_this_url: pathlib.Path = pathlib.Path("db/monitored_urls") / str(url_id)

    if not dir_for_this_url.exists():
        # Create it with all parents
        dir_for_this_url.mkdir(parents=True)
    elif not dir_for_this_url.is_dir():
       raise RuntimeError(f"\"DB\" path for monitored URL {str(url_id)} exists but isn't a directory!?!?!?!")

    # Now we know the dir existed previously OR we created it, write out state with current UTC timestamp
    json_file_path: pathlib.Path = dir_for_this_url / \
                     f"{datetime.datetime.now(tz=datetime.timezone.utc).isoformat(sep=" ", timespec="seconds")}.json"

    with open(json_file_path, "w") as state_json_handle:
        json.dump(serializable_search_results, state_json_handle, indent=4)

    _logger.info(f"Wrote new search results for URL {str(url_id)} to {json_file_path}")


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
                            "Message": "{\"schema_datetime\": \"2026-06-24T15:00Z\", " + \
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
