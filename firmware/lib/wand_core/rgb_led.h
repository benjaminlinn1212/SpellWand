// STATUS_LED as an ordinary 4-leg RGB LED: each colour leg gets its own PWM pin.
#pragma once
#include <stdint.h>

namespace rgb_led {

// PWM duty (0-255) for one colour leg showing `value` (0-255) at `brightness` (0-255).
// Common cathode (long leg to GND): more duty = brighter.
// Common anode (long leg to 3.3 V): the pin must go LOW to light, so the duty is inverted.
inline uint8_t duty(uint8_t value, uint8_t brightness, bool commonAnode) {
  uint8_t level = (uint8_t)((uint16_t)value * brightness / 255);
  return commonAnode ? 255 - level : level;
}

}  // namespace rgb_led
