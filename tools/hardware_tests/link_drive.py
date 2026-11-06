"""Bluetooth link test without a button: the Mac asks for 20 recordings, and each runs to the
wand's 5 s limit. Flash the wand firmware first, and run this in a terminal allowed to use Bluetooth:

    mac_app/.venv/bin/python -u tools/hardware_tests/link_drive.py

Then get the results from mac_app/ with: component_tests.py link link_test.log
"""

import sys
import threading
import time
from pathlib import Path

MAC_APP = Path(__file__).resolve().parents[2] / "mac_app"
sys.path.insert(0, str(MAC_APP))

from ble_manager import BleWandLink
from protocol import CastEnd, decode_event, encode_start_recording

RECORDINGS = 20
LOG = MAC_APP / "link_test.log"


def main():
    link = BleWandLink()
    ended = threading.Event()
    log = open(LOG, "w")

    def on_event(data):
        event = decode_event(data)
        print(event, file=log, flush=True)
        if isinstance(event, CastEnd):
            ended.set()

    link.on_event = on_event
    link.on_disconnect = lambda: print("Wand disconnected", file=log, flush=True)
    print("Connecting...", flush=True)
    started = time.time()
    link.connect()
    print(f"Connected in {time.time() - started:.1f} s", flush=True)
    for number in range(1, RECORDINGS + 1):
        ended.clear()
        link.send(encode_start_recording())
        print(f"Recording {number}: {'done' if ended.wait(8) else 'NO CAST_END'}", flush=True)
        time.sleep(0.5)
    link.disconnect()
    print(f"Finished. Log saved to {LOG}", flush=True)


if __name__ == "__main__":
    main()
