"""Gesture Classifier: recognizes a GestureSequence by comparing it with stored examples.

Algorithm: Dynamic Time Warping (DTW) nearest neighbour with a rejection threshold.
"""

import math
from dataclasses import dataclass

import numpy as np

from motion_trace import gravity_in_wand

UNKNOWN = "UNKNOWN"
RESAMPLE_LENGTH = 40       # every gesture is stretched or squeezed to this many points
MIN_SAMPLES = 10           # anything shorter (0.1 s at 100 Hz) is not a gesture
MIN_ROTATION_RAD_S = 0.3   # average rotation below this (about 17 deg/s) = the wand barely moved
TRIM_FRACTION = 0.1        # trim start/end where rotation is under 10 % of the gesture's peak...
STILL_FLOOR_RAD_S = 0.2    # ...or under this, whichever is larger (sensor noise is far below it)
ACCEL_UNIT = 9.81          # m/s^2 per g
GYRO_UNIT = np.pi          # rad/s per half-turn-per-second


@dataclass
class GestureSequence:
    """One recorded gesture: a timestamp and IMU reading per MotionSample.

    t_ms:  shape (N,), milliseconds, increasing
    imu:   shape (N, 6), columns ax, ay, az (m/s^2) and gx, gy, gz (rad/s)
    label: the GestureLabel (e.g. "CIRCLE"), or None if not known yet
    """
    t_ms: np.ndarray
    imu: np.ndarray
    label: str | None = None


@dataclass
class GestureResult:
    """label: the recognized GestureLabel, or UNKNOWN if the best match was too far away.
    distance: DTW distance to the best match (lower = more similar).
    nearest_label: label of the best match even when rejected; handy for tuning the threshold.
    """
    label: str
    distance: float
    nearest_label: str | None


class GestureClassifier:
    """Nearest-neighbour DTW classifier with a rejection threshold.

    A gesture is accepted only if its distance to the closest stored example is at
    most `threshold`; otherwise the result is UNKNOWN. Change `threshold` at any time.
    """

    def __init__(self, threshold):
        self.threshold = threshold
        self._examples = []  # list of (label, preprocessed array)

    def fit(self, examples):
        """Store labelled GestureSequences to compare against. Replaces any previous examples."""
        for example in examples:
            if not example.label:
                raise ValueError("every training example needs a label")
            if len(example.t_ms) < MIN_SAMPLES:
                raise ValueError(f"{example.label} example has {len(example.t_ms)} samples; "
                                 f"need at least {MIN_SAMPLES}")
        self._examples = [(example.label, preprocess(example)) for example in examples]

    def classify(self, sequence):
        """Return a GestureResult for one GestureSequence."""
        best_label, best_distance = None, math.inf
        t = np.asarray(sequence.t_ms, dtype=float)
        start, end = active_span(sequence) if len(t) else (0.0, 0.0)
        inside = (t >= start) & (t <= end)
        moving_part = GestureSequence(t[inside], np.asarray(sequence.imu)[inside])
        if np.count_nonzero(inside) >= MIN_SAMPLES and wand_moved(moving_part):
            query = preprocess(sequence)
            for label, example in self._examples:
                # Divide by the length so the distance is an average per point.
                distance = dtw_distance(query, example) / RESAMPLE_LENGTH
                if distance < best_distance:
                    best_label, best_distance = label, distance

        accepted = best_label is not None and best_distance <= self.threshold
        return GestureResult(
            label=best_label if accepted else UNKNOWN,
            distance=best_distance,
            nearest_label=best_label,
        )


@dataclass
class ExampleCheck:
    """How one training example compares with all the other examples (see leave_one_out)."""
    index: int
    label: str
    nearest_label: str | None
    distance: float


def leave_one_out(examples):
    """Compare every labelled example with all the *other* examples. One whose nearest
    neighbour has a different label, or that is far from everything, is probably a
    bad recording worth deleting."""
    prepared = [preprocess(example) for example in examples]
    n = len(examples)
    distances = np.full((n, n), math.inf)
    for i in range(n):
        for j in range(i + 1, n):  # DTW distance is symmetric: compute each pair once
            distances[i, j] = distances[j, i] = dtw_distance(prepared[i], prepared[j]) / RESAMPLE_LENGTH
    checks = []
    for i, example in enumerate(examples):
        j = int(np.argmin(distances[i])) if n > 1 else None
        nearest = examples[j].label if j is not None else None
        checks.append(ExampleCheck(i, example.label, nearest, float(distances[i, j]) if j is not None else math.inf))
    return checks


