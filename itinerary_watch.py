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
import requests

import cruise_line
import cruise_line_celebrity

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


def _scrape_search_url(url: str, _url_id: uuid.UUID) -> None:
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

    # Pull out search filters from search URL
    parsed_url: urllib.parse.ParseResult = urllib.parse.urlparse(url)

    query_param_search: str | None = dict(urllib.parse.parse_qsl(parsed_url.query)).get("search")
    if query_param_search is None:
        raise ValueError(f"Did not find search parameter in search URL \"{url}\"")

    _logger.debug(f"Extracted search query param \"{query_param_search}\"")

    _logger.info( "Starting Celebrity GraphQL API query for itineraries matching filter string: "
                 f"\"{query_param_search}\"")

    _celebrity_api_query(query_param_search)


def _celebrity_api_query(graphql_filter_str: str) -> None:
    graphql_api_url: str = "https://www.celebritycruises.com/cruises/graph"

    graphql_query_str: str = """
        query CruisesSearchResults(
          $filters: String
          $qualifiers: String
          $sort: CruiseSearchSort
          $pagination: CruiseSearchPagination
          $nlSearch: String
          $enableNewCasinoExperience: Boolean = false
        ) {
          cruiseSearch(
            filters: $filters
            qualifiers: $qualifiers
            sort: $sort
            pagination: $pagination
            nlSearch: $nlSearch
          ) {
            results {
              cruises {
                productViewLink                
                masterSailing {
                  itinerary {
                    name
                    code
                    days {
                      number
                      type
                      ports {
                        activity
                        arrivalTime
                        departureTime
                        port {
                          code
                          name
                          region
                        }
                      }
                    }
                    sailingNights
                    ship {
                      name
                    }
                  }
                }                
                sailings {
                  itinerary {
                    code
                  }
                  sailDate
                  startDate
                  endDate
                  stateroomClassPricing {
                    price {
                      netAmount @include(if: $enableNewCasinoExperience)
                      currency {
                        code
                      }
                    }
                    stateroomClass {
                      id
                    }
                  }
                }
              }
            }
          }
        }
    """

    graphql_variables: dict[str, str | dict[str, str] | dict[str, int] | bool] = {
        "filters"   : "nights:9~11,gte12|startDate:2028-01-01~2028-01-31|visiting:CARI",
        "currency"  : "USD",
        "pagination"    : {
            "count"     : 25,
            "skip"      : 0
        },
        "enableNewCasinoExperience": True,
    }

    graphql_payload: dict[str, str | dict[str, str | dict[str, str] | dict[str, int] | bool]] = {
        "query"     : graphql_query_str,
        "variables" : graphql_variables,
    }
    query_headers: dict[str, str] = {
        # Turns out this GraphQL endpoint is hosted by Celebrity's parent. If you don't signal you want
        #   Celebrity results in your query headers, you get Royal Caribbean results by default
        "Brand"         : "C",

        # If we advertise we're Python requests, the CDN throws a 403 Access Denied; pretend to be Chrome on Win11
        "User-Agent"    : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/121.0.0.0 Safari/537.36",
    }

    time_start: float = time.perf_counter()
    search_results_response: requests.Response = requests.post(
        graphql_api_url, json=graphql_payload, headers=query_headers)
    time_end: float = time.perf_counter()

    if not search_results_response.ok:
        _logger.warning( "Querying Celebrity GraphQL API endpoint failed, "
                        f"code: {search_results_response.status_code}, error: {search_results_response.text}")
        return

    _logger.debug(f"API query returned in {time_end - time_start:.03f} seconds, "
                  f"returned {len(search_results_response.text):,} bytes")

    cruise_sailing = cruise_line_celebrity.CruiseSailingCelebrity(search_results_response.text)

    print(f"Repr: {repr(cruise_sailing)}\nStr: {str(cruise_sailing)}")

    raise NotImplementedError("Done for now")


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