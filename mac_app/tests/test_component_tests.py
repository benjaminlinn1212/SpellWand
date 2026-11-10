"""Tests of the component test reports. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v

The logs here are written in the exact formats the real tools produce: the imu_log
firmware build's IMU lines, and `ble_manager.py --listen` printing decoded events.
"""

import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from component_tests import casts_report, link_report, still_report, turns_report
from protocol import (
    END_MAX_DURATION, END_NORMAL, MotionSample, SOURCE_CAST_BUTTON, decode_event,
    encode_cast_end, encode_cast_start, encode_motion_sample,
)


def imu_line(t_ms, accel=(0.0, 0.0, 9.81), gyro_dps=(0.0, 0.0, 0.0)):
    """One line as firmware/src/main.cpp prints it in the imu_log build (gyro in rad/s)."""
    gyro = [math.radians(g) for g in gyro_dps]
    return f"IMU,{t_ms},{accel[0]:.3f},{accel[1]:.3f},{accel[2]:.3f},{gyro[0]:.4f},{gyro[1]:.4f},{gyro[2]:.4f}"


def still_log(seconds=70, accel=(0.0, 0.0, 9.81), gyro_dps=(0.1, -0.1, 0.0), start_ms=2000):
    return [imu_line(start_ms + 10 * i, accel, gyro_dps) for i in range(seconds * 100)]


def turn_log(axes, degrees=90.0):
    """A 2 s pause, then one 1 s turn at a steady rate for each axis, each followed by a 2 s pause."""
    lines, t = [], 0

    def hold(seconds, gyro_dps=(0.0, 0.0, 0.0)):
        nonlocal t
        for _ in range(int(seconds * 100)):
            lines.append(imu_line(t, gyro_dps=gyro_dps))
            t += 10

    hold(2)
    for axis in axes:
        rate = [0.0, 0.0, 0.0]
        rate["xyz".index(axis)] = degrees
        hold(1, rate)
        hold(2)
    return lines


def listen_line(message):
    """What `ble_manager.py --listen` prints for one message from the wand."""
    return str(decode_event(message))


def cast_lines(samples=300, reason=END_MAX_DURATION, skip=(), period_ms=10, start_ms=5000):
    lines = [listen_line(encode_cast_start(SOURCE_CAST_BUTTON))]
    for i in range(samples):
        if i not in skip:
            sample = MotionSample(i, start_ms + i * period_ms, 0.1, 0.2, 9.8, 0.01, 0.02, 0.03)
            lines.append(listen_line(encode_motion_sample(sample)))
    lines.append(listen_line(encode_cast_end(samples, reason)))
    return lines


def link_log(casts=20, **options):
    lines = ["Connected. Hold CAST_BUTTON and move the wand; Ctrl+C to quit."]
    for _ in range(casts):
        lines += cast_lines(**options)
    return lines


class StillReportTest(unittest.TestCase):
    def test_a_quiet_sensor_passes(self):
        report = still_report(still_log())
        self.assertTrue(report.passed, report.lines)

    def test_gravity_is_the_size_of_the_acceleration_on_any_axis(self):
        tilted = (5.0, 5.0, math.sqrt(9.81 ** 2 - 50))
        self.assertTrue(still_report(still_log(accel=tilted)).passed)

    def test_acceleration_outside_the_target_fails(self):
        report = still_report(still_log(accel=(0.0, 0.0, 10.2)))
        self.assertFalse(report.passed)

    def test_rotation_outside_the_target_fails(self):
        report = still_report(still_log(gyro_dps=(0.0, 1.5, 0.0)))
        self.assertFalse(report.passed)

    def test_a_brief_wobble_of_the_table_passes(self):
        lines = still_log()
        for i in range(3000, 3010):  # 0.1 s rocking back and forth, as the real table did
            lines[i] = imu_line(2000 + 10 * i, gyro_dps=(1.8 if i % 2 else -1.8, 0.0, 0.0))
        self.assertTrue(still_report(lines).passed)

    def test_a_brief_jolt_in_the_acceleration_passes(self):
        lines = still_log()
        for i in range(3000, 3010):
            lines[i] = imu_line(2000 + 10 * i, accel=(0.0, 0.0, 10.3 if i % 2 else 9.4))
        self.assertTrue(still_report(lines).passed)

    def test_being_turned_a_few_degrees_fails(self):
        lines = still_log()
        for i in range(3000, 3010):  # 0.1 s at 40 deg/s = 4 degrees that do not come back
            lines[i] = imu_line(2000 + 10 * i, gyro_dps=(40.0, 0.0, 0.0))
        self.assertFalse(still_report(lines).passed)

    def test_acceleration_off_target_for_a_whole_second_fails(self):
        lines = still_log()
        for i in range(3000, 3100):
            lines[i] = imu_line(2000 + 10 * i, accel=(0.0, 0.0, 10.2))
        self.assertFalse(still_report(lines).passed)

    def test_the_largest_single_reading_is_still_reported(self):
        lines = still_log()
        lines[3000] = imu_line(32000, gyro_dps=(1.8, 0.0, 0.0))
        self.assertIn("largest single reading 1.80", "\n".join(still_report(lines).lines))

    def test_the_first_seconds_are_skipped_so_pressing_reset_does_not_count(self):
        lines = still_log()
        lines[100] = imu_line(3000, gyro_dps=(50.0, 0.0, 0.0))
        self.assertTrue(still_report(lines).passed)

    def test_time_after_the_minute_is_skipped_so_stopping_the_log_does_not_count(self):
        lines = still_log(seconds=70)
        lines[-1] = imu_line(71990, gyro_dps=(50.0, 0.0, 0.0))
        self.assertTrue(still_report(lines).passed)

    def test_a_log_shorter_than_the_test_fails(self):
        report = still_report(still_log(seconds=40))
        self.assertFalse(report.passed)
        self.assertIn("65 s", "\n".join(report.lines))

    def test_the_boot_gyro_offset_is_reported(self):
        lines = ["Gyro offset: 1.20 -2.30 0.40 deg/s"] + still_log()
        self.assertIn("1.20 -2.30 0.40", "\n".join(still_report(lines).lines))

    def test_broken_and_unrelated_lines_are_ignored(self):
        lines = ["=== SpellWand firmware booted ===", "IMU,12", "IMU,a,b,c,d,e,f,g"] + still_log()
        self.assertTrue(still_report(lines).passed)

    def test_a_log_with_no_readings_fails(self):
        self.assertFalse(still_report(["=== SpellWand firmware booted ==="]).passed)


