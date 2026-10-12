"""BLE Manager: finds and talks to the SpellWand ESP32 over BLE_LINK.

So far this only scans. Run it directly to list nearby BLE devices:

    .venv/bin/python ble_manager.py

Note: macOS hides real Bluetooth MAC addresses, so the "address" Bleak reports
on a Mac is a per-computer UUID. We will find the wand by its advertised name.
"""

import asyncio

from bleak import BleakScanner

SCAN_SECONDS = 5.0


async def scan(timeout=SCAN_SECONDS):
    """Return [(address, name, rssi), ...] for nearby BLE devices, strongest signal first."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    devices = [
        (device.address, adv.local_name or device.name, adv.rssi)
        for device, adv in found.values()
    ]
    return sorted(devices, key=lambda d: d[2], reverse=True)


if __name__ == "__main__":
    print(f"Scanning for {SCAN_SECONDS:.0f} s...")
    devices = asyncio.run(scan())
    for address, name, rssi in devices:
        print(f"{rssi:4d} dBm  {address}  {name or '(no name)'}")
    print(f"{len(devices)} device(s) found")
