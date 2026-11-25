"""Tests for the Gesture Classifier. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import math
import unittest

import numpy as np

from classifier import UNKNOWN, GestureClassifier, GestureSequence, dtw_distance, leave_one_out, level_the_roll
from motion_trace import _rotation
from simulator import GESTURES, casual_movement, make_gesture

N_SAMPLES = 40


def bump(amplitude=3.0, n=N_SAMPLES):
    """A smooth 0 -> peak -> 0 pulse, like one swing of the wand (rad/s)."""
    return amplitude * np.sin(np.linspace(0, np.pi, n))


def gyro_sequence(gx=0.0, gy=0.0, gz=0.0, label=None, duration_ms=1000):
    """GestureSequence with rotation only (rad/s); the accelerometer reads zero."""
    gx, gy, gz = np.broadcast_arrays(np.asarray(gx, float), np.asarray(gy, float), np.asarray(gz, float))
    imu = np.zeros((len(gx), 6))
    imu[:, 3], imu[:, 4], imu[:, 5] = gx, gy, gz
    t_ms = np.linspace(0, duration_ms, len(gx))
    return GestureSequence(t_ms=t_ms, imu=imu, label=label)


def turn(axis, degrees):
    """Rotation matrix for turning `degrees` about the x, y or z axis (right-hand rule)."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    i, j = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    r = np.eye(3)
    r[i, i], r[i, j], r[j, i], r[j, j] = c, -s, s, c
    return r


def swing_seen_by(start, axis_in_world, amplitude=1.5, n=N_SAMPLES):
    """A swing about a fixed direction in the room, as measured by a wand that starts out
    held in orientation `start` (wand axes -> room axes). Room axes: x forward, y left, z up.
    A swing about z moves the tip sideways; a swing about y moves it up and down.
    The accelerometer feels only gravity (the swing pivots at the hand)."""
    t = np.linspace(0.0, 1.0, n)
    rate = amplitude * np.sin(np.pi * t)                    # rad/s
    angle = amplitude / np.pi * (1 - np.cos(np.pi * t))     # turned so far, rad
    axis = np.asarray(axis_in_world, dtype=float)
    imu = np.zeros((n, 6))
    for k in range(n):
        orientation = _rotation(axis * angle[k]) @ start     # wand axes -> room axes now
        imu[k, 0:3] = orientation.T @ [0.0, 0.0, 9.81]      # gravity, seen in the wand's axes
        imu[k, 3:6] = orientation.T @ (axis * rate[k])      # the turn, seen in the wand's axes
    return GestureSequence(t_ms=1000 * t, imu=imu)


SIDEWAYS = [0.0, 0.0, 1.0]
UP_DOWN = [0.0, 1.0, 0.0]


def three_axis_examples():
    """One example per gyro axis. A swing about one axis is far from a swing about
    another, so the nearest example is easy to reason about by hand."""
    return [
        gyro_sequence(gx=bump(), label="GX"),
        gyro_sequence(gy=bump(), label="GY"),
        gyro_sequence(gz=bump(), label="GZ"),
    ]


class DtwDistanceTest(unittest.TestCase):
    # Expected values below were worked out by hand from the cost matrix |a[i] - b[j]|.

    def test_identical_sequences_cost_nothing(self):
        self.assertEqual(dtw_distance([0, 1, 2], [0, 1, 2]), 0.0)

    def test_stretched_copy_aligns_for_free(self):
        # b repeats the 1; DTW should align both 1s in b with the single 1 in a.
        self.assertEqual(dtw_distance([0, 1, 2], [0, 1, 1, 2]), 0.0)

    def test_constant_offset_costs_offset_per_step(self):
        self.assertEqual(dtw_distance([0, 0, 0], [1, 1, 1]), 3.0)

    def test_frames_compared_with_euclidean_distance(self):
        # 3-4-5 triangle: one 2-D frame vs another.
        self.assertEqual(dtw_distance([[0, 0]], [[3, 4]]), 5.0)

    def test_window_limits_how_far_alignment_can_shift(self):
        a = [0, 1, 2, 3]
        b = [1, 2, 3, 3]
        # Unlimited: a0-b0 (1) then a1-b0, a2-b1, a3-b2, a3-b3 (all 0) = 1.
        self.assertEqual(dtw_distance(a, b), 1.0)
        # Window 0 forces the straight diagonal: 1 + 1 + 1 + 0 = 3.
        self.assertEqual(dtw_distance(a, b, window=0), 3.0)


