import datetime
import enum
import json
import logging
import requests
import time
import typing
import urllib.parse

from src import cruise_day_detail
from src import cruise_lines
from src import cruise_sailing


class _CelebrityShipCode(enum.StrEnum):
    # Active Ocean Fleet as of 2026-07
    ASCENT          = "AT"
    APEX            = "AX"
    BEYOND          = "BY"
    CONSTELLATION   = "CS"
    ECLIPSE         = "EC"
    EDGE            = "EG"
    EQUINOX         = "EQ"
    FLORA           = "FL"
    INFINITY        = "IN"
    MILLENNIUM      = "ML"
    REFLECTION      = "RF"
    SOLSTICE        = "SL"
    SILHOUETTE      = "SI"
    SUMMIT          = "SM"
    XCEL            = "XC"

    # Upcoming Fleet Additions
    XCITE           = "XI"  # Entering service 2028 (Placeholder internal system code)


_ship_names: dict[_CelebrityShipCode, str] = {
    _CelebrityShipCode.APEX          : "Apex",
    _CelebrityShipCode.ASCENT        : "Ascent",
    _CelebrityShipCode.BEYOND        : "Beyond",
    _CelebrityShipCode.CONSTELLATION : "Constellation",
    _CelebrityShipCode.ECLIPSE       : "Eclipse",
    _CelebrityShipCode.EDGE          : "Edge",
    _CelebrityShipCode.EQUINOX       : "Equinox",
    _CelebrityShipCode.FLORA         : "Flora",
    _CelebrityShipCode.INFINITY      : "Infinity",
    _CelebrityShipCode.MILLENNIUM    : "Millennium",
    _CelebrityShipCode.REFLECTION    : "Reflection",
    _CelebrityShipCode.SOLSTICE      : "Solstice",
    _CelebrityShipCode.SILHOUETTE    : "Silhouette",
    _CelebrityShipCode.SUMMIT        : "Summit",
    _CelebrityShipCode.XCEL          : "Xcel",

    # Future
    _CelebrityShipCode.XCITE         : "Xcite",
}

_ship_classes: dict[_CelebrityShipCode, str | None] = {
    _CelebrityShipCode.APEX          : "Edge",
    _CelebrityShipCode.ASCENT        : "Edge",
    _CelebrityShipCode.BEYOND        : "Edge",
    _CelebrityShipCode.CONSTELLATION : "Millennium",
    _CelebrityShipCode.ECLIPSE       : "Solstice",
    _CelebrityShipCode.EDGE          : "Edge",
    _CelebrityShipCode.EQUINOX       : "Solstice",
    _CelebrityShipCode.FLORA         : None,
    _CelebrityShipCode.INFINITY      : "Millennium",
    _CelebrityShipCode.MILLENNIUM    : "Millennium",
    _CelebrityShipCode.REFLECTION    : "Solstice",
    _CelebrityShipCode.SOLSTICE      : "Solstice",
    _CelebrityShipCode.SILHOUETTE    : "Solstice",
    _CelebrityShipCode.SUMMIT        : "Millennium",
    _CelebrityShipCode.XCEL          : "Edge",

    # Future
    _CelebrityShipCode.XCITE         : "Edge",
}


