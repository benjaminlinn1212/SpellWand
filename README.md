# SpellWand

A handheld wand that recognizes air-drawn gestures and uses them to control devices.

- `firmware/`: ESP32 firmware (PlatformIO + Arduino). Reads the `IMU`, handles `CAST_BUTTON`,
  runs the `IDLE` / `CASTING` / `INFLIGHT` state machine, drives `STATUS_LED`, talks to the Mac over `BLE_LINK`.
- `mac_app/`: Mac-side Python app (Flask + Bleak): `SpellWand UI`, `BLE Manager`, `Sample Recorder`,
  `Gesture Classifier` (DTW with rejection), `Action Dispatcher`.
- `docs/protocol.md`: the `BLE_LINK` message format. `docs/prior-work.md`: how other gesture wands work.

## Try it without hardware

The Mac app has a simulated wand that speaks the same Bluetooth protocol as the firmware.

```bash
cd mac_app
.venv/bin/python app.py --simulate
```

Open <http://127.0.0.1:8780>. Use the "Draw a circle / zigzag / ..." buttons to cast, record training
examples, view the dataset in 3D and change settings. Simulation mode keeps its own data and settings
in `mac_app/sim_data/` (it starts from the 18 simulated samples in `mac_app/sample_data/`), so your
real data in `mac_app/data/` and `mac_app/config.json` are never touched. Delete `sim_data/` to reset it.

## Hardware

| Part | Connection |
|---|---|
| ESP32-WROOM-32 dev board | PlatformIO board `esp32dev` |
| BNO086 IMU | I²C: SDA → GPIO 21, SCL → GPIO 22, 3.3 V, GND |
| BNO086 INT / RST | INT → GPIO 4, RST → GPIO 23 (set to `-1` in `main.cpp` if not wired) |
| BNO086 mounting | x axis along the wand toward the tip; y left and z up when the wand is held level (the Mac app assumes this) |
| `CAST_BUTTON` | GPIO 27 → button → GND (internal pull-up) |
| `STATUS_LED` (WS2812B) | Data in → GPIO 18, 5 V (or 3.3 V), GND |
| Action LED (demo output) | GPIO 26 → 330 Ω resistor → LED → GND |

`STATUS_LED` colours: dim white `IDLE`, blue `CASTING`, amber `INFLIGHT` (waiting for the Mac), then the
spell colour for 1 s, three red flashes for `UNKNOWN`, or two magenta flashes if the Mac didn't answer within 2 s.

## Setup

`pio` lives at `~/.platformio/penv/bin/pio` unless you add it to your `PATH`.

```bash
cd firmware
~/.platformio/penv/bin/pio run                       # compile
~/.platformio/penv/bin/pio run -t upload -t monitor  # flash and open serial monitor (115200 baud)
```

The Mac app needs Python 3.13 from python.org (`/usr/local/bin/python3.13`):

```bash
cd mac_app
/usr/local/bin/python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

**Bluetooth permission:** macOS only lets a program use Bluetooth if the app that launched it
declares Bluetooth use. Run `app.py` and `ble_manager.py` from VS Code's terminal or the Claude desktop
app's Terminal panel and click **Allow** when asked. Running them from Claude Code's command runner, or
another app without that declaration, makes Python crash immediately with exit code 134
(SIGABRT, `NSBluetoothAlwaysUsageDescription` in the crash report).

## Tests (no hardware needed)

```bash
cd mac_app && .venv/bin/python -m unittest discover -s tests -v      # Mac app: 115 tests
cd firmware && ~/.platformio/penv/bin/pio test -e native              # wand logic: 23 tests, run on the Mac
```

Both suites check the same example bytes from `docs/protocol.md`, so the two sides agree on the format.

## When the hardware arrives

Work through these in order; each step only needs the ones before it.

1. **Board alone.** Flash and open the serial monitor. Expect `=== SpellWand firmware booted ===`,
   `BLE advertising as SpellWand` and an IMU error (no IMU yet). The `STATUS_LED` should glow dim white.
2. **IMU.** Wire the BNO086. Expect `BNO08x answered at 0x4B` (or `0x4A`) and `IMU reports: ... on`.
   If readings are flaky, set `I2C_FAST_CLOCK_HZ` to `100000` in `firmware/src/main.cpp`.
3. **Button and LED.** Hold `CAST_BUTTON`: serial shows `CAST_START`, the LED turns blue; release: `CAST_END`,
   amber, then two magenta flashes after 2 s (nobody answered yet).
4. **Bluetooth.** `cd mac_app && .venv/bin/python ble_manager.py --listen`, then cast: you should see
   `CastStart`, about 100 `MotionSample`s per second and `CastEnd`.
5. **Training.** `.venv/bin/python app.py`, press **Connect wand**, and record 5 or more examples of each
   gesture. Use **Check dataset** and delete anything flagged.
6. **Casting.** Cast for real and watch the distances in the UI. Raise or lower the rejection threshold
   until gestures are accepted and casual movement comes back `UNKNOWN`. (On simulated data, gestures
   score about 0.1–0.5 and casual movement 2.5 or more; real data will be noisier.)
7. **Action.** Wire the action LED; `CIRCLE` toggles it by default.

## How it fits together

```
ESP32  ──BLE_LINK──>  ble_manager.py ──> controller.py ──> classifier.py      (DTW + rejection)
 (wand_core state machine)              │      │        ──> recorder.py        (CSV samples in data/)
                                        │      └──────> action_dispatcher.py (wand LED, notification, webhook)
                                        └── app.py + templates/ + static/  (SpellWand UI, live via server-sent events)
```

`simulator.py` can stand in for the ESP32 at the left end (`app.py --simulate`, and the tests).

## Progress

| Step | Status |
|---|---|
| PlatformIO project, IMU reading, `CAST_BUTTON`, states, `STATUS_LED`, `BLE_LINK`, `GESTURE_RESULT` colours, action LED | Written and compiles; logic tested on the Mac (`pio test -e native`); **needs hardware test** |
| `BLE Manager` | Scanning tested on this Mac; connecting tested against the simulated wand only; **needs hardware test** |
| `Sample Recorder`, `Gesture Classifier`, `Action Dispatcher`, `config.json` | Tested (simulated data) |
| Flask `SpellWand UI` | Tested through its API and by hand in a browser with the simulated wand |
| End-to-end | Tested with the simulated wand; **real end-to-end needs hardware** |
| Rejection threshold | Default 1.0 works on simulated data; **tune with real recordings** |
