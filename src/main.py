# viber_auto_sender.py
import time
import logging
import sys
from viber_helper import ensure_viber_running, send_viber_message
from FlightRadar24 import FlightRadar24API
import datetime
import pandas as pd
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(".temp/app.log", mode="a"), logging.StreamHandler()],
)

GROUP_NAME = "Test group"
PHONE_NUMBER = "0913433867"
THRESHOLD_BEFORE_ARRIVAL_IN_MINS = 15
THRESHOLD_AFTER_DEPARTURE_IN_MINS = 30
MAX_ALTITUDE_BEFORE_LANDING_IN_FT = 15_000  # in feet

client = FlightRadar24API()

UTC = getattr(datetime, "UTC", datetime.timezone.utc)


def utc_now():
    return datetime.datetime.now(UTC)


class FlightNotificationTracker:
    def __init__(self):
        self.directory = ".temp"
        self.file_name = "notified_flights.txt"
        self.file_path = os.path.join(self.directory, self.file_name)

    def sync(self, available_registrations: list[str]):
        if available_registrations is None:
            return

        existing_values = self.get()
        updated_values = [
            value for value in existing_values if value in available_registrations
        ]

        tobe_removed = set(existing_values) - set(updated_values)
        if len(tobe_removed) > 0:
            for toberemoved in tobe_removed:
                logging.info(
                    "Removing notified flight %s as it is no longer available on FlightRadar24",
                    toberemoved,
                )

        self.save(updated_values)

    def get(self) -> list[str]:
        try:
            with open(self.file_path, "r") as f:
                value = f.read().strip()
                return [val for val in value.split(",") if val]
        except Exception:
            logging.exception("Unable to read notified flights")
            return []

    def track(self, values: list[str]) -> bool:
        existing_values = self.get()
        new_values = set(values) - set(existing_values)
        self.save(existing_values + list(new_values))
        if len(new_values) > 0:
            logging.info(
                "The flight registration(s): %s have been saved as the notifications have been sent.",
                ", ".join(new_values),
            )

    def save(self, values: list[str]):
        os.makedirs(self.directory, exist_ok=True)
        with open(self.file_path, "w") as f:
            f.write(",".join(values))


def get_flight_schedules():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    relative_path = os.path.join(script_dir, "../resources/Flightschedule.xlsx")
    abs_path = os.path.abspath(relative_path)

    excel_sheet = pd.read_excel(abs_path, sheet_name=0)
    results = []
    for i in range(len(excel_sheet)):
        registration = excel_sheet.iloc[i, 2]
        arrival_number = excel_sheet.iloc[i, 4]
        owner = excel_sheet.iloc[i, 13]
        arrival_owner = ", ".join(
            [x for x in ("" if pd.isna(owner) else owner).split(";") if x]
        )
        if isinstance(registration, str):
            results.append(
                {
                    "registration": registration,
                    "arrival_number": arrival_number,
                    "arrival_owner": arrival_owner,
                }
            )
    return results


def normalize_registration(registration: str) -> str:
    return registration.strip().replace("VN", "VN-")


class FlightFetcher:
    def __init__(self):
        self.flights = []
        self.last_fetched_flights = utc_now()
        self.client = FlightRadar24API()

    def get_tracking_flights(self):
        normalized_registrations = [
            normalize_registration(item["registration"])
            for item in get_flight_schedules()
        ]
        flights = self.client.get_flights(airline="HVN", details=False)
        matched_flights = [
            flight
            for flight in flights
            if flight.registration in normalized_registrations
            and flight.destination_airport_iata == "HAN"
        ]
        for flight in matched_flights:
            logging.info(
                "Matched flight: %s, Registration: %s, From: %s, To: %s, Altitude: %s ft",
                flight.callsign,
                flight.registration,
                flight.origin_airport_iata,
                flight.destination_airport_iata,
                flight.altitude,
            )
        return matched_flights


