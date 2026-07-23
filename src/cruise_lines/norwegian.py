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
    _ShipCode.VIVA                  : "Viva",

    # Future
    _ShipCode.AURA                  : "Aura",
    _ShipCode.PRIMA_PLUS_4          : "TBA Prima Plus",
}

# Need a reverse dict because their API returns ship names node codes. Keys get upper cased
#   for easy case-agnostic lookup
_ship_codes: dict[str, _ShipCode] = {value.upper(): key for key, value in _ship_names.items()}

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

    _logger: aws_lambda_powertools.Logger = aws_lambda_powertools.Logger(service="cruise_line.Norwegian")
    _logger.setLevel(logging.INFO)

    @staticmethod
    def perform_itinerary_search(search_url: str) -> list[cruise_sailing.CruiseSailing]:
        parsed_url: urllib.parse.ParseResult = urllib.parse.urlparse(search_url)

        # Check if the path portion matches exactly
        if parsed_url.path != "/vacations":
            raise ValueError(f"Path was not /vacations in URL \"{search_url}\"")

        query_tuples: list[tuple[str, str]] = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)

        # 3. Build the dictionary and check for duplicates
        api_search_filters: dict[str, str] = {}

        supported_search_filters: set[str] = {
            "dates",
            "destinations",
            "durations",
        }

        for key, value in query_tuples:
            if key in query_tuples:
                raise ValueError(f"Duplicate query parameter detected: '{key}' in URL {search_url}")
            if key in supported_search_filters:
               api_search_filters[key] = value

        search_results: list[cruise_sailing.CruiseSailing] = Norwegian._execute_api_query(api_search_filters)
        return search_results


    @staticmethod
    def _execute_api_query(api_search_filters: dict[str, str]) -> list[cruise_sailing.CruiseSailing]:
        Norwegian._logger.debug("Search criteria we're passing to API:")
        Norwegian._logger.debug(json.dumps(api_search_filters, indent=4))

        return Norwegian._search_api_get_matching_itinerary_codes_and_package_ids(api_search_filters)


    @staticmethod
    def _search_api_get_matching_itinerary_codes_and_package_ids(
            api_search_filters: dict[str, str]) -> list[cruise_sailing.CruiseSailing]:

        itinerary_search_api_endpoint: str = "https://www.ncl.com/api/v2/vacations/search"

        search_api_query_params: dict[str, str | int] = api_search_filters

        # Clean up durations key, search API doesn't take tilde at the end of duration values
        if "durations" in search_api_query_params:
            duration_values: list[str] = str(search_api_query_params["durations"]).split(",")
            corrected_duration_values: list[str] = []
            known_duration_filters: list[str] = [
                "1-4",
                "5-8",
                "9-14",
                "15"
            ]
            for curr_candidate_duration in duration_values:
                Norwegian._logger.debug(f"Candidate duration: {curr_candidate_duration}")
                for known_filter in known_duration_filters:
                    if curr_candidate_duration.startswith(known_filter):
                        Norwegian._logger.debug(f"Candidate duration matched known: {known_filter}")
                        corrected_duration_values.append(known_filter)
                        break
                else:
                    raise ValueError(f"Unknown duration filter value: {curr_candidate_duration}")

            # Now that we have  leaned up all values for search, put them back in query params
            search_api_query_params["durations"] = ",".join(corrected_duration_values)

        # Add in extra params used during site reverse engineering
        search_api_query_params.update(
            {
                "filterConfig"  : "search-filters-configuration",
                "limit"         : 12,
                "offset"        : 0,
            }
        )

        Norwegian._logger.debug(
            f"Full list of parameter being passed to API endpoint {itinerary_search_api_endpoint}:")
        Norwegian._logger.debug(json.dumps(search_api_query_params, indent=4))

        query_headers: dict[str, str] = {
            # If we advertise we're Python requests, the CDN throws a 403 Access Denied; pretend to be Chrome on Win11
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/121.0.0.0 Safari/537.36",
        }

        time_start: float = time.perf_counter()
        search_results_response: requests.Response = requests.get(
            itinerary_search_api_endpoint, headers=query_headers, params=search_api_query_params)
        time_end: float = time.perf_counter()

        if not search_results_response.ok:
            raise ValueError(f"Querying Norwegian REST API endpoint {itinerary_search_api_endpoint} failed, "
                             f"code: {search_results_response.status_code}, "
                             f"error: {search_results_response.text}")

        Norwegian._logger.debug(f"API query returned in {time_end - time_start:.03f} seconds, "
                                f"returned {len(search_results_response.text):,} bytes")

        search_results: dict[str, typing.Any] = search_results_response.json()
        Norwegian._logger.debug(json.dumps(search_results, indent=4))

        return Norwegian._parse_search_api_response(search_results)


    @staticmethod
    def _parse_search_api_response(search_results: dict[str, typing.Any]) -> list[cruise_sailing.CruiseSailing]:
        # Example URL with JSON:
        # https://www.ncl.com/api/v2/vacations/search?destinations=CARIBBEAN&dates=Jan-2028&durations=15,9-14&filterConfig=search-filters-configuration&limit=100&offset=0

        itineraries: list[dict[str, typing.Any]] = search_results["itineraries"]

        query_headers: dict[str, str] = {
            # If we advertise we're Python requests, the CDN throws a 403 Access Denied; pretend to be Chrome on Win11
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/121.0.0.0 Safari/537.36",
        }

        parsed_sailings: list[cruise_sailing.CruiseSailing] = []
        for curr_sailing in itineraries:
            ship_code: _ShipCode = _ship_codes[curr_sailing["ship"]["code"]]

            sailing_details: dict[str, str | dict[str, str]] = {
                "unique_sailing"    : {
                    "code"              : curr_sailing["code"],
                    "package_id"        : curr_sailing["packageId"],
                },
                "itinerary_name"    : curr_sailing["title"],
                "ship"              : {
                    "code"              : ship_code,
                    "name"              : _ship_names[ship_code],
                }
            }

            Norwegian._logger.debug(f"Found sailing in search API result:")
            Norwegian._logger.debug(json.dumps(sailing_details, indent=4))

            # Hit separate API endpoint to get day-by_day intinerary
            day_details_api_endpoint: str = ( "https://www.ncl.com/api/vacation-builder/"  
                                             f"itinerary/{curr_sailing["code"]}/"
                                             f"package/{curr_sailing["packageId"]}/events")

            time_start: float = time.perf_counter()
            day_details_response: requests.Response = requests.get(
                day_details_api_endpoint, headers=query_headers)
            time_end: float = time.perf_counter()

            if not day_details_response.ok:
                raise RuntimeError(f"Querying Norwegian REST API endpoint {day_details_api_endpoint} failed, "
                                   f"code: {day_details_response.status_code}, "
                                   f"error: {day_details_response.text}")

            Norwegian._logger.debug(f"API query returned in {time_end - time_start:.03f} seconds, "
                                    f"returned {len(day_details_response.text):,} bytes")

            search_results: list[dict[str, typing.Any]] = day_details_response.json()
            Norwegian._logger.debug(json.dumps(search_results, indent=4))

            day_by_day_breakdown: list[cruise_day_detail.CruiseDayDetail] = \
                Norwegian._parse_search_api_response_day_details(search_results)

            start_date: datetime.date = day_by_day_breakdown[0].date
            end_date: datetime.date = day_by_day_breakdown[-1].date

            parsed_sailings.append(
                cruise_sailing.CruiseSailing(
                    cruise_lines.CruiseLineCode.NORWEGIAN,
                    ship_code,
                    _ship_names[ship_code],
                    _ship_classes[ship_code],
                    typing.cast(str, sailing_details["itinerary_name"]),
                    start_date,
                    end_date,
                    day_by_day_breakdown,
                )
            )

        parsed_sailings.sort()
        Norwegian._logger.info("Finished parsing search API results:")
        Norwegian._logger.info(json.dumps(parsed_sailings, indent=4, default=str))
        return parsed_sailings


    @staticmethod
    def _parse_search_api_response_day_details(
            search_results: list[dict[str, typing.Any]] ) -> list[cruise_day_detail.CruiseDayDetail]:

        sailing_day_breakdown: list[cruise_day_detail.CruiseDayDetail] = []

        supported_event_types: set = {
            "PORT",
            "AT_SEA",
        }

        required_port_info_keys = [
            "isTender",
            "isEmbarkation",
            "isDisembarkation",
            "isOverNight",
            "dailySchedule",
            "code",                     # Geospatial data: three letter IATA airport code
        ]

        for curr_day_idx, curr_day_detail in enumerate(search_results, start=1):
            Norwegian._logger.debug(f"Day index: {curr_day_idx}")

            Norwegian._logger.debug(json.dumps(curr_day_detail, indent=4))

            today_activities: list[cruise_day_detail.ShipActivity] = []

            # Walk today's events
            for event_idx, curr_event in enumerate(curr_day_detail["events"], start=1):
                Norwegian._logger.debug(json.dumps(curr_event, indent=4))
                # Make sure we have a date
                if "date" not in curr_event:
                    raise ValueError(f"Date not found in event: {json.dumps(curr_event, indent=4)}")

                event_datetime: datetime.datetime = datetime.datetime.fromisoformat(curr_event["date"])

                if not "eventType" in curr_event:
                    raise ValueError(f"Event type not found in event: {json.dumps(curr_event, indent=4)}")

                event_type: str = curr_event["eventType"]

                if event_type not in supported_event_types:
                    raise ValueError(f"Event type not supported: {event_type}")

                if event_type == "AT_SEA":
                    today_activities.append(
                        cruise_day_detail.ShipActivity(
                            cruise_day_detail.ActivityType.AT_SEA
                        )
                    )

                    sailing_day_breakdown.append(
                        cruise_day_detail.CruiseDayDetail(
                            # The most recent event is fine, they're all the same date
                            event_datetime.date(),
                            today_activities
                        )
                    )

                    # All we do that day
                    break

                elif event_type == "PORT":
                    # What KIND of port event?
                    port_info = curr_event["portInfo"]

                    # Validate port info
                    if len(port_info) != len(required_port_info_keys) or \
                            not all(key in port_info for key in required_port_info_keys):
                        raise ValueError(f"Not all required port info keys are present in port info: "
                                         f"{json.dumps(port_info, indent=4)}")

                    # Grab location and region
                    if "title" not in curr_event:
                        raise ValueError(f"Title not found in event: {json.dumps(curr_event, indent=4)}")

                    title_parts: list[str] = [item.strip() for item in curr_event["title"].split(",")]
                    if len(title_parts) < 2:
                        raise ValueError(f"Could not parse location out of: {curr_event["title"]}")
                    elif len(title_parts) == 2:
                        location_name, location_region = title_parts
                    elif len(title_parts) > 2:
                        # Put item N in region, everything else gets a comma and added to location name
                        location_name = ", ".join(title_parts[:-1])
                        location_region = title_parts[-1]

                    if port_info["isTender"]:
                        # Start time is in event time
                        start_time = event_datetime.time()

                        end_time: datetime.time | None
                        # If we aren't an overnight, parse end time out of daily schedule
                        if port_info["isOverNight"]:
                            today_activities.append(
                                cruise_day_detail.ShipActivity(
                                    cruise_day_detail.ActivityType.PORT_TENDERED_OVERNIGHT,
                                    activity_start_time=start_time,
                                    activity_location=cruise_day_detail.ShipActivityLocation(
                                        location_name, location_region
                                    )
                                )
                            )
                        else:
                            # 1. Split by the hyphen and grab the second part
                            end_time_str = port_info["dailySchedule"].split("-")[1].strip()

                            # 2. Parse the string using the 12-hour AM/PM format
                            parsed_datetime = datetime.datetime.strptime(end_time_str, "%I:%M %p")

                            # 3. Extract just the time object (results in 14:00:00)
                            end_time = parsed_datetime.time()

                            today_activities.append(
                                cruise_day_detail.ShipActivity(
                                    cruise_day_detail.ActivityType.PORT_TENDERED,
                                    activity_start_time=start_time,
                                    activity_end_time=end_time,
                                    activity_location=cruise_day_detail.ShipActivityLocation(
                                        location_name, location_region
                                    )
                                )
                            )

                    elif port_info["isEmbarkation"]:

                        today_activities.append(
                            cruise_day_detail.ShipActivity(
                                cruise_day_detail.ActivityType.PORT_EMBARK,
                                activity_end_time=event_datetime.time(),
                                activity_location=cruise_day_detail.ShipActivityLocation(
                                    location_name, location_region
                                )
                            )
                        )

                        sailing_day_breakdown.append(
                            cruise_day_detail.CruiseDayDetail(
                                # The most recent event is fine, they're all the same date
                                event_datetime.date(),
                                today_activities
                            )
                        )

                        break


                    elif port_info["isDisembarkation"]:
                        today_activities.append(
                            cruise_day_detail.ShipActivity(
                                cruise_day_detail.ActivityType.PORT_DEBARK,
                                activity_start_time=event_datetime.time(),
                                activity_location=cruise_day_detail.ShipActivityLocation(
                                    location_name, location_region
                                )
                            )
                        )

                        sailing_day_breakdown.append(
                            cruise_day_detail.CruiseDayDetail(
                                # The most recent event is fine, they're all the same date
                                event_datetime.date(),
                                today_activities
                            )
                        )

                        break

                    # it's just a normal port docking, nothing special
                    else:
                        # Start time is in event time
                        start_time = event_datetime.time()

                        end_time: datetime.time | None
                        if port_info["isOverNight"]:
                            today_activities.append(
                                cruise_day_detail.ShipActivity(
                                    cruise_day_detail.ActivityType.PORT_DOCKED_OVERNIGHT,
                                    activity_start_time=start_time,
                                    activity_location=cruise_day_detail.ShipActivityLocation(
                                        location_name, location_region
                                    )
                                )
                            )

                        else:
                            end_time_str = port_info["dailySchedule"].split("-")[1].strip()
                            parsed_datetime = datetime.datetime.strptime(end_time_str, "%I:%M %p")
                            end_time = parsed_datetime.time()

                            today_activities.append(
                                cruise_day_detail.ShipActivity(
                                    cruise_day_detail.ActivityType.PORT_DOCKED,
                                    activity_start_time=start_time,
                                    activity_end_time=end_time,
                                    activity_location=cruise_day_detail.ShipActivityLocation(
                                        location_name, location_region
                                    )
                                )
                            )

                # We've completed a day of activities
                sailing_day_breakdown.append(
                    cruise_day_detail.CruiseDayDetail(
                        # The most recent event is fine, they're all the same date
                        event_datetime.date(),
                        today_activities
                    )
                )

        return sailing_day_breakdown
