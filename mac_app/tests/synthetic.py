"""Simulated IMU recordings so the Gesture Classifier can be tested without the wand.

The wand pivots at the hand and its tip traces a shape in front of you
(axes: x forward, y left, z up). For every moment we work out the wand's true
orientation, then what an IMU riding at the tip would read:
  gyroscope     = how much the orientation turned since the previous moment
  accelerometer = the tip's acceleration + gravity, both seen in the wand's own axes
Every call adds random variation: size, duration, uneven pacing, the tilt of the
whole gesture, timing jitter and sensor noise. Real recordings will be messier;
this is only a sanity check.
"""

import numpy as np

from classifier import GestureSequence

GESTURES = ("CIRCLE", "ZIGZAG", "HORIZONTAL_LINE")
SAMPLE_RATE_HZ = 100
WAND_LENGTH_M = 0.3
GRAVITY = 9.81


def _tip_path(gesture, s):
    """Where the tip is aimed: (left, up) offsets in metres for progress s from 0 to 1."""
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


def _rot_y(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _rot_z(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _rot_x(angle):
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _random_tilt(rng):
    """The whole gesture done up to 20 degrees off level (pitch and roll)."""
    pitch, roll = np.radians(rng.uniform(-20, 20, 2))
    return _rot_y(pitch) @ _rot_x(roll)


def _turn_angle(r_from, r_to):
    """Rotation vector (axis * angle, in the wand's own axes) that turns r_from into r_to."""
    m = r_from.T @ r_to
    angle = np.arccos(np.clip((np.trace(m) - 1) / 2, -1.0, 1.0))
    if angle < 1e-12:
        return np.zeros(3)
    return angle / (2 * np.sin(angle)) * np.array([m[2, 1] - m[1, 2], m[0, 2] - m[2, 0], m[1, 0] - m[0, 1]])


def _gyro_readings(orientations, t):
    """Rotation rate (rad/s, wand axes) at each sample, from the orientation at each time."""
    rates = np.array([_turn_angle(orientations[k], orientations[k + 1]) / (t[k + 1] - t[k])
                      for k in range(len(t) - 1)])
    # Each sample reads the average of the turns just before and just after it.
    return np.vstack([rates[:1], 0.5 * (rates[1:] + rates[:-1]), rates[-1:]])


def _add_noise(t_s, imu, rng, label):
    imu = imu.copy()
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
    left, up = (size * p for p in _tip_path(gesture, s))

    # Wand orientation at each moment: turn left/right toward the target, then tip up/down.
    tilt = _random_tilt(rng)
    orientations = [tilt @ _rot_z(np.arctan2(y, WAND_LENGTH_M)) @ _rot_y(-np.arctan2(z, np.hypot(WAND_LENGTH_M, y)))
                    for y, z in zip(left, up)]

    tip = np.array([r @ [WAND_LENGTH_M, 0.0, 0.0] for r in orientations])
    tip_accel = np.gradient(np.gradient(tip, t, axis=0), t, axis=0)
    gravity = np.array([0.0, 0.0, GRAVITY])

    imu = np.zeros((len(t), 6))
    for k, r in enumerate(orientations):
        imu[k, 0:3] = r.T @ (tip_accel[k] + gravity)  # what the accelerometer feels, in wand axes
    imu[:, 3:6] = _gyro_readings(orientations, t)
    return _add_noise(t, imu, rng, label=gesture)


def casual_movement(rng):
    """Not a gesture: the wand held still, or wobbled around aimlessly."""
    t = _sample_times(rng, rng.uniform(0.6, 2.0))
    imu = np.zeros((len(t), 6))
    imu[:, 0:3] = _random_tilt(rng).T @ [0.0, 0.0, GRAVITY]
    if rng.random() > 0.3:  # 70 % wobble, 30 % held still
        for k, max_amplitude in enumerate([3.0, 3.0, 3.0, 1.5, 1.5, 1.5]):
            for _ in range(2):
                freq = rng.uniform(0.5, 3.0)
                phase = rng.uniform(0, 2 * np.pi)
                imu[:, k] += rng.uniform(0, max_amplitude) * np.sin(2 * np.pi * freq * t + phase)
    return _add_noise(t, imu, rng, label=None)
