import datetime
import enum
import functools
import logging
import typing

import cruise_day_detail
import cruise_lines


@functools.total_ordering
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


    # For total ordering decorator, need to implement < and == and then totalordering correctly populates the rest
    #       of the ordering comparison operators
    def __lt__(self, other: object) -> bool | type(NotImplemented):
        if not isinstance(other, CruiseSailing):
            return NotImplemented

        # Sort order: first on sailing start date, if equal, by strict alpha comparison on
        #       *lowercase* cruise line name + ship name string (e.g. all Celebrity ships come before all Virgin)
        if self.sailing_date_start == other.sailing_date_start:
            our_compare_str: str = f"{self.cruise_line_name} {self.cruise_ship_name}".lower()
            other_compare_str: str = f"{other.cruise_line_name} {other.cruise_ship_name}".lower()
            return our_compare_str < other_compare_str

        return self.sailing_date_start < other.sailing_date_start


    def __eq__(self, other: object) -> bool | type(NotImplemented):
        if not isinstance(other, CruiseSailing):
            return NotImplemented

        # If dates aren't equal, exit early to save building strings
        if self.sailing_date_start != other.sailing_date_start:
            return False

        our_compare_str: str = f"{self.cruise_line_name} {self.cruise_ship_name}".lower()
        other_compare_str: str = f"{other.cruise_line_name} {other.cruise_ship_name}".lower()

        return our_compare_str == other_compare_str
