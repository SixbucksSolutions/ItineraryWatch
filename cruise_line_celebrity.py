import datetime
import enum
import json
import logging
import typing
import urllib.parse

import cruise_line
import cruise_sailing

class CelebrityShipCode(enum.StrEnum):
    APEX            = "AP"
    ASCENT          = "AS"
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
                 sailing_url: urllib.parse.ParseResult,
                 logging_level: int | str = logging.WARNING) -> None:

        # Now populate fields in abstracted parent
        super().__init__(
            cruise_line.CruiseLineCode.CELEBRITY,
            CelebrityShipCode.ECLIPSE,
            ship_names[CelebrityShipCode.ECLIPSE],
            ship_classes[CelebrityShipCode.ECLIPSE],
            datetime.date(2028 , 1, 4),
            datetime.date(2028, 1, 20),
            logging_level
        )