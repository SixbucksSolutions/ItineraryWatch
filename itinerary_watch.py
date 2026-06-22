import datetime
import json
import logging
import time
import typing
import urllib.parse
import uuid

import aws_lambda_powertools.utilities.data_classes
import aws_lambda_powertools.utilities.data_classes.sns_event
import aws_lambda_powertools.utilities.typing
import bs4
import requests


_logger: logging.Logger = logging.getLogger(__name__)
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

    valid_search_url: str = typing.cast(str, parsed_payload["search_url"])

    _logger.info(f"SNS message ID {str(curr_sns_message_id)} contains search URL: \"{valid_search_url}\"")

    _scrape_search_url(valid_search_url)


def _valid_json(parsed_payload: dict[str, int | str]) -> bool:

    # Needs to be a dict with proper keys and values

    if not isinstance(parsed_payload, dict):
        _logger.warning("Parsed JSON was not a dict")
        return False

    if not len(parsed_payload) == 2:
        _logger.warning("Dict did not have exactly two keys")
        return False

    check_keys: list[str] = ["schema_version", "search_url"]
    if not all(key in parsed_payload for key in check_keys):
        _logger.warning("Dict did not contain all of the expected keys")
        return False

    if not isinstance(parsed_payload["schema_version"], int):
        _logger.warning("Schema version value not an integer")
        return False

    supported_schema_versions: set[int] = {
        1,
    }
    if parsed_payload["schema_version"] not in supported_schema_versions:
        _logger.warning("Unsupported schema version")
        return False

    if not isinstance(parsed_payload["search_url"], str):
        _logger.warning("search_url value not a string")
        return False

    if not _valid_url(typing.cast(str, parsed_payload["search_url"])):
        _logger.warning("search_url value not a valid URL")
        return False

    return True


def _valid_url(possible_url: str) -> bool:
    try:
        result = urllib.parse.urlparse(possible_url)
        # Ensure it has a scheme (e.g., http/https) and a domain name
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def _scrape_search_url(url: str) -> None:
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

    _logger.info(f"Scraping URL {url} as it's never been scraped or time of previous scrape was >= 24 hours ago")

    # Start a requests session so the CDN will permit us to search
    celebrity_website_session: requests.Session = requests.Session()

    celebrity_website_session.headers.update(
        {
            "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
                      "*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive"
        }
    )

    _logger.debug(f"Starting web scrape for search URL \"{url}\"")
    time_start: float = time.perf_counter()
    search_results_response: requests.Response = celebrity_website_session.get(url)
    time_end: float = time.perf_counter()

    if not search_results_response.ok:
        _logger.warning(f"Scraping failed for search URL {url}, code: {search_results_response.status_code}, "
                        f"error: {search_results_response.text}")
        return

    _logger.debug(f"Scrape of search URL took {time_end - time_start:.03f} seconds, "
                  f"returned {len(search_results_response.text):,} bytes")

    _process_search_results_response(search_results_response)


def _process_search_results_response(search_results_response: requests.Response) -> None:
    time_start: float = time.perf_counter()
    # 1. Parse the string using the high-performance 'lxml' engine
    parsed_html: bs4.BeautifulSoup = bs4.BeautifulSoup(search_results_response.text, "lxml")
    time_end: float = time.perf_counter()
    _logger.debug(f"Time to parse HTML: {time_end - time_start:.03f} seconds")

    # 2. Extract text from a specific tag using a class name
    title = parsed_html.find("h1", class_="title").text
    print(f"Title: {title}")  # Output: Welcome to Celebrity Cruises





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
                            "Message": "{\"schema_version\": 1, " + \
                                "\"search_url\": \"https://www.celebritycruises.com/cruises?search=nights:9~11,gte12|startDate:2028-01-01~2028-01-31|visiting:CARI&sort=by:NIGHTS|order:DESC&country=USA&currency=USD\"}",
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