if __name__ == "__main__":
    logging.info("Starting service")
    try:
        flight_notification_tracker = FlightNotificationTracker()
        hwnd, win = ensure_viber_running()
        flight_fetcher = FlightFetcher()
        while True:
            flight_schedules = get_flight_schedules()
            flights = flight_fetcher.get_tracking_flights()
            flight_notification_tracker.sync(
                [flight.registration for flight in flights]
            )
            landing_flights = [
                flight
                for flight in flights
                if flight.altitude > 0
                and flight.altitude < MAX_ALTITUDE_BEFORE_LANDING_IN_FT
            ]
            if len(landing_flights) == 0:
                logging.info("No landing flight found. Retrying in 1 minute.")
                time.sleep(60 * 1)
                continue

            flight_descriptions = [
                f"Found {len(landing_flights)} flight(s) on FlightRadar24 based on the flight schedule.",
                "-------------------------------------------------------------------------------------",
            ]
            earliest_estimated_arrival_registration = None
            notified_flights = flight_notification_tracker.get()
            tracking_registrations = []
            for flight in landing_flights:
                if flight.registration in notified_flights:
                    logging.info(
                        "Flight %s - %s has been notified before. Skipping.",
                        flight.callsign,
                        flight.registration,
                    )
                    continue

                flights = client.get_flights(
                    airline="HVN", registration=flight.registration, details=True
                )
                descriptions = [
                    f"{flight.registration} registration not found on FlightRadar24 currently.",
                ]
                if len(flights) > 0:
                    flight = flights[0]
                    flight_schedule = next(
                        (
                            entry
                            for entry in flight_schedules
                            if normalize_registration(entry["registration"])
                            == flight.registration
                            and entry["arrival_number"] == flight.number
                        ),
                        None,
                    )

                    if not flight_schedule:
                        logging.info(
                            "Flight %s [registration=%s, arrival_number=%s] not found in flight schedule. Skipping notification.",
                            flight.callsign,
                            flight.registration,
                            flight.number
                        )
                        continue

                    descriptions = []
                    owner = flight_schedule["arrival_owner"]
                    if owner:
                        descriptions.append(f"{owner}")

                    descriptions = descriptions + [
                        f"Flight: *{flight.callsign}*",
                        f"Number: *{flight.number}*",
                        f"Registration: *{flight.registration}*",
                        f"From: *{flight.origin_airport_name}*, To: {flight.destination_airport_name}",
                        f"Altitude: *{flight.altitude}* ft, Speed: *{flight.ground_speed}* kts",
                    ]

                    real_departure_value = flight.time_details.get("real", {}).get(
                        "departure"
                    )
                    if not real_departure_value:
                        logging.info(
                            "Flight %s - %s has no real departure time. Skipping notification.",
                            flight.callsign,
                            flight.registration,
                        )
                        continue

                    now = datetime.datetime.now().replace(second=0, microsecond=0)
                    departure_datetime = datetime.datetime.fromtimestamp(
                        real_departure_value
                    )
                    departure_delta = now - departure_datetime.replace(
                        second=0, microsecond=0
                    )
                    departure_in_minutes, _ = divmod(
                        departure_delta.total_seconds(), 60
                    )
                    if departure_in_minutes < THRESHOLD_AFTER_DEPARTURE_IN_MINS:
                        minutes, _ = divmod(departure_delta.total_seconds(), 60)
                        logging.info(
                            "Flight %s - %s has departed in %s less than %s minutes (%s). Skipping notification.",
                            flight.callsign,
                            flight.registration,
                            departure_datetime.strftime("%Y-%m-%d %H:%M"),
                            THRESHOLD_AFTER_DEPARTURE_IN_MINS,
                            departure_in_minutes,
                        )
                        continue

                    estimated_arrival_time = flight.time_details.get(
                        "estimated", {}
                    ).get("arrival")
                    if not estimated_arrival_time:
                        logging.info(
                            "Flight %s - %s has no estimated arrival time. Skipping notification.",
                            flight.callsign,
                            flight.registration,
                        )
                        continue
                    estimated_arrival = datetime.datetime.fromtimestamp(
                        estimated_arrival_time
                    ).replace(second=0, microsecond=0)
                    remaining_seconds = int((estimated_arrival - now).total_seconds())
                    hours, remainder = divmod(remaining_seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    if minutes > THRESHOLD_BEFORE_ARRIVAL_IN_MINS:
                        logging.info(
                            "Flight %s - %s arrival in %02d hour(s) %02d minute(s), which is more than threshold %d minutes. Skipping notification.",
                            flight.callsign,
                            flight.registration,
                            hours,
                            minutes,
                            THRESHOLD_BEFORE_ARRIVAL_IN_MINS,
                        )
                        # continue

                    descriptions.append(
                        f"Estimate time arrival: *{estimated_arrival.strftime('%Y-%m-%d %H:%M')}*, Time remaining: *{minutes:02d} mins*"
                    )
                    print("\n".join(descriptions))
                    send_viber_message(GROUP_NAME, descriptions, True)
                    tracking_registrations.append(flight.registration)

            flight_notification_tracker.track(tracking_registrations)
            tracking_registrations.clear()
            logging.info("Sleeping for 1 min before next check...")
            time.sleep(60 * 1)
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting.")
        sys.exit(0)
    except Exception:
        logging.exception("Unhandled exception in main_loop.")
        sys.exit(1)
