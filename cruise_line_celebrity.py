import datetime
import enum
import logging
import typing

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


class CruiseLineCelebrity:

    @staticmethod
    def parse_graphql_response_json(parsed_graphql_json: dict[str, typing.Any],
                                    logging_level: int | str = logging.WARNING) -> list[cruise_sailing.CruiseSailing]:
        matching_sailings: list[dict[str, typing.Any]] = \
            parsed_graphql_json["data"]["cruiseSearch"]["results"]["cruises"]

        parsed_sailings: list[cruise_sailing.CruiseSailing] = []

        for curr_itinerary in matching_sailings:
            master_sailing_graphql_node = curr_itinerary["masterSailing"]
            for curr_itinerary_sailing in curr_itinerary["sailings"]:
                ship_code: CelebrityShipCode = \
                    master_sailing_graphql_node["itinerary"]["ship"]["code"]

                itinerary_name: str = master_sailing_graphql_node["itinerary"]["name"]

                start_date: datetime.date = datetime.date.fromisoformat(curr_itinerary_sailing["startDate"])
                end_date: datetime.date = datetime.date.fromisoformat(curr_itinerary_sailing["endDate"])

                parsed_sailings.append(
                    cruise_sailing.CruiseSailing(
                        cruise_line.CruiseLineCode.CELEBRITY,
                        ship_code,
                        ship_names[ship_code],
                        ship_classes[ship_code],
                        itinerary_name,
                        start_date,
                        end_date,
                        logging_level
                    )
                )

        return parsed_sailings
