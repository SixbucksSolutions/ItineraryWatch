import dataclasses
import datetime
import enum


@dataclasses.dataclass(frozen=True)
class ShipActivityLocation:
    name: str
    region: str


class ActivityType(enum.Enum):
    PORT_EMBARK             = enum.auto()
    PORT_DOCKED             = enum.auto()
    PORT_TENDERED           = enum.auto()
    PORT_CRUISING           = enum.auto()
    PORT_DEBARK             = enum.auto()
    AT_SEA                  = enum.auto()
    PORT_DOCKED_OVERNIGHT   = enum.auto()
    PORT_TENDERED_OVERNIGHT = enum.auto()


@dataclasses.dataclass(frozen=True)
class ShipActivity:
    activity_type: ActivityType
    activity_start_time: datetime.time | None = None
    activity_end_time: datetime.time | None = None
    activity_location: ShipActivityLocation | None = None


@dataclasses.dataclass(frozen=True)
class CruiseDayDetail:
    date: datetime.date
    activities: list[ShipActivity] = dataclasses.field(default_factory=list)


    def __str__(self) -> str:
        return f"Date {self.date.isoformat()} with {len(self.activities)} activities"