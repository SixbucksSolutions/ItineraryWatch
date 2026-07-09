import datetime
import enum
import json
import logging
import requests
import time
import typing
import urllib.parse

import aws_lambda_powertools

from src import cruise_day_detail
from src import cruise_lines
from src import cruise_sailing


import enum

class _ShipCode(enum.StrEnum):
    # Active Ocean Fleet as of 2026-07
    AQUA                = "AQ"
    BLISS               = "BL"
    BREAKAWAY           = "BR"
    DAWN                = "DA"
    ENCORE              = "EN"
    EPIC                = "EP"
    ESCAPE              = "ES"
    GEM                 = "GM"
    GETAWAY             = "GT"
    JADE                = "JD"
    JEWEL               = "JW"
    JOY                 = "JY"
    LUNA                = "LU"
    PEARL               = "PE"
    PRIDE_OF_AMERICA    = "PA"
    PRIMA               = "PR"
    SKY                 = "SK"
    SPIRIT              = "SP"
    STAR                = "ST"
    SUN                 = "SU"
    VIVA                = "VI"

    # Upcoming Fleet Additions
    AURA                = "AU"  # Entering service 2027
    PRIMA_PLUS_4        = "P4"  # Entering service 2028 (Placeholder internal system code)


_ship_names: dict[_ShipCode, str] = {
    _ShipCode.AQUA                  : "Aqua",
    _ShipCode.BLISS                 : "Bliss",
    _ShipCode.BREAKAWAY             : "Breakaway",
    _ShipCode.DAWN                  : "Dawn",
    _ShipCode.ENCORE                : "Encore",
    _ShipCode.EPIC                  : "Epic",
    _ShipCode.ESCAPE                : "Escape",
    _ShipCode.GEM                   : "Gem",
    _ShipCode.GETAWAY               : "Getaway",
    _ShipCode.JADE                  : "Jade",
    _ShipCode.JEWEL                 : "Jewel",
    _ShipCode.JOY                   : "Joy",
    _ShipCode.LUNA                  : "Luna",
    _ShipCode.PEARL                 : "Pearl",
    _ShipCode.PRIDE_OF_AMERICA      : "Pride of America",
    _ShipCode.PRIMA                 : "Prima",
    _ShipCode.SKY                   : "Sky",
    _ShipCode.SPIRIT                : "Spirit",
    _ShipCode.STAR                  : "Star",
    _ShipCode.SUN                   : "Sun",
    _ShipCode.VIVA                  : "Norwegian Viva",

    # Future
    _ShipCode.AURA                  : "Aura",
    _ShipCode.PRIMA_PLUS_4          : "TBA Prima Plus",
}

_ship_classes: dict[_ShipCode, str | None] = {
    _ShipCode.AQUA                  : "Prima Plus",
    _ShipCode.BLISS                 : "Breakaway Plus",
    _ShipCode.BREAKAWAY             : "Breakaway",
    _ShipCode.DAWN                  : "Dawn",
    _ShipCode.ENCORE                : "Breakaway Plus",
    _ShipCode.EPIC                  : None,
    _ShipCode.ESCAPE                : "Breakaway Plus",
    _ShipCode.GEM                   : "Jewel",
    _ShipCode.GETAWAY               : "Breakaway",
    _ShipCode.JADE                  : "Jewel",
    _ShipCode.JEWEL                 : "Jewel",
    _ShipCode.JOY                   : "Breakaway Plus",
    _ShipCode.LUNA                  : "Prima Plus",
    _ShipCode.PEARL                 : "Jewel",
    _ShipCode.PRIDE_OF_AMERICA      : None,
    _ShipCode.PRIMA                 : "Prima",
    _ShipCode.SKY                   : "Sun",
    _ShipCode.SPIRIT                : "Spirit",
    _ShipCode.STAR                  : "Dawn",
    _ShipCode.SUN                   : "Sun",
    _ShipCode.VIVA                  : "Prima",

    # Future
    _ShipCode.AURA                  : "Prima Plus",
    _ShipCode.PRIMA_PLUS_4          : "Prima Plus",
}

