"""Simulated IMU recordings so the Gesture Classifier can be tested without the wand.

The wand tip traces a path in the vertical plane in front of you (y = right, z = up).
From that path we roughly estimate what the IMU would feel:
  accelerometer = the tip's acceleration + gravity (tilted by how the wand is held)
  gyroscope     = rotation needed to swing the tip (tip speed / wand length)
Every call adds random variation: size, duration, uneven pacing, tilt, timing jitter
and sensor noise. Real recordings will be messier; this is only a sanity check.
"""

import numpy as np

from classifier import GestureSequence

GESTURES = ("CIRCLE", "ZIGZAG", "HORIZONTAL_LINE")
SAMPLE_RATE_HZ = 100
WAND_LENGTH_M = 0.3
GRAVITY = 9.81


def _tip_path(gesture, s):
    """Tip position (y, z) in metres for progress s from 0 to 1."""
    if gesture == "CIRCLE":
        return 0.15 * np.cos(2 * np.pi * s), 0.15 * np.sin(2 * np.pi * s)
    if gesture == "ZIGZAG":
        # left-right-left-right strokes while drifting downward
        return -0.15 * np.cos(3 * np.pi * s), 0.1 - 0.2 * s
    if gesture == "HORIZONTAL_LINE":
        return -0.15 * np.cos(np.pi * s), np.zeros_like(s)
    raise ValueError(f"unknown gesture {gesture}")


def _sample_times(rng, duration_s):
    """Timestamps in seconds at ~100 Hz with a little jitter, like real BLE samples."""
    n = int(duration_s * SAMPLE_RATE_HZ)
    t = np.arange(n) / SAMPLE_RATE_HZ + rng.uniform(-0.002, 0.002, n)
    t[0] = 0.0
    return np.sort(t)


def _random_gravity(rng):
    """Gravity as seen by the IMU when the wand is held up to 20 degrees off level."""
    pitch, roll = np.radians(rng.uniform(-20, 20, 2))
    return GRAVITY * np.array([-np.sin(pitch), np.cos(pitch) * np.sin(roll), np.cos(pitch) * np.cos(roll)])


def _to_sequence(t_s, imu, rng, label):
    imu = imu.copy()
    imu[:, 0:3] += _random_gravity(rng)
    imu[:, 0:3] += rng.normal(0, 0.3, (len(t_s), 3))   # accelerometer noise, m/s^2
    imu[:, 3:6] += rng.normal(0, 0.05, (len(t_s), 3))  # gyroscope noise, rad/s
    return GestureSequence(t_ms=t_s * 1000, imu=imu, label=label)


def make_gesture(gesture, rng):
    """One simulated recording of `gesture`, labelled with it."""
    duration = rng.uniform(0.8, 1.4)
    t = _sample_times(rng, duration)

    # Progress along the path: uneven pacing, then smooth start and stop (at rest at both ends).
    tau = (t / t[-1]) ** rng.uniform(0.8, 1.25)
    s = 10 * tau**3 - 15 * tau**4 + 6 * tau**5

    size = rng.uniform(0.8, 1.2)
    y, z = (size * p for p in _tip_path(gesture, s))
    vy, vz = np.gradient(y, t), np.gradient(z, t)

    imu = np.zeros((len(t), 6))
    imu[:, 1] = np.gradient(vy, t)        # ay
    imu[:, 2] = np.gradient(vz, t)        # az
    imu[:, 4] = -vz / WAND_LENGTH_M       # gy: pitching moves the tip up/down
    imu[:, 5] = vy / WAND_LENGTH_M        # gz: yawing moves the tip left/right
    return _to_sequence(t, imu, rng, label=gesture)


def casual_movement(rng):
    """Not a gesture: the wand held still, or wobbled around aimlessly."""
    t = _sample_times(rng, rng.uniform(0.6, 2.0))
    imu = np.zeros((len(t), 6))
    if rng.random() > 0.3:  # 70 % wobble, 30 % held still
        for k, max_amplitude in enumerate([3.0, 3.0, 3.0, 1.5, 1.5, 1.5]):
            for _ in range(2):
                freq = rng.uniform(0.5, 3.0)
                phase = rng.uniform(0, 2 * np.pi)
                imu[:, k] += rng.uniform(0, max_amplitude) * np.sin(2 * np.pi * freq * t + phase)
    return _to_sequence(t, imu, rng, label=None)