class ClassifierDecisionTest(unittest.TestCase):
    def setUp(self):
        self.clf = GestureClassifier(threshold=10.0)
        self.clf.fit(three_axis_examples())

    def test_exact_copy_of_an_example_is_recognized(self):
        result = self.clf.classify(gyro_sequence(gx=bump()))
        self.assertEqual(result.label, "GX")
        self.assertAlmostEqual(result.distance, 0.0)

    def test_picks_the_nearest_example(self):
        # Mostly a y-swing with a little x: close to GY, far from GX and GZ.
        result = self.clf.classify(gyro_sequence(gy=bump(), gx=bump(amplitude=0.6)))
        self.assertEqual(result.label, "GY")

    def test_wrong_shape_is_unknown(self):
        # Two swings instead of one: most like GX (same axis), but a different shape.
        self.clf.threshold = 0.1
        double_swing = 3.0 * np.abs(np.sin(np.linspace(0, 2 * np.pi, N_SAMPLES)))
        result = self.clf.classify(gyro_sequence(gx=double_swing))
        self.assertEqual(result.label, UNKNOWN)
        self.assertEqual(result.nearest_label, "GX")
        self.assertGreater(result.distance, 0.1)

    def test_distance_equal_to_threshold_is_accepted(self):
        query = gyro_sequence(gz=bump(), gx=bump(amplitude=0.6))
        self.clf.threshold = math.inf
        d = self.clf.classify(query).distance
        self.assertGreater(d, 0.0)

        self.clf.threshold = d
        self.assertEqual(self.clf.classify(query).label, "GZ")
        self.clf.threshold = d * 0.99
        self.assertEqual(self.clf.classify(query).label, UNKNOWN)

    def test_no_examples_gives_unknown(self):
        clf = GestureClassifier(threshold=10.0)
        clf.fit([])
        result = clf.classify(gyro_sequence(gx=bump()))
        self.assertEqual(result.label, UNKNOWN)
        self.assertIsNone(result.nearest_label)
        self.assertEqual(result.distance, math.inf)

    def test_example_without_label_is_refused(self):
        with self.assertRaises(ValueError):
            GestureClassifier(threshold=1.0).fit([gyro_sequence(gx=bump())])

    def test_empty_training_example_is_refused(self):
        with self.assertRaises(ValueError):
            GestureClassifier(threshold=1.0).fit([gyro_sequence(gx=bump(n=0), label="GX")])


class PreprocessingTest(unittest.TestCase):
    def setUp(self):
        self.clf = GestureClassifier(threshold=10.0)
        self.clf.fit(three_axis_examples())

    def test_same_swing_with_the_tip_raised_30_degrees_still_matches(self):
        # The wand turns about its own z axis. Held level, gravity stays on z. With the tip
        # raised, gravity swings between the wand's axes as it turns, which must not make it
        # look like a different gesture: gravity is taken out of every reading.
        level = swing_seen_by(np.eye(3), SIDEWAYS)
        level.label = "SWING"
        raised = turn("y", -30)  # turning the tip (x) up toward z
        tilted = swing_seen_by(raised, raised @ np.array(SIDEWAYS))  # about the wand's own z
        clf = GestureClassifier(threshold=1.0)
        clf.fit([level])
        result = clf.classify(tilted)
        self.assertEqual(result.label, "SWING")
        self.assertLess(result.distance, 0.01)


    def test_same_gesture_done_slower_matches_closely(self):
        # Three times as long, three times as many samples, same shape.
        slow = gyro_sequence(gx=bump(n=3 * N_SAMPLES), duration_ms=3000)
        result = self.clf.classify(slow)
        self.assertEqual(result.label, "GX")
        self.assertLess(result.distance, 0.01)

    def test_same_gesture_drawn_bigger_matches_closely(self):
        result = self.clf.classify(gyro_sequence(gx=bump(amplitude=6.0)))
        self.assertEqual(result.label, "GX")
        self.assertLess(result.distance, 0.01)

    def test_holding_still_before_and_after_the_gesture_is_ignored(self):
        # Training recordings include waiting: after pressing Start, and before pressing Stop.
        still = np.zeros(100)
        padded = np.concatenate([still, bump(), still, still])
        sequence = gyro_sequence(gx=padded, duration_ms=1000 * len(padded) / N_SAMPLES)
        result = self.clf.classify(sequence)
        self.assertEqual(result.label, "GX")
        self.assertLess(result.distance, 0.05)

    def test_barely_moving_wand_is_unknown(self):
        # Exactly the GX shape, but so small it is just a twitch.
        result = self.clf.classify(gyro_sequence(gx=bump(amplitude=0.05)))
        self.assertEqual(result.label, UNKNOWN)

    def test_too_short_recording_is_unknown(self):
        # 0 and 1 samples: nothing recorded. 3 samples: a 30 ms jolt, moving hard but far
        # too brief to be a gesture.
        for n in (0, 1, 3):
            with self.subTest(samples=n):
                result = self.clf.classify(gyro_sequence(gx=bump(n=n)))
                self.assertEqual(result.label, UNKNOWN)


