// One-off check: all LED pins fully on, and the raw button state whenever it changes.
#include <Arduino.h>
static const int LED_PINS[3] = {18, 19, 23};
static const int BUTTON_PIN = 27;
void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  for (int pin : LED_PINS) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, HIGH);
  }
}
void loop() {
  static int last = -1;
  static uint32_t lastPrint = 0;
  int level = digitalRead(BUTTON_PIN);
  if (level != last || millis() - lastPrint > 3000) {
    Serial.println(level == LOW ? "Button: DOWN (pin connected to GND)" : "Button: UP (pin not connected to GND)");
    last = level;
    lastPrint = millis();
  }
  delay(10);
}
