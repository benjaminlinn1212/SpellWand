"""Tests for the SpellWand UI's web API, using the simulated wand. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import copy
import json
import queue
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app import create_app
from config import DEFAULT_CONFIG, save_config
from controller import SpellWandController
from recorder import save_sample
from simulator import GESTURES, make_gesture


class AppTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.data_dir = root / "data"
        rng = np.random.default_rng(3)
        for gesture in GESTURES:
            for _ in range(4):
                save_sample(make_gesture(gesture, rng), self.data_dir)
        config_path = root / "config.json"
        save_config(DEFAULT_CONFIG, config_path)
        self.controller = SpellWandController(data_dir=self.data_dir, config_path=config_path,
                                              run_in_background=lambda task: task(),
                                              simulator_realtime=False, simulator_seed=4,
                                              notifier=lambda message: True)
        self.controller.connect("simulated")
        self.client = create_app(self.controller).test_client()

    def tearDown(self):
        self.controller.disconnect()
        self._tmp.cleanup()

    def post(self, url, body=None):
        return self.client.post(url, json=body or {})

    def test_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SpellWand", response.data)

    def test_status_reports_the_connection_and_dataset(self):
        status = self.client.get("/api/status").get_json()
        self.assertTrue(status["connected"])
        self.assertEqual(status["mode"], "simulated")
        self.assertEqual(status["dataset"], {g: 4 for g in GESTURES})

    def test_simulated_cast_is_classified(self):
        events = self.controller.subscribe()
        self.assertEqual(self.post("/api/simulate", {"motion": "CIRCLE"}).status_code, 200)
        results = []
        while not events.empty():
            event = events.get_nowait()
            if event["type"] == "result":
                results.append(event["data"]["label"])
        self.assertEqual(results, ["CIRCLE"])

    def test_training_through_the_api_saves_a_sample(self):
        self.assertEqual(self.post("/api/recording/start", {"label": "ZIGZAG"}).status_code, 200)
        self.assertEqual(self.post("/api/recording/stop").status_code, 200)
        samples = self.client.get("/api/samples").get_json()
        self.assertEqual(sum(s["label"] == "ZIGZAG" for s in samples), 5)

    def test_problems_come_back_as_readable_errors(self):
        response = self.post("/api/recording/start", {"label": "TRIANGLE"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("TRIANGLE", response.get_json()["error"])

        self.post("/api/disconnect")
        response = self.post("/api/recording/start", {"label": "CIRCLE"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("connect", response.get_json()["error"])

    def test_sample_detail_and_delete(self):
        sample_id = self.client.get("/api/samples").get_json()[0]["sample_id"]
        detail = self.client.get(f"/api/samples/{sample_id}").get_json()
        self.assertEqual(len(detail["trace"]["x"]), detail["sample_count"])
        self.assertEqual(self.client.delete(f"/api/samples/{sample_id}", json={}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/samples/{sample_id}").status_code, 404)
        self.assertEqual(self.client.delete("/api/samples/..%2Fsecret", json={}).status_code, 400)

    def test_dataset_check(self):
        checks = self.post("/api/dataset/check").get_json()
        self.assertEqual(len(checks), 12)
        self.assertEqual({c["label"] for c in checks}, set(GESTURES))

    def test_settings_round_trip(self):
        config = self.client.get("/api/config").get_json()
        config["dtw_threshold"] = 0.8
        response = self.client.put("/api/config", json=config)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/config").get_json()["dtw_threshold"], 0.8)

        bad = copy.deepcopy(config)
        bad["gestures"]["CIRCLE"]["color"] = "blue"
        response = self.client.put("/api/config", json=bad)
        self.assertEqual(response.status_code, 400)
        self.assertIn("colour", response.get_json()["error"])

    def test_action_types_are_listed_for_the_settings_form(self):
        meta = self.client.get("/api/meta").get_json()
        self.assertIn("webhook", meta["action_types"])
        self.assertNotIn("wand_led", meta["action_types"])
        self.assertEqual(meta["simulated_motions"][:3], list(GESTURES))

    def test_form_posts_from_other_websites_are_refused(self):
        response = self.client.post("/api/disconnect", data={"x": "1"})
        self.assertEqual(response.status_code, 415)
        self.assertTrue(self.client.get("/api/status").get_json()["connected"])

    def test_requests_for_other_host_names_are_refused(self):
        # Protects against DNS rebinding: a web page on evil.example pointing its name at 127.0.0.1.
        response = self.client.get("/api/status", headers={"Host": "evil.example:8780"})
        self.assertEqual(response.status_code, 403)

    def test_event_stream_starts_with_the_current_status(self):
        response = self.client.get("/api/events", buffered=False)
        self.assertEqual(response.mimetype, "text/event-stream")
        first = next(response.response).decode()
        response.close()
        self.assertTrue(first.startswith("event: status\n"))
        payload = json.loads(first.split("data: ", 1)[1])
        self.assertTrue(payload["connected"])


if __name__ == "__main__":
    unittest.main()
