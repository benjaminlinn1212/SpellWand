// The BNO08x reports its accelerometer and gyroscope separately. Each gyroscope report
// becomes one reading, using the newest accelerometer report.
#pragma once

struct ImuReading {
  float accel[3];  // m/s^2, including gravity
  float gyro[3];   // rad/s
};

class ImuPairing {
 public:
  void accel(float x, float y, float z) {
    accel_[0] = x;
    accel_[1] = y;
    accel_[2] = z;
    haveAccel_ = true;
  }

  // Fills `reading` and returns true once an accelerometer report has arrived.
  bool gyro(float x, float y, float z, ImuReading& reading) const {
    if (!haveAccel_) return false;
    for (int k = 0; k < 3; k++) reading.accel[k] = accel_[k];
    reading.gyro[0] = x;
    reading.gyro[1] = y;
    reading.gyro[2] = z;
    return true;
  }

 private:
  float accel_[3] = {0, 0, 0};
  bool haveAccel_ = false;
};
