#pragma once
#include <stdint.h>

struct Rgb {
  uint8_t r, g, b;
};

inline bool isBlack(Rgb c) { return c.r == 0 && c.g == 0 && c.b == 0; }
