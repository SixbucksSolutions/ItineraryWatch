import enum

from .celebrity import Celebrity


class CruiseLineCode(enum.StrEnum):
    # Three char Global Distribution System (GDS) codes
    CARNIVAL            = "CCL"
    CELEBRITY           = "CEL"
    DISNEY              = "DIS"
    HOLLAND_AMERICA     = "HAL"
    NORWEGIAN           = "NCL"
    PRINCESS            = "PRN"
    ROYAL_CARIBBEAN     = "RCL"
    VIRGIN              = "VVI"


cruise_line_names: dict[CruiseLineCode, str] = {
    CruiseLineCode.CARNIVAL         : "Carnival",
    CruiseLineCode.CELEBRITY        : "Celebrity",
    CruiseLineCode.DISNEY           : "Disney",
    CruiseLineCode.HOLLAND_AMERICA  : "Holland-America",
    CruiseLineCode.NORWEGIAN        : "Norwegian",
    CruiseLineCode.PRINCESS         : "Princess",
    CruiseLineCode.ROYAL_CARIBBEAN  : "Royal Caribbean",
    CruiseLineCode.VIRGIN           : "Virgin",
}


# Optional: Define what gets exposed during "from my_package import *"
__all__ = ['CruiseLineCode', 'cruise_line_names', 'Celebrity']