"""Tests for config.json handling. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from config import DEFAULT_CONFIG, ConfigError, load_config, save_config, validate_config


class ConfigFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "config.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_gives_the_defaults(self):
        config = load_config(self.path)
        self.assertEqual(config, DEFAULT_CONFIG)
        self.assertEqual(sorted(config["gestures"]), ["CIRCLE", "HORIZONTAL_LINE", "ZIGZAG"])

    def test_saved_settings_load_back(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["dtw_threshold"] = 0.75
        config["gestures"]["TRIANGLE"] = {"color": "#aa00ff", "action": {"type": "none"}}
        save_config(config, self.path)
        self.assertEqual(load_config(self.path), config)

    def test_file_is_readable_json(self):
        save_config(DEFAULT_CONFIG, self.path)
        self.assertEqual(json.loads(self.path.read_text())["dtw_threshold"], DEFAULT_CONFIG["dtw_threshold"])

    def test_invalid_settings_are_not_saved(self):
        save_config(DEFAULT_CONFIG, self.path)
        bad = copy.deepcopy(DEFAULT_CONFIG)
        bad["dtw_threshold"] = -1
        with self.assertRaises(ConfigError):
            save_config(bad, self.path)
        self.assertEqual(load_config(self.path), DEFAULT_CONFIG)

    def test_colours_are_stored_in_lowercase(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["gestures"]["CIRCLE"]["color"] = "#00AAFF"
        self.assertEqual(validate_config(config)["gestures"]["CIRCLE"]["color"], "#00aaff")


class ValidationTest(unittest.TestCase):
    def assert_rejected(self, change):
        config = copy.deepcopy(DEFAULT_CONFIG)
        change(config)
        with self.assertRaises(ConfigError):
            validate_config(config)

    def test_threshold_must_be_a_positive_number(self):
        for value in (0, -0.5, "1", None, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assert_rejected(lambda c: c.update(dtw_threshold=value))

    def test_gesture_labels_must_be_plain_names_that_fit_in_a_ble_message(self):
        for label in ("circle", "TWO WORDS", "../X", "A" * 17, "UNKNOWN", ""):
            with self.subTest(label=label):
                self.assert_rejected(lambda c: c["gestures"].update({label: {"color": "#ffffff", "action": {"type": "none"}}}))

    def test_colours_must_be_hex(self):
        for colour in ("blue", "#12345", "#gg0000", None):
            with self.subTest(colour=colour):
                self.assert_rejected(lambda c: c["gestures"]["CIRCLE"].update(color=colour))

    def test_actions_must_be_known_and_complete(self):
        bad_actions = [
            {"type": "launch_rocket"},
            {"type": "wand_led", "mode": "explode"},
            {"type": "notify"},
            {"type": "webhook", "url": "ftp://example.com/x"},
            {"type": "webhook"},
        ]
        for action in bad_actions:
            with self.subTest(action=action):
                self.assert_rejected(lambda c: c["gestures"]["CIRCLE"].update(action=action))

    def test_valid_actions_are_accepted(self):
        good_actions = [
            {"type": "none"},
            {"type": "wand_led", "mode": "toggle"},
            {"type": "wand_led", "mode": "pulse"},
            {"type": "notify", "message": "Lumos!"},
            {"type": "webhook", "url": "http://homeassistant.local:8123/api/webhook/spellwand"},
        ]
        for action in good_actions:
            with self.subTest(action=action):
                config = copy.deepcopy(DEFAULT_CONFIG)
                config["gestures"]["CIRCLE"]["action"] = action
                self.assertEqual(validate_config(config)["gestures"]["CIRCLE"]["action"], action)

    def test_needs_at_least_one_gesture(self):
        self.assert_rejected(lambda c: c.update(gestures={}))


if __name__ == "__main__":
    unittest.main()
