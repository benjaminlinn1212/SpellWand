"""Turn test: records the IMU while telling you when to turn it. Flash the imu_log build first.

    ~/.platformio/penv/bin/python tools/hardware_tests/guided_turns.py firmware/logs/turn_test.log

Then get the results from mac_app/ with: component_tests.py turns ../firmware/logs/turn_test.log
"""

import sys
import time
from pathlib import Path

from serial_port import open_board

PROMPTS = [
    (0, "Pick it up gently by the edges and hold it level. First turn in 6 seconds."),
    (6, ">>> TURN 90 degrees around the X arrow NOW"),
    (9, "    hold still..."),
    (13, ">>> TURN 90 degrees around the Y arrow NOW"),
    (16, "    hold still..."),
    (20, ">>> TURN 90 degrees around the Z arrow NOW"),
    (23, "    hold still..."),
    (27, "Done. You can put it down."),
]


def main():
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    port = open_board(timeout=0.05)
    start = time.time()
    waiting = list(PROMPTS)
    with open(sys.argv[1], "wb") as f:
        while waiting:
            if time.time() - start >= waiting[0][0]:
                print(waiting.pop(0)[1], flush=True)
            f.write(port.read(4096))
    port.close()


if __name__ == "__main__":
    main()
