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
        """
            Parses a URL and checks if the path is exactly '/vacations'.
            Ignores query strings, fragments, and domains.
            """
        parsed_url: urllib.parse.ParseResult = urllib.parse.urlparse(search_url)

        # Check if the path portion matches exactly
        if parsed_url.path != "/vacations":
            raise ValueError(f"Path was not /vacations in URL \"{search_url}\"")

        query_tuples: list[tuple[str, str]] = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)

        # 3. Build the dictionary and check for duplicates
        query_parameters: dict[str, str] = {}

        param_key_filter: set[str] = {
            "dates",
            "destinations",
            "durations",
        }

        for key, value in query_tuples:
            if key in query_parameters:
                raise ValueError(f"Duplicate query parameter detected: '{key}' in URL {search_url}")
            if key in param_key_filter:
               query_parameters[key] = value

        Norwegian._logger.debug("Parsed/filtered search criteria:")
        Norwegian._logger.debug(json.dumps(query_parameters, indent=4))

        Norwegian._logger.warning(f"Requested to run Norwegian search on {search_url}, not implemented yet")

        return []




    @staticmethod
    def _celebrity_api_query(graphql_filter_str: str) -> list[cruise_sailing.CruiseSailing]:
        pass


    @staticmethod
    def _parse_graphql_response_json(parsed_graphql_json: dict[str, typing.Any],
                                    logging_level: int | str = logging.WARNING) -> list[cruise_sailing.CruiseSailing]:
        pass


    @staticmethod
    def _parse_day_details(master_sailing_graphql_node: dict[str, typing.Any],
                           curr_itinerary_sailing: dict[str, typing.Any]) -> list[cruise_day_detail.CruiseDayDetail]:

        pass
