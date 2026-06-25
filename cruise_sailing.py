import datetime
import enum
import logging
import typing

import cruise_day_detail
import cruise_lines


class CruiseSailing:
    def __init__(self,
                 cruise_line_code: cruise_lines.CruiseLineCode,
                 cruise_ship_code: enum.Enum,
                 cruise_ship_name: str,
                 cruise_ship_class_name: str | None,
                 itinerary_name: str,
                 sailing_date_start: datetime.date,
                 sailing_date_end: datetime.date,
                 day_details: list[cruise_day_detail.CruiseDayDetail],
                 logging_level: int | str = logging.WARNING) -> None:

        self.cruise_line_code: cruise_lines.CruiseLineCode = cruise_line_code
        self.cruise_line_name: str = cruise_lines.cruise_line_names[self.cruise_line_code]

        self.cruise_ship_code = cruise_ship_code
        self.cruise_ship_name = cruise_ship_name

        self.cruise_ship_class_name = cruise_ship_class_name

        self.itinerary_name = itinerary_name

        self.sailing_date_start: datetime.date = sailing_date_start
        self.sailing_date_end: datetime.date = sailing_date_end

        self.day_details = day_details

        self._id: str = f"sailing.{self.cruise_line_code}.{self.cruise_ship_code}." + \
                        f"{self.sailing_date_start.isoformat()}.{self.sailing_date_end.isoformat()}"

        self._logger = logging.getLogger(self._id)
        self._logger.setLevel(logging_level)


    def __repr__(self: typing.Any) -> str:
        """
        :return: code-parsable string representation of the object
        """
        return self._id


    def __str__(self: typing.Any) -> str:
        """
        :return: human-readable string representation of the object
        """
        return f"{self.cruise_line_name} {self.cruise_ship_name}, {self.itinerary_name}, " + \
               f"{self.sailing_date_start.isoformat()} to {self.sailing_date_end.isoformat()}"
