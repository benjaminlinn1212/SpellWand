"""Turn test: records the IMU while telling you when to turn it. Flash the imu_log build first.

    ~/.platformio/penv/bin/python tools/hardware_tests/guided_turns.py firmware/logs/turn_test.log

Then get the results from mac_app/ with: component_tests.py turns ../firmware/logs/turn_test.log
"""

import sys
import time
from pathlib import Path

from serial_port import open_board

PROMPTS = [  # 10 s per turn: reading the prompt while holding a breadboard takes a few seconds
    (0, "Pick it up gently by the edges and hold it level. First turn in 8 seconds."),
    (8, ">>> TURN 90 degrees around the X arrow NOW, then hold still"),
    (18, ">>> TURN 90 degrees around the Y arrow NOW, then hold still"),
    (28, ">>> TURN 90 degrees around the Z arrow NOW, then hold still"),
    (38, "Done. You can put it down."),
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
