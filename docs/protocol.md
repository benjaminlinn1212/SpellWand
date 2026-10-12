# BLE_LINK message protocol

How the `ESP32` and the Mac's `BLE Manager` talk. Implemented in
`firmware/lib/wand_core/protocol.*` (C++) and `mac_app/protocol.py` (Python). Both test
suites check the example bytes below, so the two sides cannot drift apart silently.

## GATT layout

| Item | UUID | Direction |
|---|---|---|
| Device name | `SpellWand` (advertised) | |
| Service | `06f40001-a27b-408d-a176-2e94b74b3ad3` | |
| Events characteristic (notify) | `06f40002-a27b-408d-a176-2e94b74b3ad3` | ESP32 → Mac |
| Commands characteristic (write) | `06f40003-a27b-408d-a176-2e94b74b3ad3` | Mac → ESP32 |

Every message is at most **20 bytes**, so it fits in one BLE packet at the default MTU.
The first byte is the message type. Numbers are little-endian.

## Events (ESP32 → Mac)

| Type | Name | Payload after the type byte | Size |
|---|---|---|---|
| `0x01` | `CAST_START` | source `u8`: 0 = `CAST_BUTTON` held, 1 = `START_RECORDING` from the Mac | 2 |
| `0x02` | `MOTION_SAMPLE` | index `u16` (0, 1, 2, ... per cast), t_ms `u32` (ESP32 `millis()`), ax ay az `i16` in 0.01 m/s², gx gy gz `i16` in 0.001 rad/s | 19 |
| `0x03` | `CAST_END` | sample count `u16`, reason `u8`: 0 = button released / `STOP_RECORDING`, 1 = maximum duration reached, 2 = connection lost | 4 |
| `0x04` | `ACTION_COMPLETE` | action `u8` (echo of `EXECUTE_ACTION`), ok `u8` (1 = done, 0 = unknown action) | 3 |

Values are rounded to the nearest step and clamped to the `i16` range: ±327.67 m/s² for the
accelerometer and ±32.767 rad/s (about 1877 °/s) for the gyroscope.

## Commands (Mac → ESP32)

| Type | Name | Payload after the type byte | Size |
|---|---|---|---|
| `0x81` | `START_RECORDING` | none | 1 |
| `0x82` | `STOP_RECORDING` | none | 1 |
| `0x83` | `GESTURE_RESULT` | r g b `u8`: the spell colour, shown exactly as sent; then the `GestureLabel` in ASCII, 1–16 characters | 5–20 |
| `0x84` | `EXECUTE_ACTION` | action `u8`: 1 = toggle the action LED, 2 = pulse the action LED for 0.5 s | 2 |

## Typical exchanges

Casting (button):

```
ESP32: CAST_START(source=0)            state IDLE -> CASTING, LED blue
ESP32: MOTION_SAMPLE x N (about 100 Hz)
ESP32: CAST_END(count=N, reason=0)     state CASTING -> INFLIGHT, LED amber
Mac:   GESTURE_RESULT(colour, "CIRCLE")  LED shows that colour (three flashes of it for UNKNOWN)
                                       state INFLIGHT -> IDLE after the feedback
Mac:   EXECUTE_ACTION(1)               (only if the gesture is mapped to the wand's action LED)
ESP32: ACTION_COMPLETE(1, ok=1)
```

**Spell colours have one home: the Mac's `config.json`** (edited in the SpellWand UI, including the
colour for `UNKNOWN`). The wand has no spell colours of its own; it only owns the colours of its states
(dim white `IDLE`, blue `CASTING`, amber `INFLIGHT`, magenta "no answer") and the flash pattern.

If no `GESTURE_RESULT` arrives within 2 s, the wand flashes magenta ("no answer") and returns to `IDLE`.

Training (no button needed):

```
Mac:   START_RECORDING                 state IDLE -> CASTING
ESP32: CAST_START(source=1)
ESP32: MOTION_SAMPLE x N
Mac:   STOP_RECORDING
ESP32: CAST_END(count=N, reason=0)     state CASTING -> IDLE (nothing to classify)
```

## Example bytes (checked by both test suites)

| Message | Bytes (hex) |
|---|---|
| `CAST_START(source=0)` | `01 00` |
| `MOTION_SAMPLE(index=7, t_ms=123456, accel=(0.12, -9.81, 1.00), gyro=(0.5, -1.25, 3.0))` | `02 07 00 40 e2 01 00 0c 00 2b fc 64 00 f4 01 1e fb b8 0b` |
| `CAST_END(count=150, reason=1)` | `03 96 00 01` |
| `ACTION_COMPLETE(action=2, ok=1)` | `04 02 01` |
| `START_RECORDING` | `81` |
| `STOP_RECORDING` | `82` |
| `GESTURE_RESULT(rgb=(0, 80, 255), "CIRCLE")` | `83 00 50 ff 43 49 52 43 4c 45` |
| `EXECUTE_ACTION(action=1)` | `84 01` |
