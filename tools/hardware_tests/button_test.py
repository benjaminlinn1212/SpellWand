"""Button test: 20 presses. Waits for each press, and checks it gives one CAST_START and one
CAST_END. Flash the wand firmware first.

    ~/.platformio/penv/bin/python tools/hardware_tests/button_test.py firmware/logs/button_test.log
"""

import sys
import time
from pathlib import Path

import serial

from serial_port import open_board

TARGET = 20
Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
log = open(sys.argv[1], "w")
port = open_board(timeout=0.05)


def next_line():
    try:
        text = port.readline().decode(errors="replace").strip()
    except serial.SerialException:
        print(f"\nUSB DISCONNECTED during the test. Good presses so far: {good}. Result: not finished.", flush=True)
        sys.exit(1)
    if text:
        log.write(text + "\n")
        log.flush()
    return text


good = 0
started_early = 0
settle = time.time()
while time.time() - settle < 3:  # let the board finish starting
    if next_line().startswith("CAST_START"):
        started_early += 1
if started_early:
    print("A cast started with nobody pressing: check the button wiring.", flush=True)

holds = []
for press in range(1, TARGET + 1):
    print(f"Press {press} of {TARGET}: PRESS when ready, hold about 1 second, let go", flush=True)
    starts = ends = 0
    limit = time.time() + 180
    pressed_at = None
    while time.time() < limit:
        text = next_line()
        if text.startswith("CAST_START"):
            starts += 1
            pressed_at = time.time()
            print("   pressed: LED should be BLUE", flush=True)
        elif text.startswith("CAST_END"):
            ends += 1
            held = time.time() - (pressed_at or time.time())
            holds.append(held)
            print(f"   let go after {held:.1f} s: AMBER, then 2 MAGENTA flashes", flush=True)
        elif text == "State: IDLE" and ends:
            break
    else:
        print("   Stopped: no press for 3 minutes.", flush=True)
        break
    if starts == 1 and ends == 1:
        good += 1
    else:
        print(f"   PROBLEM: {starts} starts, {ends} ends", flush=True)
port.close()
print(f"\nPresses with exactly one start and one end: {good} of {TARGET}")
if holds:
    print(f"Hold times: shortest {min(holds):.1f} s, longest {max(holds):.1f} s")
print("Result:", "PASS" if good == TARGET and not started_early else "FAIL")
