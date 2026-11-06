// One-off check: each colour in turn on the same pins and PWM settings as the wand.
#include <Arduino.h>
static const int PINS[3] = {18, 19, 23};
static void show(const char* name, int r, int g, int b) {
  Serial.printf("LED should be %s now\n", name);
  ledcWrite(0, r); ledcWrite(1, g); ledcWrite(2, b);
  delay(3000);
}
void setup() {
  Serial.begin(115200);
  for (int channel = 0; channel < 3; channel++) {
    ledcSetup(channel, 5000, 8);
    ledcAttachPin(PINS[channel], channel);
  }
}
void loop() {
  show("RED", 255, 0, 0);
  show("GREEN", 0, 255, 0);
  show("BLUE", 0, 0, 255);
  show("WHITE", 255, 255, 255);
  show("AMBER", 255, 70, 0);
  show("MAGENTA", 255, 0, 255);
  show("DIM WHITE", 8, 8, 8);
  show("OFF", 0, 0, 0);
}
