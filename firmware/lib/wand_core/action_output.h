// The low-voltage "action LED" the Mac can switch with EXECUTE_ACTION.
#pragma once
#include <stdint.h>

#include "protocol.h"

class ActionOutput {
 public:
  static const uint32_t PULSE_MS = 500;

  // Returns false for an action this wand does not know.
  bool execute(uint8_t action, uint32_t nowMs) {
    if (action == protocol::ACTION_TOGGLE_LED) {
      on_ = !on_;
      pulsing_ = false;
      return true;
    }
    if (action == protocol::ACTION_PULSE_LED) {
      pulsing_ = true;
      pulseStartMs_ = nowMs;
      return true;
    }
    return false;
  }

  // Whether the LED should be lit right now.
  bool level(uint32_t nowMs) const {
    // Elapsed time by subtraction stays correct when millis() wraps around.
    bool pulseLit = pulsing_ && nowMs - pulseStartMs_ < PULSE_MS;
    return pulseLit || on_;
  }

 private:
  bool on_ = false;
  bool pulsing_ = false;
  uint32_t pulseStartMs_ = 0;
};
