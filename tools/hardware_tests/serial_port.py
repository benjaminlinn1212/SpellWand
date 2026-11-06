"""Finds the ESP32's USB serial port. The scripts here that use it need pyserial, which comes
with PlatformIO, so run them with ~/.platformio/penv/bin/python.
"""

import glob
import os
import sys

import serial

BAUD = 115200
PORT_PATTERNS = ["/dev/cu.usbserial*", "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*"]


def open_board(timeout=0.2):
    """Opens the first ESP32 found. Set SPELLWAND_PORT to choose a port yourself."""
    ports = [port for pattern in PORT_PATTERNS for port in sorted(glob.glob(pattern))]
    name = os.environ.get("SPELLWAND_PORT") or (ports[0] if ports else None)
    if name is None:
        sys.exit("No ESP32 found. Check the USB cable, and that nothing else has the port open.")
    return serial.Serial(name, BAUD, timeout=timeout)
