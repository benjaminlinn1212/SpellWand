#include "protocol.h"

#include <math.h>
#include <string.h>

namespace protocol {

static const float ACCEL_STEPS_PER_UNIT = 100.0f;  // 0.01 m/s^2
static const float GYRO_STEPS_PER_UNIT = 1000.0f;  // 0.001 rad/s

// Round to the nearest step and clamp to the int16 range.
static int16_t toSteps(float value, float stepsPerUnit) {
  float steps = floorf(value * stepsPerUnit + 0.5f);
  if (steps > 32767.0f) return 32767;
  if (steps < -32768.0f) return -32768;
  return (int16_t)steps;
}

// Little-endian writers; each returns the next free position.
static uint8_t* putU16(uint8_t* p, uint16_t v) {
  p[0] = v & 0xff;
  p[1] = v >> 8;
  return p + 2;
}

static uint8_t* putU32(uint8_t* p, uint32_t v) {
  for (int i = 0; i < 4; i++) p[i] = (v >> (8 * i)) & 0xff;
  return p + 4;
}

size_t encodeCastStart(uint8_t* out, uint8_t source) {
  out[0] = CAST_START;
  out[1] = source;
  return 2;
}

size_t encodeMotionSample(uint8_t* out, const MotionSample& s) {
  uint8_t* p = out;
  *p++ = MOTION_SAMPLE;
  p = putU16(p, s.index);
  p = putU32(p, s.t_ms);
  const float values[6] = {s.ax, s.ay, s.az, s.gx, s.gy, s.gz};
  for (int i = 0; i < 6; i++) {
    float scale = i < 3 ? ACCEL_STEPS_PER_UNIT : GYRO_STEPS_PER_UNIT;
    p = putU16(p, (uint16_t)toSteps(values[i], scale));
  }
  return p - out;
}

size_t encodeCastEnd(uint8_t* out, uint16_t sampleCount, uint8_t reason) {
  out[0] = CAST_END;
  putU16(out + 1, sampleCount);
  out[3] = reason;
  return 4;
}

size_t encodeActionComplete(uint8_t* out, uint8_t action, bool ok) {
  out[0] = ACTION_COMPLETE;
  out[1] = action;
  out[2] = ok ? 1 : 0;
  return 3;
}

bool decodeCommand(const uint8_t* data, size_t length, Command& out) {
  if (data == nullptr || length == 0) return false;
  memset(&out, 0, sizeof(out));
  out.type = data[0];
  switch (out.type) {
    case START_RECORDING:
    case STOP_RECORDING:
      return length == 1;
    case GESTURE_RESULT: {
      size_t labelLength = length >= 5 ? length - 4 : 0;
      if (labelLength < 1 || labelLength > MAX_LABEL_LENGTH) return false;
      out.color = Rgb{data[1], data[2], data[3]};
      memcpy(out.label, data + 4, labelLength);
      out.label[labelLength] = '\0';
      return true;
    }
    case EXECUTE_ACTION:
      if (length != 2) return false;
      out.action = data[1];
      return true;
    default:
      return false;
  }
}

}  // namespace protocol
