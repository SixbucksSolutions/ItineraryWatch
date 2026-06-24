import datetime
import enum
import logging
import requests
import time
import typing
import urllib.parse

import cruise_lines
import cruise_sailing


class _CelebrityShipCode(enum.StrEnum):
    APEX            = "AP"
    ASCENT          = "AT"
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
    XPEDITION       = "XP"
    XPLORATION      = "XR"


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
    _CelebrityShipCode.XCEL          : "Excel",
    _CelebrityShipCode.XPEDITION     : "Xpedition",
    _CelebrityShipCode.XPLORATION    : "Xploration",
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
    _CelebrityShipCode.XPEDITION     : None,
    _CelebrityShipCode.XPLORATION    : None,
}


class Celebrity:

    _logger: logging.Logger = logging.getLogger("cruise_lines.Celebrity")
    _logger.setLevel(logging.DEBUG)

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
            "filters": "nights:9~11,gte12|startDate:2028-01-01~2028-01-31|visiting:CARI",
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

                # TODO: build day list
                day_list = []

                parsed_sailings.append(
                    cruise_sailing.CruiseSailing(
                        cruise_lines.CruiseLineCode.CELEBRITY,
                        ship_code,
                        _ship_names[ship_code],
                        _ship_classes[ship_code],
                        itinerary_name,
                        start_date,
                        end_date,
                        day_list,
                        logging_level,
                    )
                )

        return parsed_sailings
