// One-off check: prints the raw CAST_BUTTON state (GPIO 27, no debouncing) whenever it changes,
// and every 3 s, to find wiring faults.
#include <Arduino.h>
static const int CAST_BUTTON_PIN = 27;  // to GND, internal pull-up: LOW = pressed
void setup() {
  Serial.begin(115200);
  pinMode(CAST_BUTTON_PIN, INPUT_PULLUP);
}
void loop() {
  static int last = -1;
  static uint32_t lastPrint = 0;
  int level = digitalRead(CAST_BUTTON_PIN);
  if (level != last || millis() - lastPrint > 3000) {
    Serial.println(level == LOW ? "Button: DOWN (pin connected to GND)" : "Button: UP (pin not connected to GND)");
    last = level;
    lastPrint = millis();
  }
  delay(10);
}
