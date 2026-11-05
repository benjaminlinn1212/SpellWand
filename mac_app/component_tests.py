"""Component tests: turns the logs from the hardware tests into results for the Component
Testing Summary. README.md ("Component tests") explains how to make each log. Run from mac_app/:

    .venv/bin/python component_tests.py still ../firmware/logs/<log file>
    .venv/bin/python component_tests.py turns ../firmware/logs/<log file>
    .venv/bin/python component_tests.py link link_test.log
    .venv/bin/python component_tests.py casts cast_log.csv
"""

import argparse
import csv
import re
from dataclasses import dataclass, field

import numpy as np

from protocol import END_MAX_DURATION

# Targets from the Milestone 1 deck (slides 5 and 11).
GRAVITY_MS2 = 9.81
GRAVITY_TOLERANCE_MS2 = 0.30
STILL_ROTATION_LIMIT_DPS = 1.00
MIN_READINGS_PER_S = 95
CASTS_NEEDED = 20
MAX_RESPONSE_MS = 500

SKIP_S = 5    # the still test ignores this much at the start: pressing reset shakes the wand
STILL_S = 60

TURN_AXES = "xyz"    # the turn test goes in this order
TURNING_DPS = 10     # rotating faster than this counts as turning
MAX_PAUSE_S = 0.5    # a shorter pause stays inside the same turn
MIN_TURN_DEG = 45    # anything smaller is a bump, not a turn

MOTION_LINE = re.compile(r"MotionSample\(index=(\d+), t_ms=(\d+),")
CAST_END_LINE = re.compile(r"CastEnd\(sample_count=(\d+), reason=(\d+)\)")
GYRO_OFFSET_LINE = re.compile(r"Gyro offset: (.+) deg/s")


@dataclass
class Report:
    passed: bool
    lines: list


def read_imu_readings(lines):
    """Rows of t_ms, ax, ay, az, gx, gy, gz (gyro in deg/s) from a log of the imu_log firmware build."""
    rows = []
    for line in lines:
        parts = line.strip().split(",")
        if parts[0] != "IMU" or len(parts) != 8:
            continue
        try:
            rows.append([float(part) for part in parts[1:]])
        except ValueError:
            continue  # a line cut in half when the monitor started
    readings = np.array(rows, dtype=float).reshape(-1, 7)
    readings[:, 4:7] = np.degrees(readings[:, 4:7])
    return readings


def _three(values):
    return " ".join(f"{value:.2f}" for value in values)


def still_report(lines):
    """Test 3: the wand lies still. Every reading in the minute after SKIP_S must be on target."""
    readings = read_imu_readings(lines)
    t_s = (readings[:, 0] - readings[0, 0]) / 1000 if len(readings) else np.zeros(1)
    if t_s[-1] < SKIP_S + STILL_S:
        return Report(False, [f"Only {t_s[-1]:.0f} s of readings, and the test needs {SKIP_S + STILL_S} s."])

    window = readings[(t_s >= SKIP_S) & (t_s < SKIP_S + STILL_S)]
    accel, gyro = window[:, 1:4], window[:, 4:7]
    size = np.linalg.norm(accel, axis=1)
    largest_rotation = np.abs(gyro).max(axis=0)
    seconds = (window[-1, 0] - window[0, 0]) / 1000
    report = [
        f"Still test: {seconds:.1f} s, {len(window)} readings, {(len(window) - 1) / seconds:.1f} readings/s",
        f"Acceleration x y z: mean {_three(accel.mean(axis=0))}, spread (SD) {_three(accel.std(axis=0))} m/s²",
        f"Acceleration size: mean {size.mean():.2f}, lowest {size.min():.2f}, highest {size.max():.2f} m/s²"
        f" (target {GRAVITY_MS2} ± {GRAVITY_TOLERANCE_MS2:.2f})",
        f"Rotation x y z: mean {_three(gyro.mean(axis=0))}, largest {_three(largest_rotation)} °/s"
        f" (target within ±{STILL_ROTATION_LIMIT_DPS:.2f})",
    ]
    offsets = [match.group(1) for match in map(GYRO_OFFSET_LINE.search, lines) if match]
    if offsets:
        report.append(f"Gyro offset at boot, already removed from the rotation above: {offsets[-1]} °/s")
    passed = (np.abs(size - GRAVITY_MS2).max() <= GRAVITY_TOLERANCE_MS2
              and largest_rotation.max() <= STILL_ROTATION_LIMIT_DPS)
    return Report(bool(passed), report)


def find_turns(readings):
    """Each turn as [first row, last row]: runs of rotation, joined across short pauses."""
    t_s = readings[:, 0] / 1000
    turns = []
    for row in np.flatnonzero(np.linalg.norm(readings[:, 4:7], axis=1) > TURNING_DPS):
        if turns and t_s[row] - t_s[turns[-1][1]] <= MAX_PAUSE_S:
            turns[-1][1] = row
        else:
            turns.append([row, row])
    return turns


