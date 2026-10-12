"""Simulation, so everything can be tested before the wand hardware exists.

1. Simulated motion (make_gesture, casual_movement).
   The wand pivots at the hand and its tip traces a shape in front of you
   (axes: x forward, y left, z up). For every moment we work out the wand's true
   orientation, then what an IMU riding at the tip would read:
     gyroscope     = how much the orientation turned since the previous moment
     accelerometer = the tip's acceleration + gravity, both seen in the wand's own axes
   Every call adds random variation: size, duration, uneven pacing, the tilt of the
   whole gesture, timing jitter and sensor noise. Real recordings will be messier.

2. SimulatedWand: behaves like the ESP32 firmware over BLE_LINK (same states, same
   message bytes), so the whole Mac app can run without hardware.
"""

import threading
import time

import numpy as np

from classifier import GestureSequence
from protocol import (
    ExecuteAction, GestureResult, MotionSample, StartRecording, StopRecording, decode_command,
    encode_action_complete, encode_cast_end, encode_cast_start, encode_motion_sample,
    ACTION_PULSE_LED, ACTION_TOGGLE_LED, END_MAX_DURATION, END_NORMAL, SOURCE_CAST_BUTTON,
    SOURCE_RECORDING,
)

GESTURES = ("CIRCLE", "ZIGZAG", "HORIZONTAL_LINE")
OTHER_MOTIONS = ("WOBBLE", "STILL")  # things a simulated user can do that are not gestures
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


def still_motion(rng, duration_s=0.5):
    """The wand held still (level, give or take a few degrees)."""
    t = _sample_times(rng, duration_s)
    imu = np.zeros((len(t), 6))
    imu[:, 0:3] = _random_tilt(rng).T @ [0.0, 0.0, GRAVITY]
    return _add_noise(t, imu, rng, label=None)


def simulated_motion(name, rng):
    """A GestureSequence for one of GESTURES or OTHER_MOTIONS."""
    if name in GESTURES:
        return make_gesture(name, rng)
    if name == "WOBBLE":
        return casual_movement(rng)
    if name == "STILL":
        return still_motion(rng)
    raise ValueError(f"the simulator cannot perform {name!r}; try one of {GESTURES + OTHER_MOTIONS}")


# The firmware's built-in spell colours (firmware/lib/wand_core/wand_state.h), used when
# GESTURE_RESULT carries 0,0,0.
BUILT_IN_COLOURS = {
    "CIRCLE": (0, 80, 255),
    "ZIGZAG": (255, 64, 0),
    "HORIZONTAL_LINE": (0, 200, 40),
    "UNKNOWN": (255, 0, 0),
}
OTHER_SPELL_COLOUR = (180, 180, 180)


