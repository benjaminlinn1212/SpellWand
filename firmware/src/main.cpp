// SpellWand firmware
//
// Step 2 (toolchain check): prints a boot banner and a once-per-second
// heartbeat so we can confirm that build, upload and the serial monitor work.
// The IMU, CAST_BUTTON, STATUS_LED and BLE_LINK are added in later steps.

#include <Arduino.h>

static const uint32_t SERIAL_BAUD = 115200;  // must match monitor_speed in platformio.ini
static const uint32_t HEARTBEAT_MS = 1000;

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // give the USB-serial adapter a moment so the banner isn't lost

  Serial.println();
  Serial.println("=== SpellWand firmware booted ===");
  Serial.printf("Chip: %s rev %u, %u cores @ %lu MHz\n",
                ESP.getChipModel(),
                (unsigned)ESP.getChipRevision(),
                (unsigned)ESP.getChipCores(),
                (unsigned long)ESP.getCpuFreqMHz());
  Serial.printf("Flash: %lu bytes, free heap: %lu bytes\n",
                (unsigned long)ESP.getFlashChipSize(),
                (unsigned long)ESP.getFreeHeap());
}

void loop() {
  // Non-blocking timer: later steps will poll the IMU and CAST_BUTTON here,
  // so loop() must never sit inside delay().
  static uint32_t lastBeatMs = 0;
  uint32_t now = millis();
  if (now - lastBeatMs >= HEARTBEAT_MS) {
    lastBeatMs = now;
    Serial.printf("[%lu ms] alive\n", (unsigned long)now);
  }
}