def turns_report(lines):
    """Test 4: one 90 degree turn about x, then y, then z, with a pause after each."""
    readings = read_imu_readings(lines)
    if not len(readings):
        return Report(False, ["No IMU readings in this log."])

    step_s = np.diff(readings[:, 0], prepend=readings[0, 0]) / 1000
    report, axes = [], ""
    for first, last in find_turns(readings):
        rows = slice(first, last + 1)
        angles = (readings[rows, 4:7] * step_s[rows, None]).sum(axis=0)
        if np.abs(angles).max() < MIN_TURN_DEG:
            continue
        axis = int(np.abs(angles).argmax())
        axes += TURN_AXES[axis]
        share = abs(angles[axis]) / np.abs(angles).sum()
        report.append(f"Turn {len(axes)}: {angles[axis]:+.0f}° about {TURN_AXES[axis]} ({share:.0%} of the rotation)")
    report.append(f"Axes in order: {' '.join(axes) or 'none'} (target {' '.join(TURN_AXES)})")
    return Report(axes == TURN_AXES, report)


@dataclass
class LinkCast:
    indexes: list = field(default_factory=list)
    times_ms: list = field(default_factory=list)
    sample_count: int = None  # None: no CAST_END arrived
    reason: int = None


def read_link_casts(lines):
    """The casts in a log of `ble_manager.py --listen`."""
    casts = []
    for line in lines:
        if "CastStart(" in line:
            casts.append(LinkCast())
        elif casts and (match := MOTION_LINE.search(line)):
            casts[-1].indexes.append(int(match.group(1)))
            casts[-1].times_ms.append(int(match.group(2)))
        elif casts and (match := CAST_END_LINE.search(line)):
            casts[-1].sample_count, casts[-1].reason = int(match.group(1)), int(match.group(2))
    return casts


def link_report(lines):
    """Test 5: CASTS_NEEDED casts that run to the 3 s limit, with no reading lost on the way."""
    report, rates = [], []
    missing_total, unfinished = 0, 0
    for number, cast in enumerate(read_link_casts(lines), 1):
        if cast.sample_count is None:
            unfinished += 1
            report.append(f"Cast {number}: no CAST_END arrived")
        elif cast.reason != END_MAX_DURATION:
            report.append(f"Cast {number}: released before 3 s, not counted")
        else:
            missing = sorted(set(range(cast.sample_count)) - set(cast.indexes))
            seconds = (cast.times_ms[-1] - cast.times_ms[0]) / 1000 if len(cast.times_ms) > 1 else 0
            rates.append((len(cast.indexes) - 1) / seconds if seconds else 0.0)
            missing_total += len(missing)
            report.append(f"Cast {number}: {len(cast.indexes)} of {cast.sample_count} readings, {rates[-1]:.1f} readings/s"
                          + (f", missing {missing[:10]}" if missing else ""))
    report.append(f"Full casts: {len(rates)} (target {CASTS_NEEDED})")
    report.append(f"Slowest cast: {min(rates, default=0):.1f} readings/s (target at least {MIN_READINGS_PER_S})")
    report.append(f"Missing reading numbers: {missing_total} (target 0)")
    passed = (len(rates) >= CASTS_NEEDED and min(rates, default=0) >= MIN_READINGS_PER_S
              and missing_total == 0 and unfinished == 0)
    return Report(passed, report)


def casts_report(lines):
    """Response times from cast_log.csv, which the Mac app writes for every cast."""
    rows = list(csv.DictReader(lines))
    if not rows:
        return Report(False, ["No casts in this log."])
    times_ms = [float(row["response_ms"]) for row in rows if row["response_ms"]]
    unanswered = len(rows) - len(times_ms)
    report = [f"Casts: {len(rows)}, of which {unanswered} got no answer"]
    if times_ms:
        report.append(f"Mac response time: mean {np.mean(times_ms):.0f} ms, slowest {max(times_ms):.0f} ms"
                      f" (target at most {MAX_RESPONSE_MS})")
    report.append("This is CAST_END arriving to GESTURE_RESULT sent. The serial monitor shows the wand's full time.")
    return Report(unanswered == 0 and max(times_ms) <= MAX_RESPONSE_MS, report)


REPORTS = {"still": still_report, "turns": turns_report, "link": link_report, "casts": casts_report}


def main():
    parser = argparse.ArgumentParser(description="Turn a component test log into results.")
    parser.add_argument("test", choices=REPORTS)
    parser.add_argument("log", help="the log file (see README.md, Component tests)")
    args = parser.parse_args()
    with open(args.log, errors="replace") as f:
        report = REPORTS[args.test](f.read().splitlines())
    print("\n".join(report.lines))
    print("Result:", "PASS" if report.passed else "FAIL")


if __name__ == "__main__":
    main()
