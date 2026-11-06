// SpellWand firmware
//
// Hardware glue around the tested logic in lib/wand_core:
//   IMU (BNO080 / BNO085 / BNO086, I2C) -> MOTION_SAMPLE events while CASTING
//   CAST_BUTTON        -> debounced, drives IDLE / CASTING / INFLIGHT
//   STATUS_LED         -> colour from the state machine (4-leg RGB LED, PWM on three pins)
//   BLE_LINK           -> events notified to the Mac, commands written by the Mac
// Message format: docs/protocol.md

#include <Arduino.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <Wire.h>

#include "SparkFun_BNO08x_Arduino_Library.h"
#include "debouncer.h"
#include "imu_pairing.h"
#include "protocol.h"
#include "rgb_led.h"
#include "wand_state.h"

// ---- Pins (see the wiring table in README.md) ----
static const int IMU_SDA_PIN = 21;
static const int IMU_SCL_PIN = 22;
// INT and RST make the BNO08x link much more reliable (SparkFun recommends both).
// Set a pin to -1 if that wire is NOT connected: a defined-but-unwired INT pin
// makes every read wait 500 ms and then time out.
static const int IMU_INT_PIN = 4;
static const int IMU_RST_PIN = 26;
static const int CAST_BUTTON_PIN = 27;  // to GND, internal pull-up: LOW = pressed
static const int STATUS_LED_RED_PIN = 18;    // each through its resistor to the RGB LED's legs
static const int STATUS_LED_GREEN_PIN = 19;
static const int STATUS_LED_BLUE_PIN = 23;

// ---- Settings ----
static const uint32_t SERIAL_BAUD = 115200;
static const uint16_t IMU_REPORT_INTERVAL_MS = 10;  // 100 Hz accelerometer + gyroscope
static const uint32_t I2C_FAST_CLOCK_HZ = 400000;   // drop to 100000 if readings are flaky
static const uint32_t IMU_RETRY_MS = 2000;
static const uint8_t LED_BRIGHTNESS = 255;          // 0-255; the resistors already limit the current
// Common cathode: the LED's long leg goes to GND. Common anode: long leg to 3.3 V -> set true.
static const bool STATUS_LED_COMMON_ANODE = false;
static const uint32_t LED_PWM_HZ = 5000;            // fast enough that the eye sees no flicker

// BLE_LINK identifiers: must match mac_app/protocol.py
static const char* DEVICE_NAME = "SpellWand";
static const char* SERVICE_UUID = "06f40001-a27b-408d-a176-2e94b74b3ad3";
static const char* EVENTS_UUID = "06f40002-a27b-408d-a176-2e94b74b3ad3";
static const char* COMMANDS_UUID = "06f40003-a27b-408d-a176-2e94b74b3ad3";

// SparkFun and most no-name BNO08x boards answer at 0x4B; Adafruit's answers at 0x4A.
static const uint8_t BNO08X_ADDRESSES[] = {0x4B, 0x4A};

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

static uint32_t lastCastEndMs = 0;  // to time how long the Mac's answer takes

// The state machine reports CAST_START / CAST_END through this.
class BleEvents : public WandEvents {
 public:
  void castStart(uint8_t source) override {
    uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
    sendEvent(buffer, protocol::encodeCastStart(buffer, source));
    Serial.printf("CAST_START (%s)\n", source == protocol::SOURCE_RECORDING ? "recording" : "button");
  }
  void castEnd(uint16_t sampleCount, uint8_t reason) override {
    lastCastEndMs = millis();
    uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
    sendEvent(buffer, protocol::encodeCastEnd(buffer, sampleCount, reason));
    Serial.printf("CAST_END: %u samples, reason %u\n", (unsigned)sampleCount, (unsigned)reason);
  }
};

static BleEvents bleEvents;
static WandStateMachine wand(bleEvents);
static Debouncer castButton;

// ---------------------------------------------------------------------------
// IMU

static BNO08x imu;
static bool imuReady = false;
static ImuPairing imuPairing;