class TurnsReportTest(unittest.TestCase):
    def test_one_turn_about_each_axis_in_order_passes(self):
        report = turns_report(turn_log("xyz"))
        self.assertTrue(report.passed, report.lines)

    def test_the_angle_of_each_turn_is_reported(self):
        self.assertIn("90", "\n".join(turns_report(turn_log("xyz")).lines))

    def test_a_turn_on_the_wrong_axis_fails(self):
        self.assertFalse(turns_report(turn_log("xzy")).passed)

    def test_a_missing_turn_fails(self):
        self.assertFalse(turns_report(turn_log("xy")).passed)

    def test_a_small_bump_is_not_a_turn(self):
        lines = turn_log("xyz")
        for i in range(50, 60):  # 0.1 s at 100 deg/s = 10 degrees, during the first pause
            lines[i] = imu_line(i * 10, gyro_dps=(0.0, 100.0, 0.0))
        self.assertTrue(turns_report(lines).passed)

    def test_a_brief_slowdown_stays_within_one_turn(self):
        lines = turn_log("xyz")
        for i in range(240, 250):  # 0.1 s stop halfway through the x turn
            lines[i] = imu_line(i * 10)
        self.assertTrue(turns_report(lines).passed)

    def test_a_log_with_no_readings_fails(self):
        self.assertFalse(turns_report([]).passed)


class LinkReportTest(unittest.TestCase):
    def test_twenty_full_casts_with_nothing_missing_pass(self):
        report = link_report(link_log())
        self.assertTrue(report.passed, report.lines)

    def test_one_missing_reading_number_fails_and_is_named(self):
        lines = link_log(casts=19) + cast_lines(skip={123})
        report = link_report(lines)
        self.assertFalse(report.passed)
        self.assertIn("123", "\n".join(report.lines))

    def test_the_last_reading_going_missing_is_noticed(self):
        lines = link_log(casts=19) + cast_lines(skip={299})
        self.assertFalse(link_report(lines).passed)

    def test_too_few_readings_per_second_fails(self):
        report = link_report(link_log(samples=270, period_ms=11))  # about 91 readings/s
        self.assertFalse(report.passed)

    def test_fewer_than_twenty_full_casts_fails(self):
        self.assertFalse(link_report(link_log(casts=19)).passed)

    def test_casts_released_early_do_not_count_towards_the_twenty(self):
        lines = link_log(casts=19) + cast_lines(samples=100, reason=END_NORMAL)
        self.assertFalse(link_report(lines).passed)

    def test_an_early_cast_does_not_spoil_twenty_good_ones(self):
        lines = cast_lines(samples=100, reason=END_NORMAL) + link_log()
        self.assertTrue(link_report(lines).passed)

    def test_a_cast_that_never_ended_fails(self):
        lines = link_log()
        lines += cast_lines()[:-1] + ["Wand disconnected"]
        self.assertFalse(link_report(lines).passed)

    def test_a_log_with_no_casts_fails(self):
        self.assertFalse(link_report(["Looking for SpellWand for up to 10 s..."]).passed)


class CastsReportTest(unittest.TestCase):
    HEADER = "time,predicted,nearest,distance,response_ms,samples,dropped"

    def log(self, *response_ms):
        rows = [f"2026-11-05T10:00:00,CIRCLE,CIRCLE,0.3,{ms},150,0" for ms in response_ms]
        return [self.HEADER] + rows

    def test_every_response_within_the_target_passes(self):
        report = casts_report(self.log(12.5, 40.0, 499.9))
        self.assertTrue(report.passed, report.lines)

    def test_one_slow_response_fails(self):
        self.assertFalse(casts_report(self.log(12.5, 40.0, 501.0)).passed)

    def test_the_slowest_response_is_reported(self):
        self.assertIn("501", "\n".join(casts_report(self.log(12.5, 501.0)).lines))

    def test_a_cast_that_got_no_answer_fails(self):
        self.assertFalse(casts_report(self.log(12.5, "")).passed)

    def test_an_empty_log_fails(self):
        self.assertFalse(casts_report([self.HEADER]).passed)


class CommandLineTest(unittest.TestCase):
    def run_report(self, test, log_bytes):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "test.log"
            log.write_bytes(log_bytes)
            script = Path(__file__).parent.parent / "component_tests.py"
            done = subprocess.run([sys.executable, str(script), test, str(log)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_a_log_file_with_boot_noise_gives_a_result(self):
        log = b"\xff\xfe\x00 boot noise\r\n" + "\r\n".join(still_log()).encode()
        self.assertIn("Result: PASS", self.run_report("still", log))

    def test_a_failed_test_says_so(self):
        log = "\n".join(link_log(casts=3)).encode()
        self.assertIn("Result: FAIL", self.run_report("link", log))


if __name__ == "__main__":
    unittest.main()
