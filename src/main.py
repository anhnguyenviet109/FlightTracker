# viber_auto_sender.py
import time
import logging
import sys
from viber_helper import ensure_viber_running, get_viber_window, send_to_group

SEND_INTERVAL = 60
GROUP_NAME = "Test group"
REGISTRATION = "VN-A323"

def main_loop():
    logging.info("Starting service")
    from FlightRadar24 import FlightRadar24API

    client = FlightRadar24API()
    try:
        # ensure Viber running
        hwnd, win = ensure_viber_running()
        while True:
            # double-check window still present
            hwnd, win = get_viber_window()
            if not hwnd:
                logging.warning("Viber window lost. Trying to start/connect again...")
                hwnd, win = ensure_viber_running()

            # Attempt to send
            try:
                flights = client.get_flights(
                    airline="HVN", registration=REGISTRATION, details=True
                )
                messages = [
                    f"{REGISTRATION} registration not found on FlightRadar24 currently."
                ]
                if len(flights) > 0:
                    flight = flights[0]
                    messages = [
                        f"Flight {flight.callsign}",
                        f"Registration {REGISTRATION}",
                        f"From: {flight.origin_airport_name}, To: {flight.destination_airport_name}",
                        f"Altitude: {flight.altitude} ft, Speed: {flight.ground_speed} kts",
                    ]

                send_to_group(win, GROUP_NAME, messages)
            except Exception as e:
                logging.exception("send_to_group exception: %s", e)

            # wait interval
            time.sleep(SEND_INTERVAL)
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting.")
        sys.exit(0)
    except Exception:
        logging.exception("Unhandled exception in main_loop.")
        sys.exit(1)


if __name__ == "__main__":
    main_loop()
