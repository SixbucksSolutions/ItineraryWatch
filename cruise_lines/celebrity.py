import datetime
import enum
import logging
import typing

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

    @staticmethod
    def parse_graphql_response_json(parsed_graphql_json: dict[str, typing.Any],
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
