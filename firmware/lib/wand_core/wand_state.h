// The wand's operating states (IDLE, CASTING, INFLIGHT) and STATUS_LED colours.
// No Arduino code here, so the logic can be tested on a computer (test/test_wand_core).
#pragma once
#include <stdint.h>

#include "protocol.h"
#include "rgb.h"

enum class WandState : uint8_t { IDLE, CASTING, INFLIGHT };

const char* stateName(WandState state);

// Colours for the wand's own states. Spell colours are not here: they live only in the
// Mac's config.json and arrive with each GESTURE_RESULT.
namespace colors {
const Rgb IDLE = {8, 8, 8};          // dim white
const Rgb CASTING = {0, 0, 255};     // blue
const Rgb INFLIGHT = {255, 150, 0};  // amber: waiting for the Mac
const Rgb NO_ANSWER = {255, 0, 255}; // magenta flashes: no GESTURE_RESULT arrived
}  // namespace colors

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
  static const uint32_t SPELL_SHOW_MS = 1000;     // how long the spell colour stays on
  static const uint32_t FLASH_MS = 150;           // on time and off time of one flash

  explicit WandStateMachine(WandEvents& events) : events_(events) {}

  // Inputs. `now` is millis().
  void buttonChanged(bool pressed, uint32_t now);  // debounced CAST_BUTTON
  void startRecording(uint32_t now);               // START_RECORDING from the Mac
  void stopRecording(uint32_t now);                // STOP_RECORDING from the Mac
  void gestureResult(const char* label, Rgb color, uint32_t now);  // shows `color` as sent
  void connectionLost(uint32_t now);
  void tick(uint32_t now);  // call every loop: handles timeouts and ends feedback

  // Call once for each MOTION_SAMPLE sent while streaming; returns its index.
  uint16_t nextSampleIndex() { return sampleCount_++; }

  WandState state() const { return state_; }
  bool streaming() const { return state_ == WandState::CASTING; }
  Rgb ledColor(uint32_t now) const;

 private:
  void beginCast(uint8_t source, uint32_t now);
  void endCast(uint8_t reason, uint32_t now);
  void showFeedback(Rgb color, uint8_t flashes, uint32_t now);
  uint32_t feedbackDuration() const;

  WandEvents& events_;
  WandState state_ = WandState::IDLE;
  uint8_t source_ = protocol::SOURCE_CAST_BUTTON;
  uint32_t castStartMs_ = 0;
  uint16_t sampleCount_ = 0;
  uint32_t inflightStartMs_ = 0;

  // Short-lived LED feedback shown at the end of INFLIGHT (separate from the state).
  bool feedbackActive_ = false;
  Rgb feedbackColor_ = {0, 0, 0};
  uint8_t feedbackFlashes_ = 0;  // 0 = solid colour
  uint32_t feedbackStartMs_ = 0;
};
