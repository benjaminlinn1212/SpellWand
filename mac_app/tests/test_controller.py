"""End-to-end tests of the Mac app's logic against the simulated wand. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import copy
import queue
import tempfile
import unittest
from pathlib import Path

import numpy as np

from config import DEFAULT_CONFIG, save_config
from controller import SpellWandController
from recorder import list_samples, save_sample
from simulator import GESTURES, make_gesture


def run_inline(task):
    """Run background work immediately so tests are deterministic."""
    task()


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.data_dir = root / "data"
        self.config_path = root / "config.json"
        rng = np.random.default_rng(5)
        for gesture in GESTURES:
            for _ in range(5):
                save_sample(make_gesture(gesture, rng), self.data_dir)
        save_config(DEFAULT_CONFIG, self.config_path)
        self.app = SpellWandController(data_dir=self.data_dir, config_path=self.config_path,
                                       run_in_background=run_inline, simulator_realtime=False, simulator_seed=11)
        self.events = self.app.subscribe()
        self.app.connect("simulated")
        self.wand = self.app.simulated_wand

    def tearDown(self):
        self.app.disconnect()
        self._tmp.cleanup()

    def published(self, kind):
        found = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return found
            if event["type"] == kind:
                found.append(event["data"])

    def test_cast_is_recognized_and_the_wand_shows_the_configured_colour(self):
        self.wand.cast("CIRCLE")
        [result] = self.published("result")
        self.assertEqual(result["label"], "CIRCLE")
        self.assertEqual(self.wand.feedback_log, [("CIRCLE", (0x00, 0x50, 0xFF))])
        self.assertEqual(self.wand.state, "IDLE")
        self.assertEqual(self.app.status()["wand_state"], "IDLE")

    def test_every_gesture_is_recognized(self):
        for gesture in GESTURES:
            with self.subTest(gesture=gesture):
                self.wand.cast(gesture)
                [result] = self.published("result")
                self.assertEqual(result["label"], gesture)

    def test_casual_movement_is_unknown_flashes_red_and_runs_no_action(self):
        for _ in range(5):
            self.wand.cast("WOBBLE")
        labels = [r["label"] for r in self.published("result")]
        self.assertEqual(labels, ["UNKNOWN"] * 5)
        self.assertEqual({rgb for _, rgb in self.wand.feedback_log}, {(255, 0, 0)})
        self.assertEqual(self.published("action"), [])
        self.assertFalse(self.wand.action_led_on)

    def test_recognized_gesture_runs_its_action(self):
        # Default config: CIRCLE toggles the wand's action LED.
        self.wand.cast("CIRCLE")
        [action] = self.published("action")
        self.assertTrue(action["ok"], action["detail"])
        self.assertTrue(self.wand.action_led_on)

    def test_result_includes_the_motion_for_the_ui(self):
        self.wand.cast("ZIGZAG")
        [result] = self.published("result")
        n = result["sample_count"]
        self.assertGreater(n, 50)
        self.assertEqual(len(result["trace"]["x"]), n)
        self.assertEqual(len(result["accel"][0]), n)

    def test_training_recording_saves_a_labelled_sample_and_retrains(self):
        before = len(list_samples(self.data_dir))
        self.app.start_recording("ZIGZAG")
        self.assertEqual(self.app.status()["recording"], "ZIGZAG")
        self.app.stop_recording()
        [saved] = self.published("sample_saved")
        self.assertEqual(saved["label"], "ZIGZAG")
        self.assertEqual(len(list_samples(self.data_dir)), before + 1)
        self.assertEqual(self.app.status()["dataset"]["ZIGZAG"], 6)
        self.assertIsNone(self.app.status()["recording"])

    def test_recording_needs_a_connection_and_a_configured_gesture(self):
        with self.assertRaises(ValueError):
            self.app.start_recording("TRIANGLE")
        self.app.disconnect()
        with self.assertRaises(ConnectionError):
            self.app.start_recording("CIRCLE")

    def test_disconnecting_mid_recording_saves_nothing(self):
        before = len(list_samples(self.data_dir))
        self.app.start_recording("CIRCLE")
        self.app.disconnect()
        self.assertEqual(len(list_samples(self.data_dir)), before)
        self.assertIsNone(self.app.status()["recording"])
        self.assertFalse(self.app.status()["connected"])

    def test_threshold_change_applies_immediately(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["dtw_threshold"] = 0.0001
        self.app.update_config(config)
        self.wand.cast("CIRCLE")
        [result] = self.published("result")
        self.assertEqual(result["label"], "UNKNOWN")
        self.assertEqual(result["nearest_label"], "CIRCLE")

    def test_gestures_removed_from_the_config_are_no_longer_recognized(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        del config["gestures"]["CIRCLE"]
        self.app.update_config(config)
        self.wand.cast("CIRCLE")
        [result] = self.published("result")
        self.assertNotEqual(result["nearest_label"], "CIRCLE")

    def test_deleting_samples_updates_the_dataset(self):
        circle_ids = [s.sample_id for s in list_samples(self.data_dir) if s.label == "CIRCLE"]
        for sample_id in circle_ids:
            self.app.delete_sample(sample_id)
        self.assertEqual(self.app.status()["dataset"].get("CIRCLE", 0), 0)
        self.wand.cast("CIRCLE")
        [result] = self.published("result")
        self.assertNotEqual(result["nearest_label"], "CIRCLE")

    def test_dataset_check_reports_every_sample(self):
        checks = self.app.check_dataset()
        self.assertEqual(len(checks), 15)
        self.assertTrue(all(c["label"] == c["nearest_label"] for c in checks))

    def test_sample_detail_includes_the_3d_trace(self):
        sample_id = list_samples(self.data_dir)[0].sample_id
        detail = self.app.sample_detail(sample_id)
        self.assertEqual(detail["sample_id"], sample_id)
        self.assertEqual(len(detail["trace"]["x"]), detail["sample_count"])

    def test_events_are_published_in_order_for_the_ui(self):
        self.published("status")  # clear what connecting published
        self.wand.cast("HORIZONTAL_LINE")
        kinds = []
        while not self.events.empty():
            kinds.append(self.events.get_nowait()["type"])
        self.assertEqual(kinds[0], "cast_start")
        self.assertIn("motion", kinds)
        self.assertLess(kinds.index("motion"), kinds.index("result"))


if __name__ == "__main__":
    unittest.main()
