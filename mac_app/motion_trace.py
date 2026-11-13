"""Motion trace: where the wand tip went during a GestureSequence, for 3D display.

Same idea as the TensorFlow Lite Micro "magic wand" example. Integrating the
accelerometer twice to get position drifts badly within a second, so instead we track
which way the wand is *pointing*:
  1. The wand starts at rest, so the first accelerometer readings show which way is
     up. That gives the starting tilt.
  2. Each gyroscope reading says how far the wand turned since the previous sample.
     Applying these small turns one after another tracks its orientation.
  3. The tip is one wand length along the wand's x axis.

Axes: wand x = along the wand toward the tip, y = left, z = up. World axes match the
wand's when it is held level and pointing forward. (These sensors cannot tell which
compass direction the wand faced, so "forward" is simply wherever it started.)
"""

import numpy as np

WAND_LENGTH_M = 0.3
GRAVITY_SAMPLES = 5  # average this many samples at the start to find "up"


def tip_trace(sequence, wand_length_m=WAND_LENGTH_M):
    """Return an (N x 3) array: the wand tip position in metres, relative to the hand,
    for every MotionSample."""
    return orientations(sequence) @ np.array([wand_length_m, 0.0, 0.0])


class LiveTipTrace:
    """The same trace as tip_trace, worked out one MotionSample at a time, so the UI can
    draw the path while the cast is still going on."""

    def __init__(self, wand_length_m=WAND_LENGTH_M):
        self._tip_in_wand = np.array([wand_length_m, 0.0, 0.0])
        self._turned = np.eye(3)   # how the wand has turned since its first sample
        self._previous = None      # time (s) and gyro reading of the sample before
        self._tilt = None          # the starting tilt, once enough samples show which way is up
        self._waiting = []         # until then: (turned, accelerometer reading) of each sample

    def add(self, t_ms, imu):
        """Take the next MotionSample (imu = ax, ay, az, gx, gy, gz) and return the tip
        positions that are now known: none for the first few samples, which are needed to
        find "up", then those samples' positions all at once, then one per sample."""
        imu = np.asarray(imu, dtype=float)
        t_s = float(t_ms) / 1000.0
        if self._previous is not None:
            previous_t_s, previous_gyro = self._previous
            self._turned = self._turned @ _rotation(0.5 * (previous_gyro + imu[3:6]) * (t_s - previous_t_s))
        self._previous = (t_s, imu[3:6])

        if self._tilt is not None:
            return [self._tilt @ self._turned @ self._tip_in_wand]
        self._waiting.append((self._turned, imu[0:3]))
        if len(self._waiting) < GRAVITY_SAMPLES:
            return []
        self._tilt = _tilt_from_gravity(np.mean([turned @ accel for turned, accel in self._waiting], axis=0))
        points = [self._tilt @ turned @ self._tip_in_wand for turned, _ in self._waiting]
        self._waiting = []
        return points


def gravity_in_wand(sequence):
    """Return an (N x 3) array: what gravity alone would make the accelerometer read at
    each MotionSample, given how the wand was turned at that moment. Subtracting this
    leaves only the wand's own acceleration."""
    accel = np.asarray(sequence.imu, dtype=float)[:GRAVITY_SAMPLES, 0:3]
    up_in_world = np.array([0.0, 0.0, np.linalg.norm(accel, axis=1).mean()])
    # Transposing an orientation turns world directions into wand directions.
    return orientations(sequence).transpose(0, 2, 1) @ up_in_world


def orientations(sequence):
    """Return an (N x 3 x 3) array: the wand's orientation (wand axes -> world axes) at
    every MotionSample, starting from the tilt shown by gravity and following the gyro."""
    imu = np.asarray(sequence.imu, dtype=float)
    t_s = np.asarray(sequence.t_ms, dtype=float) / 1000.0

    # How the wand turned relative to its first sample, from the gyro alone.
    relative = np.empty((len(imu), 3, 3))
    turned = np.eye(3)
    for k in range(len(imu)):
        if k > 0:
            # Turn by the average rotation rate over the time since the previous sample.
            rate = 0.5 * (imu[k - 1, 3:6] + imu[k, 3:6])
            turned = turned @ _rotation(rate * (t_s[k] - t_s[k - 1]))
        relative[k] = turned

    # Starting tilt: average the first few gravity readings, each turned back into the
    # wand's starting axes first, because the wand may already be moving.
    n = min(GRAVITY_SAMPLES, len(imu))
    starting_gravity = np.mean([relative[k] @ imu[k, 0:3] for k in range(n)], axis=0)
    return _tilt_from_gravity(starting_gravity) @ relative


def _tilt_from_gravity(accel):
    """Orientation (wand -> world) of a wand at rest whose accelerometer reads `accel`."""
    if np.linalg.norm(accel) < 1e-9:
        return np.eye(3)  # no gravity reading at all: nothing to go on, assume level
    up = accel / np.linalg.norm(accel)
    # Smallest rotation that turns the measured "up" onto the world's z axis.
    axis = np.cross(up, [0.0, 0.0, 1.0])
    if np.linalg.norm(axis) < 1e-12:
        return np.eye(3) if up[2] > 0 else np.diag([1.0, -1.0, -1.0])  # level, or upside down
    angle = np.arctan2(np.linalg.norm(axis), up[2])
    return _rotation(axis / np.linalg.norm(axis) * angle)


def _rotation(rotation_vector):
    """Rotation matrix for turning |v| radians about the axis v (Rodrigues' formula)."""
    angle = np.linalg.norm(rotation_vector)
    if angle < 1e-12:
        return np.eye(3)
    kx, ky, kz = rotation_vector / angle
    k = np.array([[0.0, -kz, ky], [kz, 0.0, -kx], [-ky, kx, 0.0]])
    return np.eye(3) + np.sin(angle) * k + (1.0 - np.cos(angle)) * (k @ k)
