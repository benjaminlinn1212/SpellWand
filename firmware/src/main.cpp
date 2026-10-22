// SpellWand firmware
//
// Hardware glue around the tested logic in lib/wand_core:
//   IMU (MPU-9250 / MPU-6500, I2C) -> MOTION_SAMPLE events while CASTING
//   CAST_BUTTON        -> debounced, drives IDLE / CASTING / INFLIGHT
//   STATUS_LED         -> colour from the state machine (WS2812B via neopixelWrite)
//   BLE_LINK           -> events notified to the Mac, commands written by the Mac
//   ACTION_LED         -> low-voltage LED the Mac can switch with EXECUTE_ACTION
// Message format: docs/protocol.md

#include <Arduino.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <Wire.h>

#include "action_output.h"
#include "debouncer.h"
#include "gyro_bias.h"
#include "imu_units.h"
#include "protocol.h"
#include "wand_state.h"

// ---- Pins (see the wiring table in README.md) ----
static const int IMU_SDA_PIN = 21;
static const int IMU_SCL_PIN = 22;
static const int CAST_BUTTON_PIN = 27;  // to GND, internal pull-up: LOW = pressed
static const int STATUS_LED_PIN = 18;   // WS2812B data in
static const int ACTION_LED_PIN = 26;   // LED + 330 ohm resistor to GND

// ---- Settings ----
static const uint32_t SERIAL_BAUD = 115200;
static const uint32_t I2C_CLOCK_HZ = 400000;      // the MPU supports 400 kHz; drop to 100000 if flaky
static const uint32_t IMU_POLL_US = 1000;         // check for a new reading every 1 ms (they come every 10 ms)
static const uint32_t IMU_RETRY_MS = 2000;
static const uint32_t GYRO_CALIBRATION_MS = 3000; // at boot, wait up to this long for the wand to be still
static const uint8_t LED_BRIGHTNESS = 64;           // 0-255; a WS2812B at full power is dazzling

// BLE_LINK identifiers: must match mac_app/protocol.py
static const char* DEVICE_NAME = "SpellWand";
static const char* SERVICE_UUID = "06f40001-a27b-408d-a176-2e94b74b3ad3";
static const char* EVENTS_UUID = "06f40002-a27b-408d-a176-2e94b74b3ad3";
static const char* COMMANDS_UUID = "06f40003-a27b-408d-a176-2e94b74b3ad3";

// MPU-9250 / MPU-6500 I2C addresses: 0x68 with AD0 to GND, 0x69 with AD0 to 3.3 V.
static const uint8_t MPU_ADDRESSES[] = {0x68, 0x69};

// MPU-9250 / MPU-6500 registers (checked against the Linux kernel's inv_mpu6050 driver).
namespace mpu {
const uint8_t SMPLRT_DIV = 0x19;
const uint8_t CONFIG = 0x1A;          // gyro low-pass filter
const uint8_t GYRO_CONFIG = 0x1B;
const uint8_t ACCEL_CONFIG = 0x1C;
const uint8_t ACCEL_CONFIG_2 = 0x1D;  // accelerometer low-pass filter (not on the older MPU-6050)
const uint8_t INT_ENABLE = 0x38;
const uint8_t INT_STATUS = 0x3A;
const uint8_t ACCEL_XOUT_H = 0x3B;    // 14 bytes: accel x y z, temperature, gyro x y z
const uint8_t PWR_MGMT_1 = 0x6B;
const uint8_t PWR_MGMT_2 = 0x6C;
const uint8_t WHO_AM_I = 0x75;

const uint8_t RESET = 0x80;
const uint8_t CLOCK_PLL = 0x01;
const uint8_t DATA_READY = 0x01;
const uint8_t RATE_100HZ = 1000 / 100 - 1;  // internal rate 1 kHz / (1 + divider)
// About 41 Hz (gyro) / 45 Hz (accelerometer): just below the 50 Hz limit for clean 100 Hz
// sampling, and far above the 1-10 Hz of hand gestures, so gesture shapes are untouched.
const uint8_t LOW_PASS_45HZ = 3;
const uint8_t GYRO_2000DPS = 3 << 3;  // matches imu_units::GYRO_COUNTS_PER_DPS
const uint8_t ACCEL_8G = 2 << 3;      // matches imu_units::ACCEL_COUNTS_PER_G

const uint8_t ID_MPU6050 = 0x68;
const uint8_t ID_MPU6500 = 0x70;
const uint8_t ID_MPU9250 = 0x71;
const uint8_t ID_MPU9255 = 0x73;
}  // namespace mpu

