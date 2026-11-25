// The wand's operating states: IDLE, CASTING, INFLIGHT.
// No Arduino code here, so the logic can be tested on a computer (test/test_wand_core).
#pragma once
#include <stdint.h>

#include "protocol.h"

enum class WandState : uint8_t { IDLE, CASTING, INFLIGHT };

const char* stateName(WandState state);

// What the state machine asks the rest of the firmware to send over BLE_LINK.
class WandEvents {
 public:
  virtual ~WandEvents() {}
  virtual void castStart(uint8_t source) = 0;
  virtual void castEnd(uint16_t sampleCount, uint8_t reason) = 0;
};

class WandStateMachine {
 public:
  static const uint32_t MAX_CAST_MS = 3000;       // longest button cast
  static const uint32_t MAX_RECORDING_MS = 5000;  // longest training recording
  static const uint32_t RESULT_TIMEOUT_MS = 2000; // wait this long for GESTURE_RESULT

  explicit WandStateMachine(WandEvents& events) : events_(events) {}

  // Inputs. `now` is millis().
  void buttonChanged(bool pressed, uint32_t now);  // debounced CAST_BUTTON
  void startRecording(uint32_t now);               // START_RECORDING from the Mac
  void stopRecording(uint32_t now);                // STOP_RECORDING from the Mac
  void gestureResult();                            // GESTURE_RESULT from the Mac, any label
  void connectionLost(uint32_t now);
  void tick(uint32_t now);  // call every loop: handles the time limits

  // Call once for each MOTION_SAMPLE sent while streaming; returns its index.
  uint16_t nextSampleIndex() { return sampleCount_++; }

  WandState state() const { return state_; }
  bool streaming() const { return state_ == WandState::CASTING; }

 private:
  void beginCast(uint8_t source, uint32_t now);
  void endCast(uint8_t reason, uint32_t now);

  WandEvents& events_;
  WandState state_ = WandState::IDLE;
  uint8_t source_ = protocol::SOURCE_CAST_BUTTON;
  uint32_t castStartMs_ = 0;
  uint16_t sampleCount_ = 0;
  uint32_t inflightStartMs_ = 0;
};
