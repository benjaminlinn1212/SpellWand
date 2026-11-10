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
| BNO080 / BNO085 IMU | I²C: SDA → GPIO 21, SCL → GPIO 22, VCC → ESP32 3V3 (not 5V), GND → GND |
| IMU INT / RST | INT → GPIO 4, RST → GPIO 26. Wire both: they make the link much more reliable. If one is not wired, set it to `-1` in `firmware/src/main.cpp` |
| IMU mode pins | PS0 and PS1 → GND, which selects I²C. Clone boards like the GY-BNO080/085 may not do this for you |
| IMU pins left open | BOOT, and ADO/ADDR if your board has it: the firmware tries address 0x4B, then 0x4A |
| IMU mounting | x axis (printed on the board) along the wand toward the tip; y left and z up when the wand is held level (the Mac app assumes this) |
| `CAST_BUTTON` | GPIO 27 → button → GND (internal pull-up) |
| `STATUS_LED` (4-leg RGB LED) | GPIO 18 → 220 Ω → red leg; GPIO 19 → 68–100 Ω → green leg; GPIO 23 → 68–100 Ω → blue leg; long (common) leg → GND |
| Power: 4× AAA holder with switch | + → ESP32 **5V/VIN** pin; − → ESP32 GND (see Power below) |

**RGB LED legs:** the longest leg is the common one. On most 5 mm RGB LEDs the order is red, common, green,
blue, but check yours: with the common leg on GND, touch each other leg to 3V3 through a resistor and see
which colour lights.

**RGB LED type:** if your LED is *common anode* (the long leg must go to 3.3 V instead of GND), wire the long
leg to the ESP32's 3V3 pin and set `STATUS_LED_COMMON_ANODE = true` in `firmware/src/main.cpp`. Green and blue
need about 3 V of the 3.3 V available, hence their smaller resistors; they will still look a little dimmer than red.

## Power

4× AAA (about 6 V fresh) go straight into the **5V/VIN** pin; the board's 1117 regulator turns that into 3.3 V
for the ESP32, the IMU and the RGB LED (it needs about 4.3 V or more, which 4 cells keep up until nearly empty).
Use the holder's switch as the wand's on/off switch. Rechargeable NiMH AAA work too.

- **Never connect the batteries to the 3V3 pin**: 6 V there destroys the ESP32.
- **Check polarity before switching on**: dev boards usually have no reverse-polarity protection.
- **Switch the batteries off while the USB cable is plugged in** (flashing, serial monitor), so the two
  supplies can't push into each other or into your computer's USB port.
- All grounds (batteries, ESP32, IMU, LEDs, button) connect together.
- If the ESP32 keeps restarting on battery and the serial monitor says *Brownout detector was triggered*,
  the batteries are too low.

This branch (`BNO085`) is for the BNO080 / BNO085, and the BNO086 should work too, because they share the same
protocol. Branch `mpu9250` has the MPU-9250 / MPU-6500 version. Branch `main` is older and has neither the RGB LED
nor the component test tools.

**Gyro offset:** the BNO08x removes this itself, so the firmware doesn't. Its datasheet says the correction is
fastest on a stable surface, so lay the wand on a table for a moment after switching it on.

**I²C on the ESP32:** Adafruit lists the BNO085 as not working well over I²C with the ESP32, because of how it
stretches the clock. The firmware uses INT and RST to reduce the risk, but this hasn't been tried on real hardware
yet. If readings stop or `IMU reset detected` keeps repeating, set `I2C_FAST_CLOCK_HZ` to `100000` in
`firmware/src/main.cpp`. SPI is the fallback if that doesn't help; it needs more wires and new pins, because
the default SPI pins are used by the LED.

