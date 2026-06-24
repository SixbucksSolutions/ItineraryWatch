import abc
import datetime
import enum
import logging
import typing

import cruise_line

class CruiseSailing(abc.ABC):
    @abc.abstractmethod
    def __init__(self: typing.Self,
                 cruise_line_code: cruise_line.CruiseLineCode,
                 cruise_ship_code: enum.Enum,
                 cruise_ship_name: str,
                 cruise_ship_class_name: str | None,
                 sailing_date_start: datetime.date,
                 sailing_date_end: datetime.date,
                 logging_level: int | str = logging.WARNING) -> None:
        self._cruise_line_code: cruise_line.CruiseLineCode = cruise_line_code
        self.cruise_line_name: str = cruise_line.cruise_line_names[self._cruise_line_code]
        self._cruise_ship_code = cruise_ship_code
        self.cruise_ship_name = cruise_ship_name
        self.cruise_ship_class_name = cruise_ship_class_name
        self.sailing_date_start: datetime.date = sailing_date_start
        self.sailing_date_end: datetime.date = sailing_date_end
        self._id: str = f"sailing.{self._cruise_line_code}.{self._cruise_ship_code}." + \
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
        return f"{self.cruise_line_name} {self.cruise_ship_name} sailing: " + \
               f"{self.sailing_date_start.isoformat()} to {self.sailing_date_end.isoformat()}"
