"""Sample Recorder: saves labelled GestureSequences as CSV files and manages the dataset.

Each sample is one CSV file in data/, named <LABEL>_<date>-<time>.csv, with one row
per MotionSample:

    t_ms, ax, ay, az, gx, gy, gz, label

Open them in any spreadsheet to inspect them; delete bad ones with delete_sample()
(the SpellWand UI will do this for you later).
"""

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from classifier import GestureSequence

DATA_DIR = Path(__file__).parent / "data"
COLUMNS = ["t_ms", "ax", "ay", "az", "gx", "gy", "gz", "label"]

# Labels and sample ids end up in file names, and later arrive from the web UI,
# so only allow plain names: nothing like "../" can escape the data folder.
LABEL_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")
SAMPLE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


@dataclass
class SampleInfo:
    """Summary of one saved sample, for listing the dataset."""
    sample_id: str
    label: str
    n_samples: int
    duration_ms: float


def save_sample(sequence, data_dir=DATA_DIR):
    """Write one labelled GestureSequence to a new CSV file and return its sample_id."""
    label = sequence.label
    if not isinstance(label, str) or not LABEL_PATTERN.fullmatch(label):
        raise ValueError(f"label must be uppercase letters, digits and _ (like CIRCLE), got {label!r}")

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    sample_id = f"{label}_{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"

    # Mode "x" refuses to overwrite an existing file.
    with open(data_dir / f"{sample_id}.csv", "x", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for t, values in zip(sequence.t_ms, sequence.imu):
            writer.writerow([float(t), *(float(v) for v in values), label])
    return sample_id


def load_sample(sample_id, data_dir=DATA_DIR):
    """Read one saved sample back as a GestureSequence."""
    with open(_sample_path(sample_id, data_dir), newline="") as f:
        rows = list(csv.DictReader(f))
    t_ms = np.array([float(row["t_ms"]) for row in rows])
    imu = np.array([[float(row[c]) for c in COLUMNS[1:7]] for row in rows]).reshape(-1, 6)
    label = rows[0]["label"] if rows else None
    return GestureSequence(t_ms=t_ms, imu=imu, label=label)


def load_dataset(data_dir=DATA_DIR):
    """Every saved sample, ready for GestureClassifier.fit()."""
    return [load_sample(sample_id, data_dir) for sample_id in _sample_ids(data_dir)]


def list_samples(data_dir=DATA_DIR):
    """A SampleInfo for every saved sample, sorted by label and then time."""
    infos = []
    for sample_id in _sample_ids(data_dir):
        s = load_sample(sample_id, data_dir)
        duration = float(s.t_ms[-1] - s.t_ms[0]) if len(s.t_ms) else 0.0
        infos.append(SampleInfo(sample_id, s.label, len(s.t_ms), duration))
    return infos


def delete_sample(sample_id, data_dir=DATA_DIR):
    """Remove one saved sample. Raises FileNotFoundError if it does not exist."""
    _sample_path(sample_id, data_dir).unlink()


def _sample_ids(data_dir):
    paths = sorted(Path(data_dir).glob("*.csv"))
    return [p.stem for p in paths if SAMPLE_ID_PATTERN.fullmatch(p.stem)]


def _sample_path(sample_id, data_dir):
    if not isinstance(sample_id, str) or not SAMPLE_ID_PATTERN.fullmatch(sample_id):
        raise ValueError(f"invalid sample id {sample_id!r}")
    return Path(data_dir) / f"{sample_id}.csv"