`STATUS_LED` colours: dim white `IDLE`, blue `CASTING`, amber `INFLIGHT` (waiting for the Mac), then the
spell colour for 1 s, three flashes of the `UNKNOWN` colour (red by default), or two magenta flashes if the
Mac didn't answer within 2 s. Spell colours (including `UNKNOWN`) are set only in the SpellWand UI
(`config.json`) and sent with each result; the wand itself only knows its state colours.

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
cd mac_app && .venv/bin/python -m unittest discover -s tests -v      # Mac app: 153 tests
cd firmware && ~/.platformio/penv/bin/pio test -e native              # wand logic: 33 tests, run on the Mac
```

Both suites check the same example bytes from `docs/protocol.md`, so the two sides agree on the format.

## When the hardware arrives

Work through these in order; each step only needs the ones before it.

The **serial monitor** in these steps is a program, not a device. It shows the text the ESP32 prints,
over the same USB cable that flashes it. From `firmware/`:

```bash
~/.platformio/penv/bin/pio run -t upload       # flash the firmware
~/.platformio/penv/bin/pio device monitor      # show what it prints; Ctrl+C to quit
```

Press the **EN** button on the board to restart it and see the boot messages from the start.

1. **Board alone.** Flash and open the serial monitor. Expect `=== SpellWand firmware booted ===`,
   `BLE advertising as SpellWand` and an IMU error (no IMU yet). The `STATUS_LED` should glow dim white.
2. **IMU.** Wire the BNO08x and reboot with the wand lying still. Expect `BNO08x answered at 0x4B` (or `0x4A`),
   `IMU software: part ..., version ...` and `IMU reports: accelerometer on, gyroscope on`. One
   `IMU reset detected` line at start-up is normal; repeated ones mean the link is unreliable (see **I²C on the
   ESP32** above). If `begin()` fails or no readings arrive, check PS0, PS1, INT and RST.
3. **Button and LED.** Hold `CAST_BUTTON`: serial shows `CAST_START`, the LED turns blue; release: `CAST_END`,
   amber, then two magenta flashes after 2 s (nobody answered yet).
4. **Bluetooth.** `cd mac_app && .venv/bin/python ble_manager.py --listen`, then cast: you should see
   `CastStart`, about 100 `MotionSample`s per second and `CastEnd`.
5. **Training.** `.venv/bin/python app.py`, press **Connect wand**, and record 5 or more examples of each
   gesture. Use **Check dataset** and delete anything flagged.
6. **Casting.** Cast for real and watch the distances in the UI. Raise or lower the rejection threshold
   until gestures are accepted and casual movement comes back `UNKNOWN`. (On simulated data, gestures
   score about 0.1–0.5 and casual movement 2.5 or more; real data will be noisier.)
7. **Action.** Cast `CIRCLE` or `ZIGZAG`: the Mac shows a notification (set per gesture in the UI). If none
   appears, check System Settings → Notifications (osascript notifications are listed under Script Editor).

## Component tests

These make the data for the Component Testing Summary, using the targets in the Milestone 1 deck
(slides 5, 11 and 12). Do bring-up steps 1–4 first. Keep every log: git ignores them, so copy them
somewhere safe. `component_tests.py` turns a log into results and prints PASS or FAIL; run it from `mac_app/`.

**IMU, still and turns.** Flash the logging build, which is the normal firmware plus every reading printed
over USB. From `firmware/`:

```bash
~/.platformio/penv/bin/pio run -e imu_log -t upload
~/.platformio/penv/bin/pio device monitor -e imu_log
```

Each time the monitor starts, it saves a new log in `firmware/logs/`.

- *Still:* put the wand on a table, start the monitor, press **EN**, leave it alone for at least 70 s, then
  press Ctrl+C. The report skips the first 5 s and checks every reading in the next 60 s.

  ```bash
  .venv/bin/python component_tests.py still ../firmware/logs/<log file>
  ```

  Also check the `readings/s` line. The datasheet lets the chip run at 0.9 to 2.1 times the 100 Hz requested.
  Anything of 95 or more meets the target. If the rate is below 95, tell me.
- *Turns:* start the monitor again with the wand lying still. Turn it 90° about x (the axes printed on the
  IMU board), wait 2 s, then do the same about y and then z, wait 2 s, and press Ctrl+C.

  ```bash
  .venv/bin/python component_tests.py turns ../firmware/logs/<log file>
  ```

**I²C stability.** This chip has a known I²C problem on the ESP32, so also leave the logging build running for
10 minutes. From `firmware/`, count the resets in that log; more than 1 means the link is not stable:

```bash
grep -c "IMU reset detected" logs/<log file>
```

**Bluetooth link.** Flash the normal firmware again (`pio run -t upload`). From `mac_app/`, in a terminal
that is allowed to use Bluetooth (see above):

```bash
.venv/bin/python -u ble_manager.py --listen | tee -i link_test.log
```

Stand as far from the Mac as you expect to use the wand, about 3 m. Make 20 casts: hold the button past
3 s (the wand stops itself at 3 s) and wait for the two magenta flashes before the next cast. They are
normal here, because the listener doesn't answer. Press Ctrl+C, then:

```bash
.venv/bin/python component_tests.py link link_test.log
```

If the serial monitor is open too, it shows the wand's side. On connecting, `Bluetooth interval now 15.00 ms`:
the wand asks the Mac for a message slot every 15 ms instead of macOS's usual 30 ms, which doubles how many
readings get through. After each cast, `Bluetooth: cast fully sent ... longest queue N messages, D readings
dropped`: when the radio is busy, messages wait in a queue and are resent instead of being lost, so N above
1 means the link was struggling, and D should always be 0. Without the button, `tools/hardware_tests/link_drive.py`
has the Mac start 20 recordings itself.

**Response time.** `app.py` adds a row to `mac_app/cast_log.csv` for every cast (`sim_data/cast_log.csv`
in simulation mode): time, predicted label, nearest gesture, DTW distance, `response_ms`, samples and
dropped samples. Delete the file to start a new test.

```bash
.venv/bin/python component_tests.py casts cast_log.csv
```

`response_ms` is only the Mac's share: from `CAST_END` arriving to `GESTURE_RESULT` sent. For the full time,
keep the serial monitor open: it prints lines like `GESTURE_RESULT: CIRCLE, 85 ms after CAST_END`. Add 30 ms
of button debounce to get button release to LED result. The log can't know which gesture you meant to
cast, so cast in blocks of one gesture and add an `actual` column in a spreadsheet to work out accuracy.

### Extra test tools

`tools/hardware_tests/` has small helpers for finding faults and for guided tests. Run these from the top of the
repo. The first two replace the wand firmware, so flash it back afterwards with `pio run -d firmware -t upload`.

| Tool | Use it to |
|---|---|
| `pin_check` | Find wiring faults: turns on all the LED pins and prints the raw button state |
| `led_check` | Check the LED: shows each colour for 3 s and prints which colour it should be |
| `button_test.py` | Run the 20-press button test, one prompt at a time |
| `guided_turns.py` | Run the turn test with prompts telling you when to turn (needs the `imu_log` build) |
| `link_drive.py` | Run the Bluetooth test with no button: the Mac starts 20 recordings of 5 s each |
| `capture.py` | Save what the board prints to a file; add `--restart` to include the boot messages |

Flash and watch `pin_check` or `led_check` like this:

```bash
~/.platformio/penv/bin/pio run -d tools/hardware_tests/pin_check -t upload
```

```bash
~/.platformio/penv/bin/pio device monitor -d tools/hardware_tests/pin_check
```

The scripts say how to run them at the top of each file. `link_drive.py` runs with `mac_app/.venv/bin/python` in
a terminal allowed to use Bluetooth; the other scripts run with `~/.platformio/penv/bin/python`.

## How it fits together

```
ESP32  ──BLE_LINK──>  ble_manager.py ──> controller.py ──> classifier.py      (DTW + rejection)
 (wand_core state machine)              │      │        ──> recorder.py        (CSV samples in data/)
                                        │      └──────> action_dispatcher.py (notification, webhook)
                                        └── app.py + templates/ + static/  (SpellWand UI, live via server-sent events)
