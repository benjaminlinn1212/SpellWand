"""Tests for the Sample Recorder's dataset storage. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from classifier import GestureSequence
from recorder import delete_sample, list_samples, load_dataset, load_sample, save_sample


def sample(label="CIRCLE", n=5, start_ms=1000.0):
    rng = np.random.default_rng(n)
    return GestureSequence(
        t_ms=start_ms + 10.0 * np.arange(n),
        imu=rng.normal(0, 3, (n, 6)),
        label=label,
    )


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"

    def tearDown(self):
        self._tmp.cleanup()

    def test_saved_sample_loads_back_unchanged(self):
        original = sample()
        sample_id = save_sample(original, self.data_dir)
        loaded = load_sample(sample_id, self.data_dir)
        self.assertEqual(loaded.label, "CIRCLE")
        np.testing.assert_array_equal(loaded.t_ms, original.t_ms)
        np.testing.assert_array_equal(loaded.imu, original.imu)

    def test_csv_has_one_readable_row_per_motion_sample(self):
        sample_id = save_sample(sample(n=3), self.data_dir)
        with open(self.data_dir / f"{sample_id}.csv", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["t_ms", "ax", "ay", "az", "gx", "gy", "gz", "label"])
        self.assertEqual(len(rows), 1 + 3)
        self.assertEqual(rows[1][0], "1000.0")
        self.assertEqual(rows[1][-1], "CIRCLE")

    def test_each_save_creates_a_new_sample(self):
        first = save_sample(sample(), self.data_dir)
        second = save_sample(sample(), self.data_dir)
        self.assertNotEqual(first, second)
        self.assertEqual(len(list_samples(self.data_dir)), 2)

    def test_list_describes_each_sample(self):
        save_sample(sample("ZIGZAG", n=4), self.data_dir)
        [info] = list_samples(self.data_dir)
        self.assertEqual(info.label, "ZIGZAG")
        self.assertEqual(info.n_samples, 4)
        self.assertEqual(info.duration_ms, 30.0)  # 4 samples, 10 ms apart

    def test_dataset_contains_every_saved_sample_with_its_label(self):
        save_sample(sample("CIRCLE"), self.data_dir)
        save_sample(sample("ZIGZAG"), self.data_dir)
        save_sample(sample("CIRCLE"), self.data_dir)
        labels = sorted(s.label for s in load_dataset(self.data_dir))
        self.assertEqual(labels, ["CIRCLE", "CIRCLE", "ZIGZAG"])

    def test_missing_data_folder_means_empty_dataset(self):
        self.assertEqual(list_samples(self.data_dir), [])
        self.assertEqual(load_dataset(self.data_dir), [])

    def test_delete_removes_only_that_sample(self):
        keep = save_sample(sample("CIRCLE"), self.data_dir)
        remove = save_sample(sample("ZIGZAG"), self.data_dir)
        delete_sample(remove, self.data_dir)
        self.assertEqual([info.sample_id for info in list_samples(self.data_dir)], [keep])

    def test_ids_that_point_outside_the_data_folder_are_refused(self):
        save_sample(sample(), self.data_dir)
        outside = self.data_dir.parent / "precious.csv"
        outside.write_text("do not delete")
        for bad_id in ("../precious", "..", "/etc/passwd", "a/b", ""):
            with self.subTest(sample_id=bad_id):
                with self.assertRaises(ValueError):
                    delete_sample(bad_id, self.data_dir)
                with self.assertRaises(ValueError):
                    load_sample(bad_id, self.data_dir)
        self.assertTrue(outside.exists())

    def test_deleting_a_sample_that_does_not_exist_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            delete_sample("CIRCLE_20260101-000000-000000", self.data_dir)

    def test_label_must_be_a_simple_uppercase_name(self):
        for bad_label in (None, "", "circle", "../EVIL", "TWO WORDS", "A/B"):
            with self.subTest(label=bad_label):
                with self.assertRaises(ValueError):
                    save_sample(sample(label=bad_label), self.data_dir)
        self.assertEqual(list_samples(self.data_dir), [])


if __name__ == "__main__":
    unittest.main()
