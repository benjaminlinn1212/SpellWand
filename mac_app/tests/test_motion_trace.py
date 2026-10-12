"""Tests for the 3D wand-tip trace. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import math
import unittest

import numpy as np

from classifier import GestureSequence
from motion_trace import tip_trace
from synthetic import make_gesture

G = 9.81
L = 0.3  # wand length in metres


def constant_motion(accel, gyro, duration_ms=1000, n=101):
    """A recording where the accelerometer and gyroscope read the same values throughout."""
    imu = np.tile(np.concatenate([accel, gyro]), (n, 1)).astype(float)
    return GestureSequence(t_ms=np.linspace(0, duration_ms, n), imu=imu)


class TipTraceTest(unittest.TestCase):
    # Wand frame: x along the wand toward the tip, y to the left, z up.
    # World frame: same axes when the wand is held level and pointing forward.

    def test_still_level_wand_points_straight_ahead(self):
        trace = tip_trace(constant_motion([0, 0, G], [0, 0, 0]), wand_length_m=L)
        np.testing.assert_allclose(trace, np.tile([L, 0, 0], (101, 1)), atol=1e-9)

    def test_wand_tilted_up_30_degrees_points_up(self):
        # Tip raised 30 degrees: gravity's "up" reads partly along the wand's x axis.
        up_in_wand = [G * math.sin(math.radians(30)), 0, G * math.cos(math.radians(30))]
        trace = tip_trace(constant_motion(up_in_wand, [0, 0, 0]), wand_length_m=L)
        expected = [L * math.cos(math.radians(30)), 0, L * math.sin(math.radians(30))]
        np.testing.assert_allclose(trace[0], expected, atol=1e-9)
        np.testing.assert_allclose(trace[-1], expected, atol=1e-9)

    def test_quarter_turn_about_z_swings_tip_to_the_left(self):
        trace = tip_trace(constant_motion([0, 0, G], [0, 0, math.pi / 2]), wand_length_m=L)
        np.testing.assert_allclose(trace[0], [L, 0, 0], atol=1e-9)
        np.testing.assert_allclose(trace[-1], [0, L, 0], atol=1e-6)

    def test_quarter_turn_about_minus_y_raises_the_tip(self):
        # Pitching up at pi/2 rad/s: after t seconds the tip is raised by angle a = pi t / 2,
        # so gravity's "up" reads (sin a, 0, cos a) in the wand's axes.
        motion = constant_motion([0, 0, G], [0, -math.pi / 2, 0])
        a = np.pi / 2 * motion.t_ms / 1000
        motion.imu[:, 0:3] = G * np.column_stack([np.sin(a), np.zeros_like(a), np.cos(a)])
        trace = tip_trace(motion, wand_length_m=L)
        np.testing.assert_allclose(trace[0], [L, 0, 0], atol=1e-6)
        np.testing.assert_allclose(trace[-1], [0, 0, L], atol=1e-6)

    def test_tip_stays_one_wand_length_from_the_hand(self):
        trace = tip_trace(make_gesture("ZIGZAG", np.random.default_rng(0)), wand_length_m=L)
        np.testing.assert_allclose(np.linalg.norm(trace, axis=1), L, atol=1e-9)

    def test_simulated_circle_comes_back_to_where_it_started(self):
        for seed in range(5):
            with self.subTest(seed=seed):
                trace = tip_trace(make_gesture("CIRCLE", np.random.default_rng(seed)), wand_length_m=L)
                size = np.ptp(trace, axis=0).max()
                gap = np.linalg.norm(trace[-1] - trace[0])
                self.assertLess(gap, 0.1 * size)

    def test_simulated_horizontal_line_is_mostly_left_right(self):
        for seed in range(5):
            with self.subTest(seed=seed):
                trace = tip_trace(make_gesture("HORIZONTAL_LINE", np.random.default_rng(seed)), wand_length_m=L)
                left_right, up_down = np.ptp(trace[:, 1]), np.ptp(trace[:, 2])
                self.assertLess(up_down, 0.5 * left_right)


if __name__ == "__main__":
    unittest.main()