class Celebrity:

    _logger: logging.Logger = logging.getLogger("cruise_lines.Celebrity")
    _logger.setLevel(logging.INFO)

    @staticmethod
    def perform_itinerary_search(search_url: str) -> list[cruise_sailing.CruiseSailing]:
        # Pull out search filters from search URL
        parsed_url: urllib.parse.ParseResult = urllib.parse.urlparse(search_url)

        query_param_search: str | None = dict(urllib.parse.parse_qsl(parsed_url.query)).get("search")
        if query_param_search is None:
            raise ValueError(f"Did not find search parameter in search URL \"{search_url}\"")

        Celebrity._logger.debug(f"Extracted search query param \"{query_param_search}\"")

        Celebrity._logger.info("Starting Celebrity GraphQL API query for itineraries matching filter string: "
                     f"\"{query_param_search}\"")

        return Celebrity._celebrity_api_query(query_param_search)


    @staticmethod
    def _celebrity_api_query(graphql_filter_str: str) -> list[cruise_sailing.CruiseSailing]:
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
                        id
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
                              code
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
                      cruiseRecommendationId
                      total
                      nlFilters
                    }
                  }
                }
            """

        graphql_variables: dict[str, str | dict[str, str] | dict[str, int] | bool] = {
            "filters": graphql_filter_str,
            "currency": "USD",
            "pagination": {
                "count": 25,
                "skip": 0
            },
            "enableNewCasinoExperience": True,
        }

        graphql_payload: dict[str, str | dict[str, str | dict[str, str] | dict[str, int] | bool]] = {
            "query": graphql_query_str,
            "variables": graphql_variables,
        }
        query_headers: dict[str, str] = {
            # Turns out this GraphQL endpoint is hosted by Celebrity's parent. If you don't signal you want
            #   Celebrity results in your query headers, you get Royal Caribbean results by default
            "Brand": "C",

            # If we advertise we're Python requests, the CDN throws a 403 Access Denied; pretend to be Chrome on Win11
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/121.0.0.0 Safari/537.36",
        }

        time_start: float = time.perf_counter()
        search_results_response: requests.Response = requests.post(
            graphql_api_url, json=graphql_payload, headers=query_headers)
        time_end: float = time.perf_counter()

        if not search_results_response.ok:
            raise RuntimeError( "Querying Celebrity GraphQL API endpoint failed, "
                               f"code: {search_results_response.status_code}, error: {search_results_response.text}")

        Celebrity._logger.debug(f"API query returned in {time_end - time_start:.03f} seconds, "
                      f"returned {len(search_results_response.text):,} bytes")

        search_results = search_results_response.json()

        matching_sailings = Celebrity._parse_graphql_response_json(search_results, logging_level=logging.DEBUG)

        return matching_sailings


    @staticmethod
    def _parse_graphql_response_json(parsed_graphql_json: dict[str, typing.Any],
                                    logging_level: int | str = logging.WARNING) -> list[cruise_sailing.CruiseSailing]:
        matching_sailings: list[dict[str, typing.Any]] = \
            parsed_graphql_json["data"]["cruiseSearch"]["results"]["cruises"]

        parsed_sailings: list[cruise_sailing.CruiseSailing] = []

        for curr_itinerary in matching_sailings:
            master_sailing_graphql_node = curr_itinerary["masterSailing"]
            for curr_itinerary_sailing in curr_itinerary["sailings"]:
                ship_code: _CelebrityShipCode = master_sailing_graphql_node["itinerary"]["ship"]["code"]

                itinerary_name: str = master_sailing_graphql_node["itinerary"]["name"]

                start_date: datetime.date = datetime.date.fromisoformat(curr_itinerary_sailing["startDate"])
                end_date: datetime.date = datetime.date.fromisoformat(curr_itinerary_sailing["endDate"])

                activities_per_day: list[cruise_day_detail.CruiseDayDetail] = Celebrity._parse_day_details(
                    master_sailing_graphql_node, curr_itinerary_sailing
                )

                parsed_sailings.append(
                    cruise_sailing.CruiseSailing(
                        cruise_lines.CruiseLineCode.CELEBRITY,
                        ship_code,
                        _ship_names[ship_code],
                        _ship_classes[ship_code],
                        itinerary_name,
                        start_date,
                        end_date,
                        activities_per_day,
                        logging_level,
                    )
                )

            Celebrity._logger.info(f"Finished processing for itinerary: {str(parsed_sailings[-1])}")

        return sorted(parsed_sailings)

    @staticmethod
    def _parse_day_details(master_sailing_graphql_node: dict[str, typing.Any],
                           curr_itinerary_sailing: dict[str, typing.Any]) -> list[cruise_day_detail.CruiseDayDetail]:

        master_sailing_days: list[dict[str, typing.Any]] = master_sailing_graphql_node["itinerary"]["days"]

        sailing_date_start: datetime.date = datetime.date.fromisoformat(curr_itinerary_sailing["startDate"])
        sailing_date_end: datetime.date = datetime.date.fromisoformat(curr_itinerary_sailing["endDate"])

        Celebrity._logger.debug(f"Sailing dates: {sailing_date_start.isoformat()} to {sailing_date_end.isoformat()}")
        # Celebrity._logger.debug(
        #     f"Day breakdown: {json.dumps(master_sailing_days, indent=4, sort_keys=True)}")

        sailing_day_breakdown: list[cruise_day_detail.CruiseDayDetail] = []

        for day_number, day_api_details in enumerate(master_sailing_days, start=1):
            # Celebrity._logger.debug(f"Processing day number {day_number} with details: {json.dumps(day_api_details,
            #     indent=4, sort_keys=True)}")

            # Embark day
            if day_number == 1:
                # Sanity check rest of the entry
                if day_api_details["type"] != "PORT" or \
                        len(day_api_details["ports"]) != 1 or\
                        day_api_details["ports"][0]["activity"] != "EMBARK" or \
                        day_api_details["ports"][0]["arrivalTime"] is not None or \
                        day_api_details["ports"][0]["departureTime"] is None:

                    raise RuntimeError( "Unsupported API data for embark day: "
                                       f"{json.dumps(day_api_details, indent=4, sort_keys=True)}")

                # Add embark details
                sailing_day_breakdown.append(
                    cruise_day_detail.CruiseDayDetail(
                        sailing_date_start,
                        [
                            cruise_day_detail.ShipActivity(
                                cruise_day_detail.ActivityType.PORT_EMBARK,
                                activity_end_time=datetime.time.fromisoformat(
                                    day_api_details["ports"][0]["departureTime"]),
                                activity_location=cruise_day_detail.ShipActivityLocation(
                                    day_api_details["ports"][0]["port"]["name"],
                                    day_api_details["ports"][0]["port"]["region"]
                                ),
                            ),
                        ]
                    )
                )

                Celebrity._logger.debug(f"Added embark day: {str(sailing_day_breakdown[-1])}")

                continue

            # Mid-cruise, full day at sea
            if day_api_details["type"] == "CRUISING":

                # Input validation
                if len(day_api_details["ports"]) != 1 or \
                        day_api_details["ports"][0]["activity"] != "CRUISING" or \
                        day_api_details["ports"][0]["arrivalTime"] is not None or \
                        day_api_details["ports"][0]["departureTime"] is not None or \
                        day_api_details["ports"][0]["port"]["code"] != "ASE" or \
                        day_api_details["ports"][0]["port"]["name"] != "Cruising" or \
                        day_api_details["ports"][0]["port"]["region"] is not None:

                    raise RuntimeError("Unsupported API data for at sea day: "
                                       f"{json.dumps(day_api_details, indent=4, sort_keys=True)}")

                # Add full day at sea
                sailing_day_breakdown.append(
                    cruise_day_detail.CruiseDayDetail(
                        sailing_date_start + datetime.timedelta(days=day_number - 1),
                        [
                            cruise_day_detail.ShipActivity(
                                cruise_day_detail.ActivityType.AT_SEA,
                            ),
                        ]
                    )
                )

                Celebrity._logger.debug(f"Added at sea day: {str(sailing_day_breakdown[-1])}")

                continue

            # Mid-cruise, one or more stops
            if day_api_details["type"] in ["PORT", "MULTI_PORT"]:

                # Input validation
                if len(day_api_details["ports"]) < 1:
                    raise RuntimeError("Need at least one port entry for port day day: "
                                       f"{json.dumps(day_api_details, indent=4, sort_keys=True)}")

                day_activities: list[cruise_day_detail.ShipActivity] = []

                for curr_activity in day_api_details["ports"]:
                    if curr_activity["activity"] in ["DOCKED", "TENDERED", "CRUISING"]:
                        activity_type: cruise_day_detail.ActivityType
                        if curr_activity["activity"] == "DOCKED":
                            if curr_activity["departureTime"] is not None:
                                activity_type = cruise_day_detail.ActivityType.PORT_DOCKED
                            else:
                                # If the docked activity doesn't end, ship is overnighting there
                                activity_type = cruise_day_detail.ActivityType.PORT_DOCKED_OVERNIGHT
                        elif curr_activity["activity"] == "TENDERED":
                            if curr_activity["departureTime"] is not None:
                                activity_type = cruise_day_detail.ActivityType.PORT_TENDERED
                            else:
                                activity_type = cruise_day_detail.ActivityType.PORT_TENDERED_OVERNIGHT
                        elif curr_activity["activity"] == "CRUISING":
                            activity_type = cruise_day_detail.ActivityType.PORT_CRUISING
                        else:
                            raise RuntimeError( "Unsupported activity type: "
                                               f"{json.dumps(curr_activity, indent=4, sort_keys=True)}")

                        start_time: datetime.time | None
                        if curr_activity["arrivalTime"]:
                            start_time = datetime.time.fromisoformat(curr_activity["arrivalTime"])
                        else:
                            start_time = None

                        end_time: datetime.time | None
                        if curr_activity["departureTime"]:
                            end_time = datetime.time.fromisoformat(curr_activity["departureTime"])
                        else:
                            end_time = None

                        day_activities.append(
                            cruise_day_detail.ShipActivity(
                                activity_type=activity_type,
                                activity_start_time=start_time,
                                activity_end_time=end_time,
                                activity_location=cruise_day_detail.ShipActivityLocation(
                                    curr_activity["port"]["name"],
                                    curr_activity["port"]["region"]
                                ),
                            )
                        )

                    elif curr_activity["activity"] == "DEBARK":
                        if curr_activity["arrivalTime"] is None or \
                                curr_activity["departureTime"] is not None:
                            raise RuntimeError( "Unsupported API data for at debark day: "
                                               f"{json.dumps(curr_activity, indent=4, sort_keys=True)}")

                        day_activities.append(
                            cruise_day_detail.ShipActivity(
                                activity_type=cruise_day_detail.ActivityType.PORT_DEBARK,
                                activity_start_time=datetime.time.fromisoformat(
                                    curr_activity["arrivalTime"]),
                                activity_location=cruise_day_detail.ShipActivityLocation(
                                    curr_activity["port"]["name"],
                                    curr_activity["port"]["region"]
                                ),
                            )
                        )

                    else:
                        raise ValueError( "Unsupported activity type for a port day: "
                                         f"{json.dumps(curr_activity, indent=4, sort_keys=True)}")

                if len(day_activities) == 0:
                    raise RuntimeError( "Did not process any activities out of: "
                                        f"{json.dumps(day_api_details, indent=4, sort_keys=True)}")

                # Add day with all its activities
                sailing_day_breakdown.append(
                    cruise_day_detail.CruiseDayDetail(
                        sailing_date_start + datetime.timedelta(days=day_number - 1),
                        day_activities,
                    )
                )

                if day_activities[-1].activity_type != cruise_day_detail.ActivityType.PORT_DEBARK:
                    Celebrity._logger.debug(f"Added port day: {str(sailing_day_breakdown[-1])}")
                else:
                    Celebrity._logger.debug(f"Added debark day: {str(sailing_day_breakdown[-1])}")

                continue

            raise NotImplementedError("No logic to handle this day")

        return sailing_day_breakdown
