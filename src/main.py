# viber_auto_sender.py
import time
import logging
import sys
from viber_helper import ensure_viber_running, send_viber_message
from FlightRadar24 import FlightRadar24API
import datetime
import pandas as pd
import os
import random

GROUP_NAME = "Test group"
PHONE_NUMBER = "0913433867"
THRESHOLD_BEFORE_ARRIVAL_IN_MINS = 15
FLIGHT_DATA_EXPIRATION = 30

client = FlightRadar24API()

UTC = getattr(datetime, "UTC", datetime.timezone.utc)


def utc_now():
    return datetime.datetime.now(UTC)


class EstimatedArrivalTimeManager:
    def __init__(self):
        self.directory = ".temp"
        self.file_name = "estimated_arrival.txt"
        self.file_path = os.path.join(self.directory, self.file_name)

    def get(self) -> datetime:
        try:
            with open(self.file_path, "r") as f:
                value = f.read().strip()
                iso_date_time = datetime.datetime.fromisoformat(value)
                logging.info("Loaded estimated arrival date time %s", value)
                return iso_date_time
        except Exception:
            logging.exception("Unable to parse estimated arrival date time")

        logging.info(
            "Not found '%s', fallback to default estimated arrival date time",
            self.file_path,
        )
        return utc_now() + datetime.timedelta(hours=12)

    def save(self, value: datetime):
        now = utc_now()
        valid_estimated = now if value < now else value
        os.makedirs(self.directory, exist_ok=True)
        with open(self.file_path, "w") as f:
            f.write(valid_estimated.isoformat())


def get_registrations_from_excel():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    relative_path = os.path.join(script_dir, "../resources/Flight schedule.xlsx")
    abs_path = os.path.abspath(relative_path)

    excel_sheet = pd.read_excel(abs_path, sheet_name=0)
    return [
        item.replace("VN", "VN-")
        for item in excel_sheet.iloc[:, 1].tolist()
        if isinstance(item, str) and item.startswith("VN")
    ]


class FlightFetcher:
    def __init__(self):
        self.flights = []
        self.last_fetched_flights = utc_now()
        self.client = FlightRadar24API()

    def get_tracking_flights(self):
        """
        Refetch flights after 30 minutes to get the latest updates
        """
        now = utc_now()
        should_fetch = (
            (
                self.last_fetched_flights
                < now - datetime.timedelta(minutes=FLIGHT_DATA_EXPIRATION)
            )
            if len(self.flights) > 0
            else now - datetime.timedelta(minutes=5)
        )
        if not should_fetch:
            return self.flights

        self.flights = [
            flight
            for flight in self.client.get_flights(airline="HVN", details=False)
            if flight.registration in get_registrations_from_excel()
            and flight.altitude > 0 and flight.altitude < 10_000
        ]
        self.last_fetched_flights = now
        return self.flights


if __name__ == "__main__":
    logging.info("Starting service")
    try:
        hwnd, win = ensure_viber_running()
        flight_fetcher = FlightFetcher()
        estimated_arrival_time_manager = EstimatedArrivalTimeManager()
        while True:
            min_estimated_arrival_date_time = estimated_arrival_time_manager.get()
            if (
                utc_now() < min_estimated_arrival_date_time
                and len(flight_fetcher.flights) > 0
            ):
                sleep_in_seconds = random.randint(10, 15)
                logging.info(
                    "Wait until %s for tracking before landing. Sleep in %s seconds",
                    min_estimated_arrival_date_time,
                    sleep_in_seconds,
                )
                time.sleep(sleep_in_seconds)
                continue

            tracking_flights = flight_fetcher.get_tracking_flights()
            flight_descriptions = [
                f"Found {len(tracking_flights)} flight(s) on FlightRadar24 based on the flight schedule.",
                "-------------------------------------------------------------------------------------",
            ]
            earliest_estimated_arrival_registration = None
            for flight in tracking_flights:
                flights = client.get_flights(
                    airline="HVN", registration=flight.registration, details=True
                )
                descriptions = [
                    f"{flight.registration} registration not found on FlightRadar24 currently.",
                ]
                if len(flights) > 0:
                    flight = flights[0]
                    descriptions = [
                        f"Flight {flight.callsign}",
                        f"Registration {flight.registration}",
                        f"From: {flight.origin_airport_name}, To: {flight.destination_airport_name}",
                        f"Altitude: {flight.altitude} ft, Speed: {flight.ground_speed} kts",
                    ]
                    estimated_arrival_time = flight.time_details.get(
                        "estimated", {}
                    ).get("arrival")
                    if not estimated_arrival_time:
                        descriptions.append("Estimate time arrival is not found.")
                        continue

                    eta = datetime.datetime.fromtimestamp(
                        estimated_arrival_time
                    ).replace(tzinfo=datetime.UTC)
                    if eta <= min_estimated_arrival_date_time:
                        min_estimated_arrival_date_time = eta
                        earliest_estimated_arrival_registration = flight.registration

                    remaining = eta - utc_now()
                    total_seconds = int(remaining.total_seconds())
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    descriptions.append(
                        f"Estimate time arrival: {eta.strftime('%Y-%m-%d %H:%M:%S UTC')}, Time remaining: {hours:02d}:{minutes:02d}"
                    )
                flight_descriptions += descriptions
                flight_descriptions.append(
                    "-------------------------------------------------------------------------------------"
                )

            estimated_arrival_time_manager.save(
                min_estimated_arrival_date_time
                - datetime.timedelta(minutes=THRESHOLD_BEFORE_ARRIVAL_IN_MINS)
            )
            flight_descriptions.append(
                f"* Earliest estimated arrival: {earliest_estimated_arrival_registration} - {min_estimated_arrival_date_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            flight_descriptions.append(
                f"* Will be back to update until {min_estimated_arrival_date_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )

            print("\n".join(flight_descriptions))
            # send_viber_message(GROUP_NAME, flight_descriptions, True)
            # send_viber_message(PHONE_NUMBER, flight_descriptions, True)
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting.")
        sys.exit(0)
    except Exception:
        logging.exception("Unhandled exception in main_loop.")
        sys.exit(1)
