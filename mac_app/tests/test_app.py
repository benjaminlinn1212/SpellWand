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

    def test_clear_dataset(self):
        response = self.post("/api/dataset/clear")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["moved"], 12)
        self.assertEqual(self.client.get("/api/samples").get_json(), [])

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

    def test_the_old_living_room_address_is_gone(self):
        self.assertEqual(self.client.get("/home").status_code, 404)

    def test_home_page_loads(self):
        response = self.client.get("/living-room")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Living room", response.data)

    def test_pages_arrive_with_the_current_connection_in_the_top_bar(self):
        # so the top bar does not change as the page opens, or between the two pages
        for url in ("/", "/living-room"):
            html = self.client.get(url).get_data(as_text=True)
            # one status: a dot and a phrase, saying both the connection and the wand's state
            self.assertIn('<span id="link-dot" class="dot ready"></span><span id="link-text">Simulated wand ready</span>', html)
            self.assertNotIn('id="wand-state"', html)
            self.assertIn('<button id="connect-ble" type="button" hidden>', html)
            self.assertIn('<button id="disconnect" type="button" class="quiet">', html)
        for url in ("/", "/living-room"):   # the simulated wand's motions, ready to press, on both pages
            html = self.client.get(url).get_data(as_text=True)
            self.assertIn('<body class="has-sim">', html)
            self.assertIn('<div id="sim-panel" class="sim-dock" role="toolbar"', html)
            self.assertRegex(html, r'data-motion="CIRCLE" title="Draw a circle"[^>]*>\s*<svg[^>]*>.*?</svg>\s*<span class="sim-name">Circle</span>')
            self.assertRegex(html, r'data-motion="STILL" title="Hold it still[^"]*"[^>]*>\s*<svg[^>]*>.*?</svg>\s*<span class="sim-name">Still</span>')
        self.post("/api/disconnect")
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('<span id="link-dot" class="dot"></span><span id="link-text">No wand connected</span>', html)
        self.assertIn('<button id="disconnect" type="button" class="quiet" hidden>', html)
        self.assertIn('<body>', html)
        self.assertRegex(html, r'<div id="sim-panel" class="sim-dock" role="toolbar"[^>]* hidden>')

    def test_dataset_and_settings_open_in_panels(self):
        grimoire = self.client.get("/").get_data(as_text=True)
        living_room = self.client.get("/living-room").get_data(as_text=True)
        for html in (grimoire, living_room):   # the same two buttons in the top bar on both pages
            self.assertIn('data-drawer="dataset-drawer" data-drawer-page="/"', html)
            self.assertIn('data-drawer="settings-drawer"', html)
            self.assertIn('id="settings-drawer"', html)   # settings work on both pages
            self.assertIn('id="save-settings"', html)
            self.assertIn('data-drawer="help-drawer"', html)   # and help, on both pages
            self.assertIn('id="help-drawer"', html)
        # the dataset panel replays samples in the motion view, so it is on the Grimoire page only
        self.assertIn('id="dataset-drawer"', grimoire)
        self.assertNotIn('id="dataset-drawer"', living_room)
        # nothing of it is left on the page itself
        main = grimoire[grimoire.index('<main class="grid">'):grimoire.index("</main>")]
        self.assertNotIn("sample-rows", main)
        self.assertNotIn("record-start", main)

    def test_living_room_arrives_drawn_as_it_is(self):
        self.post("/api/home", {"device": "lamp"})
        html = self.client.get("/living-room").get_data(as_text=True)
        self.assertIn('<svg id="room" class="lamp-on"', html)

    def test_home_devices_through_the_api(self):
        self.assertEqual(self.client.get("/api/home").get_json(),
                         {"devices": {"lamp": False, "door": False, "tv": False, "curtains": False}})
        response = self.post("/api/home", {"device": "curtains"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["devices"]["curtains"])
        self.assertEqual(self.post("/api/home", {"device": "toaster"}).status_code, 400)
        meta = self.client.get("/api/meta").get_json()
        self.assertIn("home", meta["action_types"])
        self.assertEqual([d["device"] for d in meta["home_devices"]], ["door", "curtains", "tv", "lamp"])

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
