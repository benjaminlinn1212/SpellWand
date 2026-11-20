"""Tests for the simulated living room. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import unittest

from home import HOME_DEVICES, Home, describe


class HomeTest(unittest.TestCase):
    def test_the_living_room_has_a_door_curtains_tv_and_lamp_all_off_or_closed(self):
        # in the order they stand in the drawing, left to right
        self.assertEqual(list(HOME_DEVICES), ["door", "curtains", "tv", "lamp"])
        self.assertEqual(Home().state(), {"lamp": False, "door": False, "tv": False, "curtains": False})

    def test_toggle_switches_one_device_and_returns_its_new_state(self):
        home = Home()
        self.assertTrue(home.toggle("lamp"))
        self.assertEqual(home.state(), {"lamp": True, "door": False, "tv": False, "curtains": False})
        self.assertFalse(home.toggle("lamp"))
        self.assertFalse(home.state()["lamp"])

    def test_unknown_devices_are_refused(self):
        with self.assertRaises(ValueError):
            Home().toggle("toaster")

    def test_state_is_a_copy(self):
        home = Home()
        home.state()["tv"] = True
        self.assertFalse(home.state()["tv"])

    def test_states_are_described_in_words(self):
        self.assertEqual(describe("lamp", True), "Lamp on")
        self.assertEqual(describe("door", True), "Door open")
        self.assertEqual(describe("tv", False), "TV off")
        self.assertEqual(describe("curtains", False), "Curtains closed")


if __name__ == "__main__":
    unittest.main()
