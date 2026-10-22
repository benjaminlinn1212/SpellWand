// Learns the gyro's constant offset ("bias") from moments when the wand is held still, so
// it can be subtracted from every reading. Every MEMS gyro reads slightly non-zero at rest,
// and the offset drifts as the chip warms up. The BNO086 corrected this itself; the
// MPU-9250 / MPU-6500 does not, so the firmware does it here.
#pragma once
#include <math.h>

namespace gyro_bias {
const float MAX_SPREAD_RAD_S = 0.05f;  // "still": each gyro axis stays within this range (about 3 deg/s)...
const float MAX_ACCEL_SPREAD = 0.5f;   // ...and each accelerometer axis within this (m/s^2): no tilting
const float MAX_OFFSET_RAD_S = 0.15f;  // real offsets are smaller (about 9 deg/s); more is a slow, steady turn
}  // namespace gyro_bias

class GyroBias {
 public:
  static const int WINDOW = 50;  // 0.5 s at 100 Hz

  // Feed every reading (rad/s and m/s^2, before correction) taken while the wand is IDLE.
  // Returns true each time a full window of stillness gives a new offset.
  bool update(const float gyro[3], const float accel[3]) {
    for (int k = 0; k < 3; k++) {
      if (count_ == 0) {
        gyroMin_[k] = gyroMax_[k] = gyro[k];
        accelMin_[k] = accelMax_[k] = accel[k];
      }
      sum_[k] += gyro[k];
      gyroMin_[k] = fminf(gyroMin_[k], gyro[k]);
      gyroMax_[k] = fmaxf(gyroMax_[k], gyro[k]);
      accelMin_[k] = fminf(accelMin_[k], accel[k]);
      accelMax_[k] = fmaxf(accelMax_[k], accel[k]);
    }
    if (++count_ < WINDOW) return false;

    float mean[3];
    bool still = true;
    for (int k = 0; k < 3; k++) {
      mean[k] = sum_[k] / WINDOW;
      still = still && gyroMax_[k] - gyroMin_[k] <= gyro_bias::MAX_SPREAD_RAD_S
                    && accelMax_[k] - accelMin_[k] <= gyro_bias::MAX_ACCEL_SPREAD
                    && fabsf(mean[k]) <= gyro_bias::MAX_OFFSET_RAD_S;
    }
    restart();
    if (!still) return false;
    for (int k = 0; k < 3; k++) offset_[k] = mean[k];
    ready_ = true;
    return true;
  }

  // Throw away a partly measured window (call when the wand stops being IDLE).
  void restart() {
    count_ = 0;
    for (int k = 0; k < 3; k++) sum_[k] = 0.0f;
  }

  bool ready() const { return ready_; }  // an offset has been measured at least once
  float offset(int axis) const { return offset_[axis]; }

  void correct(float gyro[3]) const {
    for (int k = 0; k < 3; k++) gyro[k] -= offset_[k];
  }

 private:
  int count_ = 0;
  float sum_[3] = {0, 0, 0};
  float gyroMin_[3] = {0, 0, 0}, gyroMax_[3] = {0, 0, 0};
  float accelMin_[3] = {0, 0, 0}, accelMax_[3] = {0, 0, 0};
  float offset_[3] = {0, 0, 0};
  bool ready_ = false;
};
