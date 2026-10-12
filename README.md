# SpellWand

A handheld wand that recognizes air-drawn gestures and uses them to control devices.

- `firmware/`: ESP32 firmware (PlatformIO + Arduino). Reads the `IMU`, handles `CAST_BUTTON`,
  runs the `IDLE` / `CASTING` / `INFLIGHT` state machine, drives `STATUS_LED`, talks to the Mac over `BLE_LINK`.
- `mac_app/`: Mac-side Python app (Flask + Bleak): `SpellWand UI`, `BLE Manager`, `Sample Recorder`,
  `Gesture Classifier` (DTW with rejection), `Action Dispatcher`.

## Hardware

| Part | Connection |
|---|---|
| ESP32-WROOM-32 dev board | PlatformIO board `esp32dev` |
| BNO086 IMU | I²C: SDA → GPIO 21, SCL → GPIO 22, 3.3 V, GND |
| BNO086 INT / RST | INT → GPIO 4, RST → GPIO 23 (set to `-1` in `main.cpp` if not wired) |
| `CAST_BUTTON` | GPIO 27 → GND (internal pull-up) |
| `STATUS_LED` (WS2812B) | Data in → GPIO 18 |

## Firmware

`pio` lives at `~/.platformio/penv/bin/pio` unless you add it to your `PATH`.

```bash
cd firmware
~/.platformio/penv/bin/pio run                       # compile
~/.platformio/penv/bin/pio run -t upload -t monitor  # flash and open serial monitor (115200 baud)
```

## Mac app

Needs Python 3.13 from python.org (`/usr/local/bin/python3.13`).

```bash
cd mac_app
/usr/local/bin/python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python ble_manager.py   # 5-second BLE scan
```

**Bluetooth permission:** macOS only lets a program use Bluetooth if the app that launched it
declares Bluetooth use. Run BLE code from VS Code's terminal or the Claude desktop app's Terminal panel
and click **Allow** when asked. Running it from Claude Code's command runner, or from another app
without that declaration, makes Python crash immediately with exit code 134
(SIGABRT, `NSBluetoothAlwaysUsageDescription` in the crash report).

## Progress

- [x] PlatformIO project compiles (boot banner + heartbeat)
- [ ] IMU readings on the serial monitor (code compiles; needs hardware test)
- [ ] `CAST_BUTTON` and the three operating states
- [ ] `STATUS_LED`
- [x] Mac Python environment; Bleak BLE scan works
- [ ] `BLE_LINK`
- [ ] `Sample Recorder`
- [ ] DTW `Gesture Classifier` with rejection
- [ ] `GESTURE_RESULT` back to the wand + spell colors
- [ ] Flask `SpellWand UI`
- [ ] End-to-end test