static bool i2cDevicePresent(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

// Each reading becomes one MotionSample, sent only while CASTING. The BNO08x keeps its own
// gyro offset up to date, so the readings need no correction here.
static void handleReading(const ImuReading& reading, uint32_t now) {
#ifdef IMU_SERIAL_LOG
  // Component test build (env:imu_log): every reading over USB, in the units the Mac receives.
  Serial.printf("IMU,%lu,%.3f,%.3f,%.3f,%.4f,%.4f,%.4f\n", (unsigned long)now, reading.accel[0], reading.accel[1],
                reading.accel[2], reading.gyro[0], reading.gyro[1], reading.gyro[2]);
#endif

  if (!wand.streaming()) return;
  protocol::MotionSample sample;
  sample.index = wand.nextSampleIndex();
  sample.t_ms = now;
  sample.ax = reading.accel[0];
  sample.ay = reading.accel[1];
  sample.az = reading.accel[2];
  sample.gx = reading.gyro[0];
  sample.gy = reading.gyro[1];
  sample.gz = reading.gyro[2];
  uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
  sendEvent(buffer, protocol::encodeMotionSample(buffer, sample));
}

// One packet from the BNO08x can hold several reports, and the library's own handler keeps
// only the last of them, so every report is taken here instead.
static void onImuReport(void*, sh2_SensorEvent_t* event) {
  sh2_SensorValue_t value;
  if (sh2_decodeSensorEvent(&value, event) != SH2_OK) return;
  if (value.sensorId == SENSOR_REPORTID_ACCELEROMETER) {
    imuPairing.accel(value.un.accelerometer.x, value.un.accelerometer.y, value.un.accelerometer.z);
  } else if (value.sensorId == SENSOR_REPORTID_GYROSCOPE_CALIBRATED) {
    ImuReading reading;
    if (imuPairing.gyro(value.un.gyroscope.x, value.un.gyroscope.y, value.un.gyroscope.z, reading)) {
      handleReading(reading, millis());
    }
  }
}

static void enableImuReports() {
  bool accelOk = imu.enableAccelerometer(IMU_REPORT_INTERVAL_MS);
  bool gyroOk = imu.enableGyro(IMU_REPORT_INTERVAL_MS);
  Serial.printf("IMU reports: accelerometer %s, gyroscope %s\n", accelOk ? "on" : "FAILED", gyroOk ? "on" : "FAILED");
}

static bool startImu() {
  for (uint8_t address : BNO08X_ADDRESSES) {
    if (!i2cDevicePresent(address)) continue;
    Serial.printf("BNO08x answered at 0x%02X\n", address);
    if (!imu.begin(address, Wire, IMU_INT_PIN, IMU_RST_PIN)) {
      Serial.println("ERROR: BNO08x found but begin() failed. If INT/RST are not wired, set them to -1.");
      return false;
    }
    sh2_setSensorCallback(onImuReport, nullptr);
    Wire.setClock(I2C_FAST_CLOCK_HZ);
    if (imu.prodIds.numEntries > 0) {
      const sh2_ProductId_t& id = imu.prodIds.entry[0];
      Serial.printf("IMU software: part %lu, version %u.%u.%u, build %lu\n", (unsigned long)id.swPartNumber,
                    id.swVersionMajor, id.swVersionMinor, id.swVersionPatch, (unsigned long)id.swBuildNumber);
    }
    enableImuReports();
    return true;
  }
  Serial.println("ERROR: no BNO08x at 0x4A or 0x4B. Check SDA, SCL, 3V3 and GND.");
  return false;
}

// With INT wired, only talk to the IMU when it says data is ready (INT low);
// otherwise the library blocks for up to 500 ms and then resets the sensor.
static void readImu() {
  if (IMU_INT_PIN < 0 || digitalRead(IMU_INT_PIN) == LOW) sh2_service();
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
      Serial.printf("GESTURE_RESULT: %s, %lu ms after CAST_END\n", command.label,
                    (unsigned long)(millis() - lastCastEndMs));
      wand.gestureResult(command.label, command.color, now);
      break;
    case protocol::EXECUTE_ACTION: {
      // Reserved in the protocol, but this wand has no action outputs: answer "not done".
      uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
      sendEvent(buffer, protocol::encodeActionComplete(buffer, command.action, false));
      Serial.printf("EXECUTE_ACTION %u: no action outputs on this wand\n", (unsigned)command.action);
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// STATUS_LED (RGB LED on three PWM channels)

static const int LED_PINS[3] = {STATUS_LED_RED_PIN, STATUS_LED_GREEN_PIN, STATUS_LED_BLUE_PIN};

static void startStatusLed() {
  for (int channel = 0; channel < 3; channel++) {
    ledcSetup(channel, LED_PWM_HZ, 8);  // 8-bit duty: 0-255, like the colour values
    ledcAttachPin(LED_PINS[channel], channel);
  }
}

static void updateStatusLed(uint32_t now) {
  static Rgb shown = {1, 2, 3};  // impossible start value forces the first write
  Rgb c = wand.ledColor(now);
  if (c.r != shown.r || c.g != shown.g || c.b != shown.b) {
    shown = c;
    ledcWrite(0, rgb_led::duty(c.r, LED_BRIGHTNESS, STATUS_LED_COMMON_ANODE));
    ledcWrite(1, rgb_led::duty(c.g, LED_BRIGHTNESS, STATUS_LED_COMMON_ANODE));
    ledcWrite(2, rgb_led::duty(c.b, LED_BRIGHTNESS, STATUS_LED_COMMON_ANODE));
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // give the USB-serial adapter a moment so the banner isn't lost
  Serial.println();
  Serial.println("=== SpellWand firmware booted ===");

  pinMode(CAST_BUTTON_PIN, INPUT_PULLUP);
  startStatusLed();
  updateStatusLed(millis());

  // Start at the default 100 kHz: the BNO08x start-up handshake is most reliable there.
  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  imuReady = startImu();
  startBle();
}

void loop() {
  uint32_t now = millis();

  // Retry the IMU if it was missing at boot (everything else keeps working meanwhile).
  static uint32_t lastImuAttemptMs = 0;
  if (!imuReady && now - lastImuAttemptMs >= IMU_RETRY_MS) {
    lastImuAttemptMs = now;
    imuReady = startImu();
  }
  if (imuReady) {
    if (imu.wasReset()) {
      Serial.println("IMU reset detected, re-enabling reports");
      enableImuReports();
    }
    readImu();
  }

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

  updateStatusLed(now);
}
