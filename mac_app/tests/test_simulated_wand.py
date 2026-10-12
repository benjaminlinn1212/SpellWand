"""Tests for the simulated wand, which stands in for the ESP32 until the hardware arrives.
Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import threading
import unittest

from protocol import (
    ActionComplete, CastEnd, CastStart, MotionSample, decode_event, encode_execute_action,
    encode_gesture_result, encode_start_recording, encode_stop_recording,
)
from simulator import SimulatedWand


class EventLog:
    """Collects decoded events the way the Mac's BLE Manager would receive them."""

    def __init__(self, wand):
        self.events = []
        self.cast_ended = threading.Event()
        wand.on_event = self.receive

    def receive(self, data):
        event = decode_event(data)
        self.events.append(event)
        if isinstance(event, CastEnd):
            self.cast_ended.set()

    def of_type(self, kind):
        return [e for e in self.events if isinstance(e, kind)]


class SimulatedWandTest(unittest.TestCase):
    def setUp(self):
        self.wand = SimulatedWand(seed=1)
        self.log = EventLog(self.wand)
        self.wand.connect()

    def test_cast_sends_start_numbered_samples_and_end(self):
        self.assertTrue(self.wand.cast("CIRCLE"))
        first, *middle, last = self.log.events
        self.assertEqual(first, CastStart(source=0))
        self.assertTrue(all(isinstance(e, MotionSample) for e in middle))
        self.assertEqual([s.index for s in middle], list(range(len(middle))))
        self.assertTrue(all(b.t_ms > a.t_ms for a, b in zip(middle, middle[1:])))
        self.assertEqual(last, CastEnd(sample_count=len(middle), reason=0))
        self.assertGreater(len(middle), 50)
        self.assertEqual(self.wand.state, "INFLIGHT")

    def test_gesture_result_shows_its_colour_then_returns_to_idle(self):
        self.wand.cast("ZIGZAG")
        self.wand.send(encode_gesture_result("ZIGZAG", (10, 20, 30)))
        self.assertEqual(self.wand.feedback_log, [("ZIGZAG", (10, 20, 30))])
        self.assertEqual(self.wand.state, "IDLE")

    def test_wand_shows_exactly_the_colour_the_mac_sends(self):
        # Spell colours live only in the Mac's config.json; the wand has none of its own.
        self.wand.cast("CIRCLE")
        self.wand.send(encode_gesture_result("CIRCLE", (0, 0, 0)))
        self.wand.cast("ZIGZAG")
        self.wand.send(encode_gesture_result("UNKNOWN", (0, 255, 255)))
        self.assertEqual(self.wand.feedback_log, [("CIRCLE", (0, 0, 0)), ("UNKNOWN", (0, 255, 255))])

    def test_cast_is_refused_while_waiting_for_a_result(self):
        self.wand.cast("CIRCLE")
        count = len(self.log.events)
        self.assertFalse(self.wand.cast("CIRCLE"))
        self.assertEqual(len(self.log.events), count)

    def test_mac_controls_training_recordings(self):
        self.wand.perform("HORIZONTAL_LINE")
        self.wand.send(encode_start_recording())
        self.assertEqual(self.log.events[0], CastStart(source=1))
        self.assertEqual(self.wand.state, "CASTING")
        self.wand.send(encode_stop_recording())
        samples = self.log.of_type(MotionSample)
        self.assertGreater(len(samples), 50)
        self.assertEqual(self.log.events[-1], CastEnd(sample_count=len(samples), reason=0))
        self.assertEqual(self.wand.state, "IDLE")

    def test_execute_action_switches_the_action_led_and_replies(self):
        self.wand.send(encode_execute_action(1))
        self.assertTrue(self.wand.action_led_on)
        self.wand.send(encode_execute_action(99))
        self.assertEqual(self.log.of_type(ActionComplete),
                         [ActionComplete(action=1, ok=True), ActionComplete(action=99, ok=False)])

    def test_nothing_is_sent_while_disconnected(self):
        self.wand.disconnect()
        self.wand.cast("CIRCLE")
        self.assertEqual(self.log.events, [])


class RealtimeSimulatedWandTest(unittest.TestCase):
    def test_realtime_cast_streams_in_the_background_at_about_100_hz(self):
        wand = SimulatedWand(realtime=True, seed=2)
        log = EventLog(wand)
        wand.connect()
        wand.cast("HORIZONTAL_LINE")
        self.assertLess(len(log.events), 10)  # cast() returned straight away
        self.assertTrue(log.cast_ended.wait(timeout=5))
        samples = log.of_type(MotionSample)
        duration_ms = samples[-1].t_ms - samples[0].t_ms
        self.assertAlmostEqual(len(samples) / (duration_ms / 1000), 100, delta=15)


if __name__ == "__main__":
    unittest.main()
