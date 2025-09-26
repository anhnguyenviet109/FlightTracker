# viber_auto_sender.py
import subprocess
import time
import logging
import sys
from pywinauto import Application, findwindows, keyboard
import pygetwindow as gw
import ctypes
from ctypes import wintypes


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# === Config ===
VIBER_EXE_PATH = r"C:\Users\anhnv\AppData\Local\Viber\Viber.exe"  # <-- edit
GROUP_NAME = "Test group"
MESSAGE = "Automated message (test) ✅"
SEND_INTERVAL = 60  # seconds

# === Win32 helpers for bringing windows front/back more reliably ===
user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.restype = wintypes.HWND

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = (wintypes.HWND,)
SetForegroundWindow.restype = wintypes.BOOL

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
ShowWindow.restype = wintypes.BOOL

AttachThreadInput = user32.AttachThreadInput
AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
AttachThreadInput.restype = wintypes.BOOL

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
GetWindowThreadProcessId.restype = wintypes.DWORD

GetCurrentThreadId = kernel32.GetCurrentThreadId
GetCurrentThreadId.restype = wintypes.DWORD

SW_SHOW = 5
SW_RESTORE = 9

def bring_window_to_front(hwnd):
    """Try to reliably bring window hwnd to the foreground (may still fail due to OS rules)."""
    if not hwnd:
        return False
    try:
        foreground = GetForegroundWindow()
        tid_foreground = GetWindowThreadProcessId(foreground, None)
        tid_target = GetWindowThreadProcessId(hwnd, None)
        cur_tid = GetCurrentThreadId()

        # Attach threads so SetForegroundWindow will work
        AttachThreadInput(tid_foreground, cur_tid, True)
        AttachThreadInput(tid_target, cur_tid, True)

        ShowWindow(hwnd, SW_RESTORE)
        SetForegroundWindow(hwnd)

        # detach
        AttachThreadInput(tid_foreground, cur_tid, False)
        AttachThreadInput(tid_target, cur_tid, False)
        return True
    except Exception as e:
        logging.debug("bring_window_to_front failed: %s", e)
        return False

def get_viber_window():
    """Return the top-level hwnd and pywinauto window wrapper of Viber, or (None, None)."""
    # try to find an open Viber window by title containing "Viber"
    try:
        wins = findwindows.find_windows(title_re=".*Rakuten Viber.*")
        if not wins:
            return None, None
        hwnd = wins[0]
        # connect via pywinauto
        app = Application(backend="uia").connect(handle=hwnd)
        window = app.window(handle=hwnd)
        return hwnd, window
    except Exception as e:
        logging.debug("get_viber_window exception: %s", e)
        return None, None

def start_viber():
    logging.info("Starting Viber...")
    subprocess.Popen(VIBER_EXE_PATH)
    # wait for window to appear
    for i in range(30):
        hwnd, win = get_viber_window()
        if hwnd:
            logging.info("Viber window detected.")
            return hwnd, win
        time.sleep(1)
    raise RuntimeError("Viber window did not appear in time. Check VIBER_EXE_PATH and that Viber can start.")

def send_to_group(window, group_name, messages):
    """
    Steps:
    1) Focus the search input,
    2) Type the group name,
    3) Click the first result in the sidebar (by coordinates),
    4) Type the message and send.
    """
    from pywinauto import keyboard
    import time

    # Save current foreground
    try:
        window.set_focus()
    except Exception:
        pass

    search_box = window.child_window(control_type="Edit", found_index=0)
    search_box.click_input()
    keyboard.send_keys("^a")
    keyboard.send_keys("{DEL}")

    # --- Step 2: Type the group name ---
    keyboard.send_keys(group_name, with_spaces=True, pause=0.05)
    time.sleep(1)  # wait for results to show

    # --- Step 3: Click the first conversation result ---
    rect = window.rectangle()
    x = 60
    y = 200
    window.click_input(coords=(x, y))
    time.sleep(1)  # wait for chat to open

    # 
    x = 400
    y = 200
    window.click_input(coords=(x, y))
    time.sleep(0.8)  # wait for chat to open

    # clear unsent message
    keyboard.send_keys("^a")
    keyboard.send_keys("{DEL}")

    # send the message
    for message in messages:
        keyboard.send_keys(message, with_spaces=True, pause=0.05)
        keyboard.send_keys("+{ENTER}")
    keyboard.send_keys("{ENTER}")
    print(f"✅ Sent message to group: {group_name}")

def ensure_viber_running():
    hwnd, win = get_viber_window()
    if hwnd and win:
        return hwnd, win
    return start_viber()

def main_loop():
    logging.info("Starting main loop. Press Ctrl+C to stop.")
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
                flights = client.get_flights(airline="HVN", registration="VN-A331", details=True)
                messages = ["VN-A331 registration not found on FlightRadar24 currently."]
                if len(flights) > 0:
                    flight = flights[0]
                    messages = [f"Flight {flight.callsign}", f"From: {flight.origin_airport_name}, To: {flight.destination_airport_name}", f"Altitude: {flight.altitude} ft, Speed: {flight.ground_speed} kts"]

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

    