// ---------------------------------------------------------------------------
// BLE_LINK

static BLECharacteristic* eventsCharacteristic = nullptr;
static volatile bool bleConnected = false;
// Commands arrive on the BLE task; loop() handles them so all wand logic runs in one place.
static QueueHandle_t commandQueue = nullptr;

static void sendEvent(uint8_t* data, size_t length) {
  if (!bleConnected) return;
  eventsCharacteristic->setValue(data, length);
  eventsCharacteristic->notify();
}

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    bleConnected = true;
  }
  void onDisconnect(BLEServer*) override {
    bleConnected = false;
    BLEDevice::startAdvertising();  // let the Mac reconnect
  }
};

class CommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* characteristic) override {
    protocol::Command command;
    if (protocol::decodeCommand(characteristic->getData(), characteristic->getLength(), command)) {
      xQueueSend(commandQueue, &command, 0);
    }
  }
};

static void startBle() {
  commandQueue = xQueueCreate(8, sizeof(protocol::Command));
  BLEDevice::init(DEVICE_NAME);
  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  BLEService* service = server->createService(SERVICE_UUID);

  eventsCharacteristic = service->createCharacteristic(EVENTS_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  eventsCharacteristic->addDescriptor(new BLE2902());  // lets the Mac switch notifications on

  BLECharacteristic* commands = service->createCharacteristic(
      COMMANDS_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  commands->setCallbacks(new CommandCallbacks());

  service->start();
  BLEDevice::getAdvertising()->addServiceUUID(SERVICE_UUID);
  BLEDevice::getAdvertising()->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.println("BLE advertising as SpellWand");
}

// The state machine reports CAST_START / CAST_END through this.
class BleEvents : public WandEvents {
 public:
  void castStart(uint8_t source) override {
    uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
    sendEvent(buffer, protocol::encodeCastStart(buffer, source));
    Serial.printf("CAST_START (%s)\n", source == protocol::SOURCE_RECORDING ? "recording" : "button");
  }
  void castEnd(uint16_t sampleCount, uint8_t reason) override {
    uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
    sendEvent(buffer, protocol::encodeCastEnd(buffer, sampleCount, reason));
    Serial.printf("CAST_END: %u samples, reason %u\n", (unsigned)sampleCount, (unsigned)reason);
  }
};

static BleEvents bleEvents;
static WandStateMachine wand(bleEvents);
static Debouncer castButton;
static ActionOutput actionLed;

// ---------------------------------------------------------------------------
// IMU

static uint8_t imuAddress = 0;
static bool imuReady = false;
static GyroBias gyroBias;

static bool i2cDevicePresent(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

static bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

static bool readRegisters(uint8_t reg, uint8_t* out, uint8_t length) {
  Wire.beginTransmission(imuAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;  // keep the bus for the read
  if (Wire.requestFrom(imuAddress, length) != length) return false;
  for (uint8_t i = 0; i < length; i++) out[i] = Wire.read();
  return true;
}

static const char* chipName(uint8_t id) {
  switch (id) {
    case mpu::ID_MPU9250: return "MPU-9250";
    case mpu::ID_MPU6500: return "MPU-6500";
    case mpu::ID_MPU9255: return "MPU-9255";
    case mpu::ID_MPU6050: return "MPU-6050";
    default: return "unknown chip";
  }
}

static bool startImu() {
  for (uint8_t address : MPU_ADDRESSES) {
    if (!i2cDevicePresent(address)) continue;
    imuAddress = address;
    uint8_t id = 0;
    readRegisters(mpu::WHO_AM_I, &id, 1);
    Serial.printf("IMU answered at 0x%02X: WHO_AM_I = 0x%02X (%s)\n", address, id, chipName(id));
    if (id != mpu::ID_MPU9250 && id != mpu::ID_MPU6500 && id != mpu::ID_MPU9255) {
      Serial.println("WARNING: not an MPU-9250/6500; trying anyway (it may be a clone).");
    }

    writeRegister(mpu::PWR_MGMT_1, mpu::RESET);
    delay(100);                                     // power-up time after a reset
    writeRegister(mpu::PWR_MGMT_1, mpu::CLOCK_PLL); // wake up, use the gyro's accurate clock
    writeRegister(mpu::PWR_MGMT_2, 0x00);           // accelerometer and gyro all on
    writeRegister(mpu::SMPLRT_DIV, mpu::RATE_100HZ);
    writeRegister(mpu::CONFIG, mpu::LOW_PASS_45HZ);
    writeRegister(mpu::GYRO_CONFIG, mpu::GYRO_2000DPS);
    writeRegister(mpu::ACCEL_CONFIG, mpu::ACCEL_8G);
    if (id != mpu::ID_MPU6050) writeRegister(mpu::ACCEL_CONFIG_2, mpu::LOW_PASS_45HZ);
    writeRegister(mpu::INT_ENABLE, mpu::DATA_READY);
    delay(100);  // let the gyro start up (about 70 ms)

    // Read the ranges back: if they didn't stick, every reading would be scaled wrongly.
    uint8_t gyroConfig = 0, accelConfig = 0;
    readRegisters(mpu::GYRO_CONFIG, &gyroConfig, 1);
    readRegisters(mpu::ACCEL_CONFIG, &accelConfig, 1);
    if ((gyroConfig & 0x18) != mpu::GYRO_2000DPS || (accelConfig & 0x18) != mpu::ACCEL_8G) {
      Serial.printf("ERROR: IMU settings didn't stick (GYRO_CONFIG 0x%02X, ACCEL_CONFIG 0x%02X).\n",
                    gyroConfig, accelConfig);
      return false;
    }
    Serial.println("IMU ready: 100 Hz, +-8 g, +-2000 deg/s, 45 Hz low-pass");
    return true;
  }
  Serial.println("ERROR: no IMU at 0x68 or 0x69. Check SDA, SCL, 3V3 and GND.");
  return false;
}

// Reads one new reading if the IMU has one. Returns false if there is none yet.
static bool readMpu(float accel[3], float gyro[3]) {
  uint8_t status = 0;
  if (!readRegisters(mpu::INT_STATUS, &status, 1) || !(status & mpu::DATA_READY)) return false;
  uint8_t raw[14];
  if (!readRegisters(mpu::ACCEL_XOUT_H, raw, sizeof(raw))) return false;
  for (int k = 0; k < 3; k++) {
    accel[k] = imu_units::accelToMs2(imu_units::fromBigEndian(raw[2 * k], raw[2 * k + 1]));
    gyro[k] = imu_units::gyroToRadS(imu_units::fromBigEndian(raw[8 + 2 * k], raw[9 + 2 * k]));
  }
  return true;
}

// At boot, measure the gyro offset while the wand lies still (up to GYRO_CALIBRATION_MS).
static void calibrateGyro() {
  Serial.println("Keep the wand still: measuring the gyro offset...");
  uint32_t start = millis();
  float accel[3], gyro[3];
  while (!gyroBias.ready() && millis() - start < GYRO_CALIBRATION_MS) {
    if (readMpu(accel, gyro)) gyroBias.update(gyro, accel);
  }
  if (gyroBias.ready()) {
    Serial.printf("Gyro offset: %.2f %.2f %.2f deg/s\n", gyroBias.offset(0) / imu_units::RAD_PER_DEG,
                  gyroBias.offset(1) / imu_units::RAD_PER_DEG, gyroBias.offset(2) / imu_units::RAD_PER_DEG);
  } else {
    Serial.println("The wand kept moving; the gyro offset will be measured the next time it is still.");
  }
}

// Each reading becomes one MotionSample, sent only while CASTING. While IDLE, still
// moments keep the gyro offset up to date (it drifts as the chip warms up).
static void readImu(uint32_t now) {
  static uint32_t lastPollUs = 0;
  if (micros() - lastPollUs < IMU_POLL_US) return;
  lastPollUs = micros();

  float accel[3], gyro[3];
  if (!readMpu(accel, gyro)) return;
  if (wand.state() == WandState::IDLE) {
    gyroBias.update(gyro, accel);
  } else {
    gyroBias.restart();
  }
  gyroBias.correct(gyro);

  if (!wand.streaming()) return;
  protocol::MotionSample sample;
  sample.index = wand.nextSampleIndex();
  sample.t_ms = now;
  sample.ax = accel[0];
  sample.ay = accel[1];
  sample.az = accel[2];
  sample.gx = gyro[0];
  sample.gy = gyro[1];
  sample.gz = gyro[2];
  uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
  sendEvent(buffer, protocol::encodeMotionSample(buffer, sample));
}

// ---------------------------------------------------------------------------
// Commands from the Mac

static void handleCommand(const protocol::Command& command, uint32_t now) {
  switch (command.type) {
    case protocol::START_RECORDING:
      wand.startRecording(now);
      break;
    case protocol::STOP_RECORDING:
      wand.stopRecording(now);
      break;
    case protocol::GESTURE_RESULT:
      Serial.printf("GESTURE_RESULT: %s\n", command.label);
      wand.gestureResult(command.label, command.color, now);
      break;
    case protocol::EXECUTE_ACTION: {
      bool ok = actionLed.execute(command.action, now);
      uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
      sendEvent(buffer, protocol::encodeActionComplete(buffer, command.action, ok));
      Serial.printf("EXECUTE_ACTION %u: %s\n", (unsigned)command.action, ok ? "done" : "unknown action");
      break;
    }
  }
}

// ---------------------------------------------------------------------------

static void updateLeds(uint32_t now) {
  static Rgb shown = {1, 2, 3};  // impossible start value forces the first write
  Rgb c = wand.ledColor(now);
  if (c.r != shown.r || c.g != shown.g || c.b != shown.b) {
    shown = c;
    neopixelWrite(STATUS_LED_PIN, c.r * LED_BRIGHTNESS / 255, c.g * LED_BRIGHTNESS / 255,
                  c.b * LED_BRIGHTNESS / 255);
  }
  digitalWrite(ACTION_LED_PIN, actionLed.level(now) ? HIGH : LOW);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // give the USB-serial adapter a moment so the banner isn't lost
  Serial.println();
  Serial.println("=== SpellWand firmware booted ===");

  pinMode(CAST_BUTTON_PIN, INPUT_PULLUP);
  pinMode(ACTION_LED_PIN, OUTPUT);
  updateLeds(millis());

  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN, I2C_CLOCK_HZ);
  imuReady = startImu();
  if (imuReady) calibrateGyro();
  startBle();
}

void loop() {
  uint32_t now = millis();

  // Retry the IMU if it was missing at boot (everything else keeps working meanwhile).
  static uint32_t lastImuAttemptMs = 0;
  if (!imuReady && now - lastImuAttemptMs >= IMU_RETRY_MS) {
    lastImuAttemptMs = now;
    imuReady = startImu();  // the gyro offset is then learnt while the wand sits IDLE
  }
  if (imuReady) readImu(now);

  // A lost connection ends any recording in progress.
  static bool wasConnected = false;
  if (wasConnected && !bleConnected) wand.connectionLost(now);
  if (bleConnected != wasConnected) Serial.println(bleConnected ? "Mac connected" : "Mac disconnected");
  wasConnected = bleConnected;

  protocol::Command command;
  while (xQueueReceive(commandQueue, &command, 0) == pdTRUE) handleCommand(command, now);

  if (castButton.update(digitalRead(CAST_BUTTON_PIN) == LOW, now)) {
    wand.buttonChanged(castButton.pressed(), now);
  }

  static WandState lastState = WandState::IDLE;
  wand.tick(now);
  if (wand.state() != lastState) {
    lastState = wand.state();
    Serial.printf("State: %s\n", stateName(lastState));
  }

  updateLeds(now);
}