def preprocess(sequence, length=RESAMPLE_LENGTH):
    """Turn a GestureSequence into a (length x 6) array ready for DTW.

    1. Subtract gravity from every accelerometer reading. Gravity only tells us how the
       wand happened to be tilted, and as the wand turns it shifts between the axes,
       which would make the same gesture look different at different tilts. We know
       which way is down at each moment by following the gyro (see motion_trace.py).
    2. Cut off the still time at the start and end (see active_span), e.g. the
       pause after pressing Start recording.
    3. Resample onto `length` evenly spaced moments between the first and last
       remaining timestamp, so fast and slow casts line up point by point.
    4. Convert to g and half-turns per second, where a typical gesture is about the
       same size on both sensors, so neither one drowns out the other.
    5. Scale the whole gesture to overall size 1, so big and small, fast and slow
       versions of the same gesture match. (This is why wand_moved() is needed:
       scaling would blow a tiny twitch up into a full-size shape.)
    """
    t = np.asarray(sequence.t_ms, dtype=float)
    imu = np.array(sequence.imu, dtype=float)  # a copy, so the caller's data is untouched
    imu[:, 0:3] -= gravity_in_wand(sequence)  # uses the whole recording: still parts show gravity best
    start, end = active_span(sequence)
    new_t = np.linspace(start, end, length)
    resampled = np.column_stack([np.interp(new_t, t, imu[:, k]) for k in range(imu.shape[1])])
    resampled[:, 0:3] /= ACCEL_UNIT
    resampled[:, 3:6] /= GYRO_UNIT
    size = _rms(resampled)
    return resampled / size if size > 0 else resampled


def active_span(sequence):
    """Times (start_ms, end_ms) of the part where the wand is moving, without the still
    time before and after it.

    The cut-off is a fraction of the gesture's own peak rotation speed, so the same
    gesture done faster, slower, bigger or smaller is trimmed at the same point of its
    motion. The exact moment is found by interpolating between samples.
    """
    t = np.asarray(sequence.t_ms, dtype=float)
    rate = np.linalg.norm(np.asarray(sequence.imu, dtype=float)[:, 3:6], axis=1)
    limit = max(STILL_FLOOR_RAD_S, TRIM_FRACTION * rate.max())
    moving = np.flatnonzero(rate > limit)
    if len(moving) == 0:
        return t[0], t[-1]
    first, last = moving[0], moving[-1]
    start = _crossing_time(t, rate, first - 1, first, limit) if first > 0 else t[0]
    end = _crossing_time(t, rate, last, last + 1, limit) if last < len(t) - 1 else t[-1]
    return start, end


def _crossing_time(t, rate, a, b, limit):
    """When the rotation speed passed `limit` between samples a and b (straight-line estimate)."""
    return t[a] + (limit - rate[a]) * (t[b] - t[a]) / (rate[b] - rate[a])


def wand_moved(sequence):
    """True if the wand rotated enough for this to possibly be a gesture."""
    gyro = np.asarray(sequence.imu, dtype=float)[:, 3:6]
    return _rms(gyro) >= MIN_ROTATION_RAD_S


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values))))


def dtw_distance(a, b, window=None):
    """Total cost of the best DTW alignment between sequences a (n x d) and b (m x d).

    Frames are compared with Euclidean distance; 1-D inputs are treated as d = 1.
    `window` is the Sakoe-Chiba band radius: a[i] may only align with b[j] when
    |i - j| <= window. None means no limit.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.ndim == 1:
        a = a[:, None]
    if b.ndim == 1:
        b = b[:, None]
    n, m = len(a), len(b)
    if window is None:
        window = max(n, m)
    window = max(window, abs(n - m))  # the band must still reach the last cell

    # cost[i, j] = distance between frame a[i] and frame b[j]
    cost = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)

    # acc[i, j] = cheapest way to align the first i frames of a with the first j of b
    acc = np.full((n + 1, m + 1), np.inf)
    acc[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(1, i - window), min(m, i + window) + 1):
            acc[i, j] = cost[i - 1, j - 1] + min(acc[i - 1, j], acc[i, j - 1], acc[i - 1, j - 1])
    return float(acc[n, m])
