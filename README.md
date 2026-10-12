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

## Progress

- [x] PlatformIO project compiles (boot banner + heartbeat)
- [ ] IMU readings on the serial monitor (code compiles; needs hardware test)
- [ ] `CAST_BUTTON` and the three operating states
- [ ] `STATUS_LED`
- [ ] `BLE_LINK`
- [ ] `Sample Recorder`
- [ ] DTW `Gesture Classifier` with rejection
- [ ] `GESTURE_RESULT` back to the wand + spell colors
- [ ] Flask `SpellWand UI`
- [ ] End-to-end test
