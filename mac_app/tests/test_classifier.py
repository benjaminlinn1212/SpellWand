"""Tests for the Gesture Classifier. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import math
import unittest

import numpy as np

from classifier import UNKNOWN, GestureClassifier, GestureSequence, dtw_distance
from synthetic import GESTURES, casual_movement, make_gesture

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

    def test_tilted_wand_still_matches(self):
        # Same flick-and-push, but the wand is held tilted 25 degrees, so gravity
        # shows up partly on the y axis instead of only on z.
        def flick(gravity):
            imu = np.zeros((N_SAMPLES, 6))
            imu[:, 0:3] = gravity
            imu[:, 0] += bump(amplitude=5.0)
            imu[:, 4] = bump()
            return GestureSequence(t_ms=np.linspace(0, 1000, N_SAMPLES), imu=imu)

        level = flick([0.0, 0.0, 9.81])
        level.label = "FLICK"
        tilted = flick([0.0, 9.81 * math.sin(math.radians(25)), 9.81 * math.cos(math.radians(25))])

        clf = GestureClassifier(threshold=1.0)
        clf.fit([level])
        result = clf.classify(tilted)
        self.assertEqual(result.label, "FLICK")
        self.assertAlmostEqual(result.distance, 0.0, places=6)

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


class SimulatedGestureTest(unittest.TestCase):
    """Whole-classifier check on simulated gestures (see synthetic.py).
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
