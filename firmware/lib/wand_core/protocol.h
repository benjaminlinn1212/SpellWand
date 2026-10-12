// BLE_LINK message protocol: the bytes the ESP32 and the Mac exchange.
// Specification and example bytes: docs/protocol.md (Mac side: mac_app/protocol.py).
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "rgb.h"

namespace protocol {

// Message types (first byte)
const uint8_t CAST_START = 0x01;
const uint8_t MOTION_SAMPLE = 0x02;
const uint8_t CAST_END = 0x03;
const uint8_t ACTION_COMPLETE = 0x04;
const uint8_t START_RECORDING = 0x81;
const uint8_t STOP_RECORDING = 0x82;
const uint8_t GESTURE_RESULT = 0x83;
const uint8_t EXECUTE_ACTION = 0x84;

// CAST_START sources
const uint8_t SOURCE_CAST_BUTTON = 0;
const uint8_t SOURCE_RECORDING = 1;

// CAST_END reasons
const uint8_t END_NORMAL = 0;  // button released, or STOP_RECORDING
const uint8_t END_MAX_DURATION = 1;
const uint8_t END_CONNECTION_LOST = 2;

// EXECUTE_ACTION actions
const uint8_t ACTION_TOGGLE_LED = 1;
const uint8_t ACTION_PULSE_LED = 2;

const size_t MAX_MESSAGE_BYTES = 20;
const size_t MAX_LABEL_LENGTH = 16;

// One timestamped IMU reading. Accel in m/s^2, gyro in rad/s.
struct MotionSample {
  uint16_t index;
  uint32_t t_ms;
  float ax, ay, az;
  float gx, gy, gz;
};

// Each encode function writes one message into `out` (at least MAX_MESSAGE_BYTES
// long) and returns its length.
size_t encodeCastStart(uint8_t* out, uint8_t source);
size_t encodeMotionSample(uint8_t* out, const MotionSample& sample);
size_t encodeCastEnd(uint8_t* out, uint16_t sampleCount, uint8_t reason);
size_t encodeActionComplete(uint8_t* out, uint8_t action, bool ok);

struct Command {
  uint8_t type;
  Rgb color;                         // GESTURE_RESULT: spell colour from the Mac's config.json
  char label[MAX_LABEL_LENGTH + 1];  // GESTURE_RESULT, null-terminated
  uint8_t action;                    // EXECUTE_ACTION
};

// Fills `out` from bytes written by the Mac. Returns false if they are not a valid command.
bool decodeCommand(const uint8_t* data, size_t length, Command& out);

}  // namespace protocol
