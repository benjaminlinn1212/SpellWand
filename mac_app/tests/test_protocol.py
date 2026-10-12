"""Tests for the BLE_LINK message protocol (see docs/protocol.md). Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import unittest

from protocol import (
    ActionComplete, CastEnd, CastStart, ExecuteAction, GestureResult, MotionSample, ProtocolError,
    StartRecording, StopRecording, decode_command, decode_event, encode_action_complete,
    encode_cast_end, encode_cast_start, encode_execute_action, encode_gesture_result,
    encode_motion_sample, encode_start_recording, encode_stop_recording,
)

# Example bytes from docs/protocol.md (the firmware's tests check the same ones).
SAMPLE = MotionSample(index=7, t_ms=123456, ax=0.12, ay=-9.81, az=1.00, gx=0.5, gy=-1.25, gz=3.0)
SAMPLE_BYTES = bytes.fromhex("02 07 00 40 e2 01 00 0c 00 2b fc 64 00 f4 01 1e fb b8 0b")


class ExampleBytesTest(unittest.TestCase):
    def test_events_encode_to_the_documented_bytes(self):
        self.assertEqual(encode_cast_start(0), bytes.fromhex("01 00"))
        self.assertEqual(encode_motion_sample(SAMPLE), SAMPLE_BYTES)
        self.assertEqual(encode_cast_end(150, 1), bytes.fromhex("03 96 00 01"))
        self.assertEqual(encode_action_complete(2, True), bytes.fromhex("04 02 01"))

    def test_commands_encode_to_the_documented_bytes(self):
        self.assertEqual(encode_start_recording(), bytes.fromhex("81"))
        self.assertEqual(encode_stop_recording(), bytes.fromhex("82"))
        self.assertEqual(encode_gesture_result("CIRCLE", (0, 80, 255)),
                         bytes.fromhex("83 00 50 ff 43 49 52 43 4c 45"))
        self.assertEqual(encode_execute_action(1), bytes.fromhex("84 01"))

    def test_documented_event_bytes_decode(self):
        self.assertEqual(decode_event(bytes.fromhex("01 01")), CastStart(source=1))
        self.assertEqual(decode_event(bytes.fromhex("03 96 00 01")), CastEnd(sample_count=150, reason=1))
        self.assertEqual(decode_event(bytes.fromhex("04 02 01")), ActionComplete(action=2, ok=True))
        sample = decode_event(SAMPLE_BYTES)
        self.assertEqual((sample.index, sample.t_ms), (7, 123456))
        for name in ("ax", "ay", "az", "gx", "gy", "gz"):
            self.assertAlmostEqual(getattr(sample, name), getattr(SAMPLE, name), places=6)

    def test_documented_command_bytes_decode(self):
        self.assertEqual(decode_command(bytes.fromhex("81")), StartRecording())
        self.assertEqual(decode_command(bytes.fromhex("82")), StopRecording())
        self.assertEqual(decode_command(bytes.fromhex("83 00 50 ff 43 49 52 43 4c 45")),
                         GestureResult(label="CIRCLE", rgb=(0, 80, 255)))
        self.assertEqual(decode_command(bytes.fromhex("84 01")), ExecuteAction(action=1))


class EncodingLimitsTest(unittest.TestCase):
    def test_every_message_fits_in_one_ble_packet(self):
        longest_label = "A" * 16
        self.assertLessEqual(len(encode_gesture_result(longest_label, (1, 2, 3))), 20)
        self.assertLessEqual(len(encode_motion_sample(SAMPLE)), 20)

    def test_out_of_range_readings_are_clamped_not_wrapped(self):
        wild = MotionSample(index=0, t_ms=0, ax=1000.0, ay=-1000.0, az=0, gx=50.0, gy=-50.0, gz=0)
        decoded = decode_event(encode_motion_sample(wild))
        self.assertAlmostEqual(decoded.ax, 327.67, places=6)
        self.assertAlmostEqual(decoded.ay, -327.68, places=6)
        self.assertAlmostEqual(decoded.gx, 32.767, places=6)
        self.assertAlmostEqual(decoded.gy, -32.768, places=6)

    def test_gesture_label_must_be_1_to_16_ascii_characters(self):
        for bad in ("", "A" * 17, "CÍRCULO"):
            with self.subTest(label=bad):
                with self.assertRaises(ValueError):
                    encode_gesture_result(bad, (0, 0, 0))


class MalformedInputTest(unittest.TestCase):
    def test_malformed_events_raise_protocol_error(self):
        for data in (b"", bytes.fromhex("02 07 00"), bytes.fromhex("7f"), bytes.fromhex("01")):
            with self.subTest(data=data.hex()):
                with self.assertRaises(ProtocolError):
                    decode_event(data)

    def test_malformed_commands_raise_protocol_error(self):
        for data in (b"", bytes.fromhex("83 00 50"), bytes.fromhex("84"), bytes.fromhex("01 00")):
            with self.subTest(data=data.hex()):
                with self.assertRaises(ProtocolError):
                    decode_command(data)


if __name__ == "__main__":
    unittest.main()
