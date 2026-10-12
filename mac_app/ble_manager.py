"""BLE Manager: finds the SpellWand ESP32 and talks to it over BLE_LINK (docs/protocol.md).

    .venv/bin/python ble_manager.py            # list nearby BLE devices
    .venv/bin/python ble_manager.py --listen   # connect to the wand and print its events

Run these from VS Code's terminal or the Claude desktop Terminal panel: macOS only lets
apps that declare Bluetooth use it (see README).

Note: macOS hides real Bluetooth MAC addresses, so the "address" Bleak reports on a Mac
is a per-computer UUID. We find the wand by its service UUID or advertised name.
"""

import asyncio
import sys
import threading

from bleak import BleakClient, BleakScanner

from protocol import COMMANDS_UUID, DEVICE_NAME, EVENTS_UUID, SERVICE_UUID, decode_event

SCAN_SECONDS = 5.0
CONNECT_SCAN_SECONDS = 10.0


async def scan(timeout=SCAN_SECONDS):
    """Return [(address, name, rssi), ...] for nearby BLE devices, strongest signal first."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    devices = [
        (device.address, adv.local_name or device.name, adv.rssi)
        for device, adv in found.values()
    ]
    return sorted(devices, key=lambda d: d[2], reverse=True)


def is_spellwand(device, advertisement):
    """True if a scanned device is our wand."""
    uuids = {u.lower() for u in advertisement.service_uuids}
    return SERVICE_UUID in uuids or (advertisement.local_name or device.name) == DEVICE_NAME


class BleWandLink:
    """BLE_LINK to the real wand. Same interface as simulator.SimulatedWand: connect(),
    disconnect(), send(bytes), and the on_event(bytes) / on_disconnect() callbacks.

    Bleak is asynchronous, so the link runs its own asyncio event loop on a background
    thread, and connect() / send() wait for it. Events are delivered on that thread.
    """

    name = "SpellWand (Bluetooth)"

    def __init__(self, scan_timeout_s=CONNECT_SCAN_SECONDS):
        self.on_event = None
        self.on_disconnect = None
        self._scan_timeout_s = scan_timeout_s
        self._client = None
        self._closing = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def connect(self):
        """Find the wand and connect. Raises ConnectionError if it can't be found."""
        self._run(self._connect(), timeout=self._scan_timeout_s + 30)

    def send(self, data):
        """Write one command to the wand."""
        client = self._client
        if client is None or not client.is_connected:
            raise ConnectionError("wand not connected")
        if threading.current_thread() is self._thread:
            raise RuntimeError("send() must not be called from the BLE thread (it would wait on itself)")
        self._run(client.write_gatt_char(COMMANDS_UUID, bytes(data), response=True), timeout=5)

    def disconnect(self):
        self._closing = True
        client, self._client = self._client, None
        if client is not None and self._loop.is_running():
            try:
                self._run(client.disconnect(), timeout=5)
            except Exception:
                pass  # already gone
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)

    async def _connect(self):
        device = await BleakScanner.find_device_by_filter(is_spellwand, timeout=self._scan_timeout_s)
        if device is None:
            raise ConnectionError("No SpellWand found. Is it powered on and within a few metres?")
        client = BleakClient(device, disconnected_callback=self._handle_disconnect)
        await client.connect()
        await client.start_notify(EVENTS_UUID, self._handle_notification)
        self._client = client

    def _handle_notification(self, sender, data):
        if self.on_event:
            self.on_event(bytes(data))

    def _handle_disconnect(self, client):
        self._client = None
        if not self._closing and self.on_disconnect:
            self.on_disconnect()

    def _run(self, coroutine, timeout):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout)


def _listen():
    """Connect to the wand and print every event until Ctrl+C (handy for the first hardware test)."""
    link = BleWandLink()
    link.on_event = lambda data: print(decode_event(data))
    link.on_disconnect = lambda: print("Wand disconnected")
    print(f"Looking for {DEVICE_NAME} for up to {CONNECT_SCAN_SECONDS:.0f} s...")
    try:
        link.connect()
        print("Connected. Hold CAST_BUTTON and move the wand; Ctrl+C to quit.")
        threading.Event().wait()
    except ConnectionError as error:
        print(error)
    except KeyboardInterrupt:
        pass
    finally:
        link.disconnect()


if __name__ == "__main__":
    if "--listen" in sys.argv:
        _listen()
    else:
        print(f"Scanning for {SCAN_SECONDS:.0f} s...")
        devices = asyncio.run(scan())
        for address, name, rssi in devices:
            print(f"{rssi:4d} dBm  {address}  {name or '(no name)'}")
        print(f"{len(devices)} device(s) found")
