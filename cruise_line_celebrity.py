import datetime
import enum
import json
import logging
import typing
import urllib.parse

from aws_lambda_powertools.utilities.feature_flags.schema import LOGGER

import cruise_line
import cruise_sailing

class CelebrityShipCode(enum.StrEnum):
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


ship_names: dict[CelebrityShipCode, str] = {
    CelebrityShipCode.APEX          : "Apex",
    CelebrityShipCode.ASCENT        : "Ascent",
    CelebrityShipCode.BEYOND        : "Beyond",
    CelebrityShipCode.CONSTELLATION : "Constellation",
    CelebrityShipCode.ECLIPSE       : "Eclipse",
    CelebrityShipCode.EDGE          : "Edge",
    CelebrityShipCode.EQUINOX       : "Equinox",
    CelebrityShipCode.FLORA         : "Flora",
    CelebrityShipCode.INFINITY      : "Infinity",
    CelebrityShipCode.MILLENNIUM    : "Millennium",
    CelebrityShipCode.REFLECTION    : "Reflection",
    CelebrityShipCode.SOLSTICE      : "Solstice",
    CelebrityShipCode.SILHOUETTE    : "Silhouette",
    CelebrityShipCode.SUMMIT        : "Summit",
    CelebrityShipCode.XCEL          : "Excel",
    CelebrityShipCode.XPEDITION     : "Xpedition",
    CelebrityShipCode.XPLORATION    : "Xploration",
}

ship_classes: dict[CelebrityShipCode, str | None] = {
    CelebrityShipCode.APEX          : "Edge",
    CelebrityShipCode.ASCENT        : "Edge",
    CelebrityShipCode.BEYOND        : "Edge",
    CelebrityShipCode.CONSTELLATION : "Millennium",
    CelebrityShipCode.ECLIPSE       : "Solstice",
    CelebrityShipCode.EDGE          : "Edge",
    CelebrityShipCode.EQUINOX       : "Solstice",
    CelebrityShipCode.FLORA         : None,
    CelebrityShipCode.INFINITY      : "Millennium",
    CelebrityShipCode.MILLENNIUM    : "Millennium",
    CelebrityShipCode.REFLECTION    : "Solstice",
    CelebrityShipCode.SOLSTICE      : "Solstice",
    CelebrityShipCode.SILHOUETTE    : "Solstice",
    CelebrityShipCode.SUMMIT        : "Millennium",
    CelebrityShipCode.XCEL          : "Edge",
    CelebrityShipCode.XPEDITION     : None,
    CelebrityShipCode.XPLORATION    : None,
}


class CruiseSailingCelebrity(cruise_sailing.CruiseSailing):
    def __init__(self: typing.Self,
                 master_sailing_graphql_node: dict[str, typing.Any],
                 sailings_graphql_node: dict[str, typing.Any],
                 logging_level: int | str = logging.WARNING) -> None:

        ship_code: CelebrityShipCode = \
            master_sailing_graphql_node["itinerary"]["ship"]["code"]

        itinerary_name: str = master_sailing_graphql_node["itinerary"]["name"]

        start_date: datetime.date = datetime.date.fromisoformat(sailings_graphql_node["startDate"])
        end_date: datetime.date = datetime.date.fromisoformat(sailings_graphql_node["endDate"])


        # Now populate fields in abstracted parent
        super().__init__(
            cruise_line.CruiseLineCode.CELEBRITY,
            ship_code,
            ship_names[ship_code],
            ship_classes[ship_code],
            itinerary_name,
            start_date,
            end_date,
            logging_level
        )

        # self._logger.debug(json.dumps(master_sailing_graphql_node, indent=4, sort_keys=True))

        # raise NotImplementedError("Not a thing")



def parse_graphql_response_json(parsed_graphql_json: dict[str, typing.Any],
                                logging_level: int | str = logging.WARNING) -> list[cruise_sailing.CruiseSailing]:
    matching_sailings: list[dict[str, typing.Any]] = parsed_graphql_json["data"]["cruiseSearch"]["results"]["cruises"]

    parsed_sailings: list[cruise_sailing.CruiseSailing] = []

    for curr_itinerary in matching_sailings:
        for curr_itinerary_sailing in curr_itinerary["sailings"]:
            parsed_sailings.append(CruiseSailingCelebrity(curr_itinerary["masterSailing"], curr_itinerary_sailing))

    return parsed_sailings