"""Tests for the parts of the BLE Manager that don't need a real wand. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v

Connecting to the real wand can only be tested once the hardware exists.
"""

import unittest

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from ble_manager import BleWandLink, is_spellwand
from protocol import SERVICE_UUID


def advert(name=None, service_uuids=()):
    device = BLEDevice("AA-BB", name, details=None)
    data = AdvertisementData(local_name=name, manufacturer_data={}, service_data={},
                             service_uuids=list(service_uuids), tx_power=None, rssi=-60, platform_data=())
    return device, data


class FindWandTest(unittest.TestCase):
    def test_wand_is_recognised_by_its_service_uuid(self):
        self.assertTrue(is_spellwand(*advert(name=None, service_uuids=[SERVICE_UUID.upper()])))

    def test_wand_is_recognised_by_its_name(self):
        self.assertTrue(is_spellwand(*advert(name="SpellWand")))

    def test_other_devices_are_ignored(self):
        self.assertFalse(is_spellwand(*advert(name="JBL Charge 5", service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"])))
        self.assertFalse(is_spellwand(*advert(name=None)))


class LinkWithoutWandTest(unittest.TestCase):
    def setUp(self):
        self.link = BleWandLink()

    def tearDown(self):
        self.link.disconnect()

    def test_sending_before_connecting_raises_connection_error(self):
        with self.assertRaises(ConnectionError):
            self.link.send(bytes.fromhex("81"))

    def test_notifications_are_passed_on_as_bytes(self):
        received = []
        self.link.on_event = received.append
        self.link._handle_notification(None, bytearray(b"\x01\x00"))
        self.assertEqual(received, [b"\x01\x00"])
        self.assertIsInstance(received[0], bytes)


if __name__ == "__main__":
    unittest.main()
