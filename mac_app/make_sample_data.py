"""Regenerate sample_data/: a small simulated dataset for demos and tests.

    .venv/bin/python make_sample_data.py

The samples are simulated (see simulator.py), not real recordings. `app.py --simulate`
starts from them; real training data goes to data/ instead.
"""

import shutil
from pathlib import Path

import numpy as np

from recorder import save_sample
from simulator import GESTURES, make_gesture

SAMPLE_DATA_DIR = Path(__file__).parent / "sample_data"
EXAMPLES_PER_GESTURE = 6
SEED = 2026  # fixed, so the files only change if the simulator changes


def main():
    if SAMPLE_DATA_DIR.exists():
        shutil.rmtree(SAMPLE_DATA_DIR)
    rng = np.random.default_rng(SEED)
    for gesture in GESTURES:
        for _ in range(EXAMPLES_PER_GESTURE):
            save_sample(make_gesture(gesture, rng), SAMPLE_DATA_DIR)
    print(f"Wrote {EXAMPLES_PER_GESTURE * len(GESTURES)} simulated samples to {SAMPLE_DATA_DIR}")


if __name__ == "__main__":
    main()
