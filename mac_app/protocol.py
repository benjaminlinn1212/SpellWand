"""BLE_LINK message protocol: the bytes the ESP32 and the Mac exchange.

The full specification, with example bytes, is in docs/protocol.md. The firmware
implements the same format in firmware/lib/wand_core/protocol.cpp.
"""

import math
import struct
from dataclasses import dataclass

DEVICE_NAME = "SpellWand"
SERVICE_UUID = "06f40001-a27b-408d-a176-2e94b74b3ad3"
EVENTS_UUID = "06f40002-a27b-408d-a176-2e94b74b3ad3"    # notify: ESP32 -> Mac
COMMANDS_UUID = "06f40003-a27b-408d-a176-2e94b74b3ad3"  # write:  Mac -> ESP32

# Message types (first byte)
CAST_START = 0x01
MOTION_SAMPLE = 0x02
CAST_END = 0x03
ACTION_COMPLETE = 0x04
START_RECORDING = 0x81
STOP_RECORDING = 0x82
GESTURE_RESULT = 0x83
EXECUTE_ACTION = 0x84

# CAST_START sources
SOURCE_CAST_BUTTON = 0
SOURCE_RECORDING = 1

# CAST_END reasons
END_NORMAL = 0          # button released, or STOP_RECORDING
END_MAX_DURATION = 1
END_CONNECTION_LOST = 2

# EXECUTE_ACTION actions
ACTION_TOGGLE_LED = 1
ACTION_PULSE_LED = 2

MAX_MESSAGE_BYTES = 20
MAX_LABEL_LENGTH = 16
ACCEL_STEPS_PER_UNIT = 100   # 0.01 m/s^2
GYRO_STEPS_PER_UNIT = 1000   # 0.001 rad/s

_MOTION_FORMAT = "<BHIhhhhhh"


class ProtocolError(ValueError):
    """Bytes that are not a valid message."""


# ---- Events (ESP32 -> Mac) ----

@dataclass(frozen=True)
class CastStart:
    source: int


@dataclass(frozen=True)
class MotionSample:
    """One timestamped IMU reading. Accel in m/s^2, gyro in rad/s."""
    index: int
    t_ms: int
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


@dataclass(frozen=True)
class CastEnd:
    sample_count: int
    reason: int


@dataclass(frozen=True)
class ActionComplete:
    action: int
    ok: bool


# ---- Commands (Mac -> ESP32) ----

@dataclass(frozen=True)
class StartRecording:
    pass


@dataclass(frozen=True)
class StopRecording:
    pass


@dataclass(frozen=True)
class GestureResult:
    label: str
    rgb: tuple


@dataclass(frozen=True)
class ExecuteAction:
    action: int


def encode_cast_start(source):
    return bytes([CAST_START, source])


def encode_motion_sample(sample):
    accel = [_to_steps(v, ACCEL_STEPS_PER_UNIT) for v in (sample.ax, sample.ay, sample.az)]
    gyro = [_to_steps(v, GYRO_STEPS_PER_UNIT) for v in (sample.gx, sample.gy, sample.gz)]
    return struct.pack(_MOTION_FORMAT, MOTION_SAMPLE, sample.index, sample.t_ms, *accel, *gyro)


def encode_cast_end(sample_count, reason):
    return struct.pack("<BHB", CAST_END, sample_count, reason)


def encode_action_complete(action, ok):
    return bytes([ACTION_COMPLETE, action, 1 if ok else 0])


def encode_start_recording():
    return bytes([START_RECORDING])


def encode_stop_recording():
    return bytes([STOP_RECORDING])


def encode_gesture_result(label, rgb):
    if not label or len(label) > MAX_LABEL_LENGTH or not label.isascii():
        raise ValueError(f"label must be 1-{MAX_LABEL_LENGTH} ASCII characters, got {label!r}")
    return bytes([GESTURE_RESULT, *rgb]) + label.encode("ascii")


def encode_execute_action(action):
    return bytes([EXECUTE_ACTION, action])


def decode_event(data):
    """Turn bytes from the events characteristic into a CastStart, MotionSample,
    CastEnd or ActionComplete. Raises ProtocolError for anything else."""
    kind = _message_type(data)
    if kind == CAST_START:
        _expect_length(data, 2)
        return CastStart(source=data[1])
    if kind == MOTION_SAMPLE:
        _expect_length(data, struct.calcsize(_MOTION_FORMAT))
        _, index, t_ms, ax, ay, az, gx, gy, gz = struct.unpack(_MOTION_FORMAT, data)
        return MotionSample(index, t_ms,
                            ax / ACCEL_STEPS_PER_UNIT, ay / ACCEL_STEPS_PER_UNIT, az / ACCEL_STEPS_PER_UNIT,
                            gx / GYRO_STEPS_PER_UNIT, gy / GYRO_STEPS_PER_UNIT, gz / GYRO_STEPS_PER_UNIT)
    if kind == CAST_END:
        _expect_length(data, 4)
        _, count, reason = struct.unpack("<BHB", data)
        return CastEnd(sample_count=count, reason=reason)
    if kind == ACTION_COMPLETE:
        _expect_length(data, 3)
        return ActionComplete(action=data[1], ok=data[2] == 1)
    raise ProtocolError(f"unknown event type 0x{kind:02x}")


def decode_command(data):
    """Turn bytes written to the commands characteristic into a command object
    (used by the simulated wand). Raises ProtocolError for anything else."""
    kind = _message_type(data)
    if kind == START_RECORDING:
        _expect_length(data, 1)
        return StartRecording()
    if kind == STOP_RECORDING:
        _expect_length(data, 1)
        return StopRecording()
    if kind == GESTURE_RESULT:
        if not 5 <= len(data) <= MAX_MESSAGE_BYTES:
            raise ProtocolError(f"GESTURE_RESULT must be 5-{MAX_MESSAGE_BYTES} bytes, got {len(data)}")
        try:
            label = data[4:].decode("ascii")
        except UnicodeDecodeError as error:
            raise ProtocolError("GESTURE_RESULT label is not ASCII") from error
        return GestureResult(label=label, rgb=(data[1], data[2], data[3]))
    if kind == EXECUTE_ACTION:
        _expect_length(data, 2)
        return ExecuteAction(action=data[1])
    raise ProtocolError(f"unknown command type 0x{kind:02x}")


def _to_steps(value, steps_per_unit):
    """Round to the nearest step and clamp to the int16 range."""
    return max(-32768, min(32767, math.floor(value * steps_per_unit + 0.5)))


def _message_type(data):
    if not data:
        raise ProtocolError("empty message")
    return data[0]


def _expect_length(data, length):
    if len(data) != length:
        raise ProtocolError(f"message type 0x{data[0]:02x} must be {length} bytes, got {len(data)}")