class SimulatedWand:
    """Pretends to be the ESP32 over BLE_LINK: same states, same message bytes.

    It offers the same methods as ble_manager.BleWandLink (connect, disconnect, send,
    and the on_event / on_disconnect callbacks), plus cast() and perform() to play the
    user's part. With realtime=False everything happens instantly, which suits tests;
    with realtime=True samples arrive at 100 Hz from a background thread, like the
    real wand.
    """

    name = "Simulated wand"
    MAX_RECORDING_S = 5.0

    def __init__(self, realtime=False, seed=None):
        self.realtime = realtime
        self.on_event = None       # called with the bytes of each event
        self.on_disconnect = None
        self.connected = False
        self.state = "IDLE"
        self.feedback_log = []     # (label, rgb) shown for each GESTURE_RESULT
        self.action_led_on = False
        self._rng = np.random.default_rng(seed)
        self._lock = threading.RLock()
        self._source = SOURCE_CAST_BUTTON
        self._sample_count = 0
        self._clock_ms = 10_000    # fake millis() when not realtime
        self._recording_motion = "STILL"
        self._stop_recording = threading.Event()

    # ---- link interface (same as BleWandLink) ----

    def connect(self):
        self.connected = True

    def disconnect(self):
        with self._lock:
            self.connected = False
            self._stop_recording.set()
            self.state = "IDLE"

    def send(self, data):
        """Handle a command from the Mac, exactly as the firmware would."""
        command = decode_command(data)
        with self._lock:
            if isinstance(command, StartRecording) and self.state == "IDLE":
                self._begin(SOURCE_RECORDING)
                self._start_recording_stream()
            elif (isinstance(command, StopRecording) and self.state == "CASTING"
                  and self._source == SOURCE_RECORDING):
                self._stop_recording.set()
                if not self.realtime:
                    self._end(END_NORMAL)
            elif isinstance(command, GestureResult) and self.state == "INFLIGHT":
                rgb = command.rgb if any(command.rgb) else BUILT_IN_COLOURS.get(command.label, OTHER_SPELL_COLOUR)
                self.feedback_log.append((command.label, rgb))
                self.state = "IDLE"
            elif isinstance(command, ExecuteAction):
                ok = command.action in (ACTION_TOGGLE_LED, ACTION_PULSE_LED)
                if command.action == ACTION_TOGGLE_LED:
                    self.action_led_on = not self.action_led_on
                self._emit(encode_action_complete(command.action, ok))

    # ---- the simulated user ----

    def cast(self, motion):
        """Hold CAST_BUTTON, perform `motion` (a gesture name, WOBBLE or STILL), release.
        Returns False if the wand is busy, like pressing the real button would do nothing."""
        with self._lock:
            if self.state != "IDLE":
                return False
            self._begin(SOURCE_CAST_BUTTON)
        sequence = simulated_motion(motion, self._rng)
        if self.realtime:
            threading.Thread(target=self._stream_cast, args=(sequence,), daemon=True).start()
        else:
            self._stream_cast(sequence)
        return True

    def perform(self, motion):
        """Choose what the simulated user does during the next training recording."""
        simulated_motion(motion, self._rng)  # fail early for an unknown motion
        self._recording_motion = motion

    # ---- internals ----

    def _begin(self, source):
        self.state = "CASTING"
        self._source = source
        self._sample_count = 0
        self._emit(encode_cast_start(source))

    def _end(self, reason):
        # Change state before sending CAST_END: the Mac may answer immediately.
        self.state = "INFLIGHT" if self._source == SOURCE_CAST_BUTTON else "IDLE"
        self._emit(encode_cast_end(self._sample_count, reason))

    def _stream_cast(self, sequence):
        self._stream(sequence)
        with self._lock:
            if self.state == "CASTING":
                self._end(END_NORMAL)

    def _start_recording_stream(self):
        self._stop_recording.clear()
        sequence = simulated_motion(self._recording_motion, self._rng)
        if self.realtime:
            threading.Thread(target=self._stream_recording, args=(sequence,), daemon=True).start()
        else:
            self._stream(sequence)

    def _stream_recording(self, sequence):
        """Realtime recording: the gesture, then holding still until STOP_RECORDING."""
        started = time.monotonic()
        self._stream(sequence)
        last = sequence.imu[-1].copy()
        last[3:6] = 0.0  # at rest: gravity only, no rotation
        while not self._stop_recording.wait(0.01):
            if time.monotonic() - started >= self.MAX_RECORDING_S:
                with self._lock:
                    if self.state == "CASTING":
                        self._end(END_MAX_DURATION)
                return
            noisy = last + np.concatenate([self._rng.normal(0, 0.3, 3), self._rng.normal(0, 0.05, 3)])
            self._send_sample(self._now_ms(), noisy)
        with self._lock:
            if self.state == "CASTING":
                self._end(END_NORMAL)

    def _stream(self, sequence):
        start_ms = self._now_ms()
        start_clock = time.monotonic()
        for t, row in zip(sequence.t_ms, sequence.imu):
            if self.realtime:
                delay = t / 1000.0 - (time.monotonic() - start_clock)
                if delay > 0:
                    time.sleep(delay)
                if not self.connected or self.state != "CASTING":
                    return
            self._send_sample(start_ms + int(t), row)
        if not self.realtime:
            self._clock_ms = start_ms + int(sequence.t_ms[-1]) + 10

    def _send_sample(self, t_ms, row):
        with self._lock:
            sample = MotionSample(self._sample_count, t_ms & 0xFFFFFFFF, *map(float, row))
            self._sample_count += 1
            self._emit(encode_motion_sample(sample))

    def _now_ms(self):
        return int(time.monotonic() * 1000) if self.realtime else self._clock_ms

    def _emit(self, data):
        if self.connected and self.on_event:
            self.on_event(data)
