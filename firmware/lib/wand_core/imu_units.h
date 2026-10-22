// Converting the MPU-9250 / MPU-6500's raw register values into SI units.
// main.cpp sets the ranges to +-8 g and +-2000 deg/s; the scale factors below match those.
#pragma once
#include <stdint.h>

namespace imu_units {

const float GRAVITY = 9.80665f;            // m/s^2 per g
const float ACCEL_COUNTS_PER_G = 4096.0f;  // at +-8 g
const float GYRO_COUNTS_PER_DPS = 16.4f;   // at +-2000 deg/s
const float RAD_PER_DEG = 3.14159265f / 180.0f;

// The chip sends each reading as two bytes, high byte first.
inline int16_t fromBigEndian(uint8_t high, uint8_t low) {
  return (int16_t)(((uint16_t)high << 8) | low);
}

inline float accelToMs2(int16_t raw) { return raw * GRAVITY / ACCEL_COUNTS_PER_G; }
inline float gyroToRadS(int16_t raw) { return raw / GYRO_COUNTS_PER_DPS * RAD_PER_DEG; }

}  // namespace imu_units
