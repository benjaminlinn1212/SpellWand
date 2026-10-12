// CAST_BUTTON debouncing: a mechanical button "bounces" for a few milliseconds when
// pressed or released. Only accept a new state once it has held steady for settleMs.
#pragma once
#include <stdint.h>

class Debouncer {
 public:
  explicit Debouncer(uint32_t settleMs = 30) : settleMs_(settleMs) {}

  // Feed the raw reading (true = pressed). Returns true once, when the
  // debounced state changes.
  bool update(bool rawPressed, uint32_t nowMs) {
    if (rawPressed != lastRaw_) {
      lastRaw_ = rawPressed;
      lastChangeMs_ = nowMs;
    }
    if (rawPressed != stable_ && nowMs - lastChangeMs_ >= settleMs_) {
      stable_ = rawPressed;
      return true;
    }
    return false;
  }

  bool pressed() const { return stable_; }

 private:
  uint32_t settleMs_;
  bool stable_ = false;
  bool lastRaw_ = false;
  uint32_t lastChangeMs_ = 0;
};
