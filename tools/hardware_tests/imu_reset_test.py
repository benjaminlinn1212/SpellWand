"""Checks that the wand gets its readings back by itself after the IMU resets.

Needs the imu_log build, which prints every reading and resets the IMU when it is sent the
letter r. Run these from the top of the project:

    ~/.platformio/penv/bin/pio run -d firmware -e imu_log -t upload
    ~/.platformio/penv/bin/python tools/hardware_tests/imu_reset_test.py

Nothing to touch: leave the wand lying still.
"""

import sys
import time

from serial_port import open_board

SETTLE_S = 1.0  # what arrives right after the port opens is thrown away
BEFORE_S = 3.0  # readings are counted for this long before the reset
WATCH_S = 8.0  # and watched for this long after it
LAST_S = 3.0  # the rate "after" is taken over the end of that time
MIN_RATE = 90.0  # readings per second that count as working (the wand sends 100)


def reading_time_ms(line):
    """The wand's own clock from an `IMU,<ms>,...` line, or None for any other line."""
    parts = line.split(",")
    if len(parts) != 8 or parts[0] != "IMU" or not parts[1].isdigit():
        return None
    return int(parts[1])


def watch(port, seconds, on_line):
    """Calls on_line(seconds since the start, text) for every whole line until the time is up."""
    start = time.time()
    pending = b""
    while time.time() - start < seconds:
        pending += port.read(4096)
        *lines, pending = pending.split(b"\n")
        for raw in lines:
            on_line(time.time() - start, raw.decode("utf-8", "replace").strip())


def main():
    port = open_board(timeout=0.05)
    watch(port, SETTLE_S, lambda at, line: None)

    before = set()  # a set, so a repeated line is counted once

    def count_before(at, line):
        ms = reading_time_ms(line)
        if ms is not None:
            before.add(ms)

    watch(port, BEFORE_S, count_before)
    print(f"Before the reset: {len(before) / BEFORE_S:.0f} readings per second")
    if len(before) / BEFORE_S < MIN_RATE:
        port.close()
        sys.exit("STOPPED: the wand is not sending readings. Upload the imu_log build, or restart the wand.")

    after = set()
    late = set()  # readings in the last LAST_S seconds
    messages = []

    def follow(at, line):
        ms = reading_time_ms(line)
        if ms is not None:
            after.add(ms)
            if at >= WATCH_S - LAST_S:
                late.add(ms)
        elif line and line not in messages:
            messages.append(line)
            print(f"  {at:4.1f} s  {line[:100]}")

    port.write(b"r")
    print("Sent the reset. The wand printed:")
    watch(port, WATCH_S, follow)
    port.close()

    rate = len(late) / LAST_S
    print(f"After the reset: {rate:.0f} readings per second")
    if rate < MIN_RATE:
        print("FAIL: the readings did not come back.")
        sys.exit(1)
    times = sorted(before | after)
    gap_s = max(b - a for a, b in zip(times, times[1:])) / 1000.0
    print(f"PASS: the readings came back by themselves, after {gap_s:.2f} s without any.")


if __name__ == "__main__":
    main()