```

`simulator.py` can stand in for the ESP32 at the left end (`app.py --simulate`, and the tests).

**Diagrams** in `docs/diagrams/`, each as a `.png` picture and an editable `.drawio` file:
- `circuit`: the wiring, with large labels so it reads well on a slide.
- `code_flowchart`: what the firmware and the Mac app do, and the messages between them.

Edit a `.drawio` file at https://app.diagrams.net or in the draw.io desktop app, then use **File > Export as >
PNG** to update its picture. Wires and arrows stay attached when you move things. `make_drawio.py` rebuilds both
`.drawio` files from scratch, so running it overwrites edits made in draw.io.

## Progress

| Step | Status |
|---|---|
| PlatformIO project, IMU reading, `CAST_BUTTON`, states, `STATUS_LED`, `BLE_LINK`, `GESTURE_RESULT` colours | Written and compiles; logic tested on the Mac (`pio test -e native`); **needs hardware test** |
| `BLE Manager` | Scanning tested on this Mac; connecting tested against the simulated wand only; **needs hardware test** |
| `Sample Recorder`, `Gesture Classifier`, `Action Dispatcher`, `config.json` | Tested (simulated data) |
| Flask `SpellWand UI` | Tested through its API and by hand in a browser with the simulated wand |
| End-to-end | Tested with the simulated wand; **real end-to-end needs hardware** |
| Rejection threshold | Default 1.0 works on simulated data; **tune with real recordings** |
| BNO08x driver | Compiles against the pinned SparkFun library 1.0.6; **never run on a real BNO08x** |
| `tools/hardware_tests/` | Button, turn and capture scripts tested on a fake board; `pin_check` and `led_check` compile; `link_drive.py` has run on the real ESP32, but not in this tidied form |
| Component test tools (`imu_log` build, `component_tests.py`, `cast_log.csv`) | Reports tested on generated logs; serial logging tried with a fake board; **needs hardware test** |
