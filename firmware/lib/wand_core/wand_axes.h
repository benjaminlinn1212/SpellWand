// Turns a reading from the IMU's own axes into the wand's axes, which the Mac app expects:
//   x = along the wand toward the tip,  y = to the left,  z = up  (wand held level)
//
// On this wand the IMU's z axis points to the tip and its y axis is up, which leaves its x axis
// pointing left. If the IMU is mounted another way, change the three lines marked below (and
// the tests): gestures recorded before the change will no longer match.
#pragma once

#include "imu_pairing.h"

inline ImuReading toWandAxes(const ImuReading& imu) {
  static const int FORWARD = 2;  // the IMU axis (0 = x, 1 = y, 2 = z) that points to the tip
  static const int LEFT = 0;     // ... that points left
  static const int UP = 1;       // ... that points up
  ImuReading wand;
  wand.accel[0] = imu.accel[FORWARD];
  wand.accel[1] = imu.accel[LEFT];
  wand.accel[2] = imu.accel[UP];
  wand.gyro[0] = imu.gyro[FORWARD];
  wand.gyro[1] = imu.gyro[LEFT];
  wand.gyro[2] = imu.gyro[UP];
  return wand;
}
