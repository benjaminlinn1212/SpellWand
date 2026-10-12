// SpellWand firmware
//
// Step 3: read the IMU (BNO086 over I2C) and print accelerometer and gyroscope
// readings to the serial monitor. CAST_BUTTON, STATUS_LED and BLE_LINK come later.

#include <Arduino.h>
#include <Wire.h>
#include "SparkFun_BNO08x_Arduino_Library.h"

// ---- Pins (see the wiring table in README.md) ----
static const int IMU_SDA_PIN = 21;
static const int IMU_SCL_PIN = 22;
// INT and RST make the BNO086 link much more reliable (SparkFun recommends both).
// Set a pin to -1 if that wire is NOT connected: a defined-but-unwired INT pin
// makes every read wait 500 ms and then time out.
static const int IMU_INT_PIN = 4;
static const int IMU_RST_PIN = 23;

// ---- Settings ----
static const uint32_t SERIAL_BAUD = 115200;            // must match monitor_speed in platformio.ini
static const uint16_t IMU_REPORT_INTERVAL_MS = 10;     // 100 Hz accelerometer + gyroscope
static const uint32_t I2C_FAST_CLOCK_HZ = 400000;      // drop to 100000 if readings are flaky
static const uint32_t PRINT_INTERVAL_MS = 100;         // print at 10 Hz so the serial port keeps up
static const uint32_t RATE_REPORT_INTERVAL_MS = 1000;

// The SparkFun BNO086 board answers at 0x4B; most other BNO08x boards use 0x4A.
static const uint8_t BNO08X_ADDRESSES[] = {0x4B, 0x4A};

// One timestamped IMU reading. Accel in m/s^2 (includes gravity), gyro in rad/s.
struct MotionSample {
  uint32_t t_ms;
  float ax, ay, az;
  float gx, gy, gz;
};

BNO08x imu;
MotionSample latest = {};
uint32_t accelEventCount = 0;
uint32_t gyroEventCount = 0;

static bool i2cDevicePresent(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

// Prints every I2C address that answers, to help debug wiring.
static void scanI2C() {
  Serial.print("I2C scan found:");
  int found = 0;
  for (uint8_t address = 1; address < 127; address++) {
    if (i2cDevicePresent(address)) {
      Serial.printf(" 0x%02X", address);
      found++;
    }
  }
  Serial.println(found ? "" : " nothing");
}

static bool startImu() {
  int address = -1;
  for (uint8_t candidate : BNO08X_ADDRESSES) {
    if (i2cDevicePresent(candidate)) {
      address = candidate;
      break;
    }
  }
  if (address < 0) {
    Serial.println("ERROR: no BNO08x at 0x4A or 0x4B. Check SDA, SCL, 3V3 and GND.");
    scanI2C();
    return false;
  }

  Serial.printf("BNO08x answered at 0x%02X\n", address);
  if (!imu.begin(address, Wire, IMU_INT_PIN, IMU_RST_PIN)) {
    Serial.println("ERROR: BNO08x found but begin() failed.");
    Serial.println("       If INT/RST are not wired, set IMU_INT_PIN / IMU_RST_PIN to -1.");
    return false;
  }
  return true;
}

// Must be called again whenever the IMU resets, because a reset clears its report settings.
static void enableImuReports() {
  bool accelOk = imu.enableAccelerometer(IMU_REPORT_INTERVAL_MS);
  bool gyroOk = imu.enableGyro(IMU_REPORT_INTERVAL_MS);
  Serial.printf("IMU reports: accelerometer %s, gyroscope %s\n",
                accelOk ? "on" : "FAILED", gyroOk ? "on" : "FAILED");
}

// The BNO086 sends accelerometer and gyroscope as separate events.
// Each event updates its half of `latest`.
static void readImu() {
  // With INT wired, only talk to the IMU when it says data is ready (INT low);
  // otherwise the library blocks for up to 500 ms and then resets the sensor.
  bool dataReady = (IMU_INT_PIN < 0) || (digitalRead(IMU_INT_PIN) == LOW);
  if (!dataReady || !imu.getSensorEvent()) {
    return;
  }

  switch (imu.getSensorEventID()) {
    case SENSOR_REPORTID_ACCELEROMETER:
      latest.ax = imu.getAccelX();
      latest.ay = imu.getAccelY();
      latest.az = imu.getAccelZ();
      accelEventCount++;
      break;
    case SENSOR_REPORTID_GYROSCOPE_CALIBRATED:
      latest.gx = imu.getGyroX();
      latest.gy = imu.getGyroY();
      latest.gz = imu.getGyroZ();
      gyroEventCount++;
      break;
    default:
      return;
  }
  latest.t_ms = millis();
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // give the USB-serial adapter a moment so the banner isn't lost

  Serial.println();
  Serial.println("=== SpellWand firmware booted ===");

  // Start at the default 100 kHz: the BNO086 start-up handshake is most reliable there.
  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  while (!startImu()) {
    Serial.println("Retrying in 2 s...");
    delay(2000);
  }
  Wire.setClock(I2C_FAST_CLOCK_HZ);
  enableImuReports();

  Serial.println("Columns: t_ms | accel m/s^2 x y z | gyro rad/s x y z");
}

void loop() {
  if (imu.wasReset()) {
    Serial.println("IMU reset detected, re-enabling reports");
    enableImuReports();
  }

  readImu();

  // Non-blocking timers: loop() must never sit inside delay(), or IMU events pile up.
  uint32_t now = millis();

  static uint32_t lastPrintMs = 0;
  if (now - lastPrintMs >= PRINT_INTERVAL_MS) {
    lastPrintMs = now;
    Serial.printf("%8lu | %7.2f %7.2f %7.2f | %6.2f %6.2f %6.2f\n",
                  (unsigned long)latest.t_ms,
                  latest.ax, latest.ay, latest.az,
                  latest.gx, latest.gy, latest.gz);
  }

  // Both rates should be close to 1000 / IMU_REPORT_INTERVAL_MS (100 Hz).
  // A rate far below that means events are being dropped.
  static uint32_t lastRateMs = 0;
  if (now - lastRateMs >= RATE_REPORT_INTERVAL_MS) {
    lastRateMs = now;
    Serial.printf("-- rates: accel %lu Hz, gyro %lu Hz\n",
                  (unsigned long)accelEventCount, (unsigned long)gyroEventCount);
    accelEventCount = 0;
    gyroEventCount = 0;
  }
}