class Norwegian:

    _logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="cruise_line.Celebrity")
    _logger.setLevel(logging.DEBUG)

    @staticmethod
    def perform_itinerary_search(search_url: str) -> list[cruise_sailing.CruiseSailing]:
        parsed_url: urllib.parse.ParseResult = urllib.parse.urlparse(search_url)

        # Check if the path portion matches exactly
        if parsed_url.path != "/vacations":
            raise ValueError(f"Path was not /vacations in URL \"{search_url}\"")

        query_tuples: list[tuple[str, str]] = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)

        # 3. Build the dictionary and check for duplicates
        api_search_filters: dict[str, str] = {}

        supported_search_filters: set[str] = {
            "dates",
            "destinations",
            "durations",
        }

        for key, value in query_tuples:
            if key in query_tuples:
                raise ValueError(f"Duplicate query parameter detected: '{key}' in URL {search_url}")
            if key in supported_search_filters:
               api_search_filters[key] = value

        search_results: list[cruise_sailing.CruiseSailing] = Norwegian._execute_api_query(api_search_filters)
        return search_results


    @staticmethod
    def _execute_api_query(api_search_filters: dict[str, str]) -> list[cruise_sailing.CruiseSailing]:
        Norwegian._logger.debug("Search criteria we're passisng to API:")
        Norwegian._logger.debug(json.dumps(api_search_filters, indent=4))

        Norwegian._search_api_get_matching_itinerary_codes_and_package_ids(api_search_filters)
        return []


    @staticmethod
    def _search_api_get_matching_itinerary_codes_and_package_ids(api_search_filters: dict[str, str]):
        itinerary_search_api_endpoint: str = "https://www.ncl.com/api/v2/vacations/search"

        search_api_query_params: dict[str, str | int] = api_search_filters

        # Clean up durations key, search API doesn't take tilde at the end of duration values
        if "durations" in search_api_query_params:
            duration_values: list[str] = str(search_api_query_params["durations"]).split(",")
            corrected_duration_values: list[str] = []
            known_duration_filters: list[str] = [
                "1-4",
                "5-8",
                "9-14",
                "15"
            ]
            for curr_candidate_duration in duration_values:
                Norwegian._logger.debug(f"Candidate duration: {curr_candidate_duration}")
                for known_filter in known_duration_filters:
                    if curr_candidate_duration.startswith(known_filter):
                        Norwegian._logger.debug(f"Candidate duration matched known: {known_filter}")
                        corrected_duration_values.append(known_filter)
                        break
                else:
                    Norwegian._logger.warning(f"Unknown duration filter value: {curr_candidate_duration}")
                    return

            # Now that we have  leaned up all values for search, put them back in query params
            search_api_query_params["durations"] = ",".join(corrected_duration_values)

        # Add in extra params used during site reverse engineering
        search_api_query_params.update(
            {
                "filterConfig"  : "search-filters-configuration",
                "limit"         : 12,
                "offset"        : 0,
            }
        )

        Norwegian._logger.debug(
            f"Full list of parameter being passed to API endpoint {itinerary_search_api_endpoint}:")
        Norwegian._logger.debug(json.dumps(search_api_query_params, indent=4))

        query_headers: dict[str, str] = {
            # If we advertise we're Python requests, the CDN throws a 403 Access Denied; pretend to be Chrome on Win11
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/121.0.0.0 Safari/537.36",
        }

        time_start: float = time.perf_counter()
        search_results_response: requests.Response = requests.get(
            itinerary_search_api_endpoint, headers=query_headers, params=search_api_query_params)
        time_end: float = time.perf_counter()

        if not search_results_response.ok:
            Norwegian._logger.warning(f"Querying Norwegian REST API endpoint {itinerary_search_api_endpoint} failed, "
                                      f"code: {search_results_response.status_code}, "
                                      f"error: {search_results_response.text}")
            return

        Norwegian._logger.debug(f"API query returned in {time_end - time_start:.03f} seconds, "
                                f"returned {len(search_results_response.text):,} bytes")

        search_results = search_results_response.json()
        Norwegian._logger.debug(json.dumps(search_results, indent=4))



    @staticmethod
    def _parse_api_response(parsed_graphql_json: dict[str, typing.Any],
                                    logging_level: int | str = logging.WARNING) -> list[cruise_sailing.CruiseSailing]:
        pass


    @staticmethod
    def _parse_api_response_day_details(master_sailing_graphql_node: dict[str, typing.Any],
                           curr_itinerary_sailing: dict[str, typing.Any]) -> list[cruise_day_detail.CruiseDayDetail]:

        pass
