// SpellWand firmware
//
// Hardware glue around the tested logic in lib/wand_core:
//   IMU (BNO086, I2C)  -> MOTION_SAMPLE events while CASTING
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

#include "SparkFun_BNO08x_Arduino_Library.h"
#include "action_output.h"
#include "debouncer.h"
#include "protocol.h"
#include "wand_state.h"

// ---- Pins (see the wiring table in README.md) ----
static const int IMU_SDA_PIN = 21;
static const int IMU_SCL_PIN = 22;
// INT and RST make the BNO086 link much more reliable (SparkFun recommends both).
// Set a pin to -1 if that wire is NOT connected: a defined-but-unwired INT pin
// makes every read wait 500 ms and then time out.
static const int IMU_INT_PIN = 4;
static const int IMU_RST_PIN = 23;
static const int CAST_BUTTON_PIN = 27;  // to GND, internal pull-up: LOW = pressed
static const int STATUS_LED_PIN = 18;   // WS2812B data in
static const int ACTION_LED_PIN = 26;   // LED + 330 ohm resistor to GND

// ---- Settings ----
static const uint32_t SERIAL_BAUD = 115200;
static const uint16_t IMU_REPORT_INTERVAL_MS = 10;  // 100 Hz accelerometer + gyroscope
static const uint32_t I2C_FAST_CLOCK_HZ = 400000;   // drop to 100000 if readings are flaky
static const uint32_t IMU_RETRY_MS = 2000;
static const uint8_t LED_BRIGHTNESS = 64;           // 0-255; a WS2812B at full power is dazzling

// BLE_LINK identifiers: must match mac_app/protocol.py
static const char* DEVICE_NAME = "SpellWand";
static const char* SERVICE_UUID = "06f40001-a27b-408d-a176-2e94b74b3ad3";
static const char* EVENTS_UUID = "06f40002-a27b-408d-a176-2e94b74b3ad3";
static const char* COMMANDS_UUID = "06f40003-a27b-408d-a176-2e94b74b3ad3";

// The SparkFun BNO086 board answers at 0x4B; most other BNO08x boards use 0x4A.
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

static BNO08x imu;
static bool imuReady = false;
static float latestAccel[3] = {0, 0, 0};

static bool i2cDevicePresent(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
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
    Wire.setClock(I2C_FAST_CLOCK_HZ);
    enableImuReports();
    return true;
  }
  Serial.println("ERROR: no BNO08x at 0x4A or 0x4B. Check SDA, SCL, 3V3 and GND.");
  return false;
}

// Reads one IMU event if one is ready. Each gyroscope event becomes one MotionSample
// (paired with the latest accelerometer reading), sent only while CASTING.
static void readImu(uint32_t now) {
  // With INT wired, only talk to the IMU when it says data is ready (INT low);
  // otherwise the library blocks for up to 500 ms and then resets the sensor.
  bool dataReady = (IMU_INT_PIN < 0) || (digitalRead(IMU_INT_PIN) == LOW);
  if (!dataReady || !imu.getSensorEvent()) return;

  uint8_t id = imu.getSensorEventID();
  if (id == SENSOR_REPORTID_ACCELEROMETER) {
    latestAccel[0] = imu.getAccelX();
    latestAccel[1] = imu.getAccelY();
    latestAccel[2] = imu.getAccelZ();
  } else if (id == SENSOR_REPORTID_GYROSCOPE_CALIBRATED && wand.streaming()) {
    protocol::MotionSample sample;
    sample.index = wand.nextSampleIndex();
    sample.t_ms = now;
    sample.ax = latestAccel[0];
    sample.ay = latestAccel[1];
    sample.az = latestAccel[2];
    sample.gx = imu.getGyroX();
    sample.gy = imu.getGyroY();
    sample.gz = imu.getGyroZ();
    uint8_t buffer[protocol::MAX_MESSAGE_BYTES];
    sendEvent(buffer, protocol::encodeMotionSample(buffer, sample));
  }
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

  // Start at the default 100 kHz: the BNO086 start-up handshake is most reliable there.
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
    readImu(now);
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

  updateLeds(now);
}