class RollTest(unittest.TestCase):
    """Turning the wand in the hand (about its own long axis) must not change the gesture.
    Up and down in the room still count: an up-down swing is not a sideways swing."""

    def setUp(self):
        level = np.eye(3)
        sideways, up_down = swing_seen_by(level, SIDEWAYS), swing_seen_by(level, UP_DOWN)
        sideways.label, up_down.label = "SIDEWAYS", "UP_DOWN"
        self.clf = GestureClassifier(threshold=1.0)
        self.clf.fit([sideways, up_down])

    def test_a_swing_matches_however_far_the_wand_is_rolled(self):
        for label, axis in (("SIDEWAYS", SIDEWAYS), ("UP_DOWN", UP_DOWN)):
            for roll in (30, 90, 135, 180, -60):
                with self.subTest(gesture=label, roll=roll):
                    result = self.clf.classify(swing_seen_by(turn("x", roll), axis))
                    self.assertEqual(result.label, label)
                    self.assertLess(result.distance, 0.01)

    def test_roll_is_found_with_the_tip_raised_or_lowered(self):
        for pitch in (-45, 45):
            with self.subTest(pitch=pitch):
                start = turn("y", pitch) @ turn("x", 90)  # rolled a quarter turn, tip tilted
                rolled = swing_seen_by(start, SIDEWAYS)
                level = swing_seen_by(turn("y", pitch), SIDEWAYS)
                self.assertLess(self.clf.classify(rolled).distance, 0.01 + self.clf.classify(level).distance)
                self.assertEqual(self.clf.classify(rolled).nearest_label, self.clf.classify(level).nearest_label)

    def test_readings_are_left_as_they_are_when_the_tip_points_almost_straight_up_or_down(self):
        # Gravity then lies along the wand, so its roll can't be read from it.
        imu = np.arange(12, dtype=float).reshape(2, 6)
        for up in ([9.81, 0.5, 0.3], [-9.81, 0.2, -0.6], [0.0, 0.0, 0.0]):
            with self.subTest(up=up):
                np.testing.assert_array_equal(level_the_roll(imu, np.array(up)), imu)

    def test_leveling_turns_the_start_s_up_onto_the_wand_s_z_axis(self):
        up = 9.81 * np.array([0.2, math.sin(math.radians(70)), math.cos(math.radians(70))])
        imu = np.concatenate([up, [0.0, 1.0, 0.0]])[None, :]
        leveled = level_the_roll(imu, up)
        self.assertAlmostEqual(leveled[0, 1], 0.0)                     # no sideways part left
        self.assertGreater(leveled[0, 2], 0.0)                         # up is up, not down
        self.assertAlmostEqual(leveled[0, 0], up[0])                   # along the wand: untouched
        self.assertAlmostEqual(np.linalg.norm(leveled[0, 0:3]), np.linalg.norm(up))
        self.assertAlmostEqual(np.linalg.norm(leveled[0, 3:6]), 1.0)  # the gyro turns the same way


class DatasetCheckTest(unittest.TestCase):
    def test_each_example_is_compared_with_all_the_others(self):
        examples = three_axis_examples() + three_axis_examples()
        checks = leave_one_out(examples)
        self.assertEqual([c.label for c in checks], ["GX", "GY", "GZ", "GX", "GY", "GZ"])
        self.assertEqual([c.nearest_label for c in checks], ["GX", "GY", "GZ", "GX", "GY", "GZ"])
        for c in checks:
            self.assertAlmostEqual(c.distance, 0.0)

    def test_mislabelled_example_is_flagged(self):
        examples = three_axis_examples() + three_axis_examples()
        examples[0] = gyro_sequence(gy=bump(), label="GX")  # a y-swing saved under the wrong label
        check = leave_one_out(examples)[0]
        self.assertEqual(check.label, "GX")
        self.assertEqual(check.nearest_label, "GY")

    def test_single_example_has_nothing_to_compare_with(self):
        [check] = leave_one_out([gyro_sequence(gx=bump(), label="GX")])
        self.assertIsNone(check.nearest_label)
        self.assertEqual(check.distance, math.inf)


class SimulatedGestureTest(unittest.TestCase):
    """Whole-classifier check on simulated gestures (see simulator.py).
    5 training examples per gesture, then 20 fresh variations each, plus casual movement."""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(seed=1)
        cls.clf = GestureClassifier(threshold=math.inf)
        cls.clf.fit([make_gesture(g, rng) for g in GESTURES for _ in range(5)])
        cls.gesture_results = [(g, cls.clf.classify(make_gesture(g, rng)))
                               for g in GESTURES for _ in range(20)]
        cls.casual_results = [cls.clf.classify(casual_movement(rng)) for _ in range(30)]

    def test_new_gestures_are_nearest_to_their_own_label(self):
        wrong = [(g, r.nearest_label) for g, r in self.gesture_results if r.nearest_label != g]
        self.assertEqual(wrong, [])

    def test_casual_movement_is_at_least_4x_farther_than_any_gesture(self):
        # Real recordings will be noisier than these, so we want a wide safety margin:
        # then a threshold between the two groups accepts gestures and rejects casual movement.
        worst_gesture = max(r.distance for _, r in self.gesture_results)
        closest_casual = min(r.distance for r in self.casual_results)
        self.assertGreaterEqual(closest_casual, 4 * worst_gesture)


if __name__ == "__main__":
    unittest.main()
