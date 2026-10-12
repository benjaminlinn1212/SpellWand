"""Checks the bundled simulated dataset (sample_data/) together with the default settings.
Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import unittest
from collections import Counter

import numpy as np

from classifier import UNKNOWN, GestureClassifier, leave_one_out
from config import DEFAULT_CONFIG
from make_sample_data import EXAMPLES_PER_GESTURE, SAMPLE_DATA_DIR
from recorder import load_dataset
from simulator import GESTURES, casual_movement, make_gesture


class BundledSampleDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(SAMPLE_DATA_DIR)
        cls.classifier = GestureClassifier(threshold=DEFAULT_CONFIG["dtw_threshold"])
        cls.classifier.fit(cls.dataset)

    def test_every_gesture_has_its_examples(self):
        self.assertEqual(Counter(s.label for s in self.dataset), {g: EXAMPLES_PER_GESTURE for g in GESTURES})

    def test_every_example_is_closest_to_its_own_gesture(self):
        for check in leave_one_out(self.dataset):
            with self.subTest(index=check.index, label=check.label):
                self.assertEqual(check.nearest_label, check.label)
                self.assertLessEqual(check.distance, DEFAULT_CONFIG["dtw_threshold"])

    def test_default_threshold_accepts_new_gestures(self):
        rng = np.random.default_rng(77)  # different from the seed that made sample_data
        for gesture in GESTURES:
            for _ in range(10):
                with self.subTest(gesture=gesture):
                    self.assertEqual(self.classifier.classify(make_gesture(gesture, rng)).label, gesture)

    def test_default_threshold_rejects_casual_movement(self):
        rng = np.random.default_rng(78)
        labels = [self.classifier.classify(casual_movement(rng)).label for _ in range(40)]
        self.assertEqual(labels, [UNKNOWN] * 40)


if __name__ == "__main__":
    unittest.main()
