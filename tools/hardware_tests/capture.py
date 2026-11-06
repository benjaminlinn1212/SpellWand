"""Saves what the ESP32 prints to a file for a set time.

    ~/.platformio/penv/bin/python tools/hardware_tests/capture.py <log file> <seconds> [--restart]

--restart restarts the board first, so the log includes its boot messages.
"""

import argparse
import time
from pathlib import Path

from serial_port import open_board


def main():
    parser = argparse.ArgumentParser(description="Save what the ESP32 prints.")
    parser.add_argument("log")
    parser.add_argument("seconds", type=float)
    parser.add_argument("--restart", action="store_true", help="restart the board first")
    args = parser.parse_args()

    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    port = open_board()
    if args.restart:
        port.setDTR(False)
        port.setRTS(True)
        time.sleep(0.1)
        port.setRTS(False)
    end = time.time() + args.seconds
    with open(args.log, "wb") as f:
        while time.time() < end:
            f.write(port.read(4096))
    port.close()
    print("Saved", args.log)


if __name__ == "__main__":
    main()
