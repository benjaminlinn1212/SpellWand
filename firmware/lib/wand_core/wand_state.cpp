#include "wand_state.h"

const char* stateName(WandState state) {
  switch (state) {
    case WandState::IDLE: return "IDLE";
    case WandState::CASTING: return "CASTING";
    case WandState::INFLIGHT: return "INFLIGHT";
  }
  return "?";
}

void WandStateMachine::buttonChanged(bool pressed, uint32_t now) {
  if (pressed && state_ == WandState::IDLE) {
    beginCast(protocol::SOURCE_CAST_BUTTON, now);
  } else if (!pressed && state_ == WandState::CASTING && source_ == protocol::SOURCE_CAST_BUTTON) {
    endCast(protocol::END_NORMAL, now);
  }
}

void WandStateMachine::startRecording(uint32_t now) {
  if (state_ == WandState::IDLE) beginCast(protocol::SOURCE_RECORDING, now);
}

void WandStateMachine::stopRecording(uint32_t now) {
  if (state_ == WandState::CASTING && source_ == protocol::SOURCE_RECORDING) {
    endCast(protocol::END_NORMAL, now);
  }
}

void WandStateMachine::gestureResult() {
  // The answer to the cast in flight. Any other result is late or unexpected: ignore it.
  if (state_ == WandState::INFLIGHT) state_ = WandState::IDLE;
}

void WandStateMachine::connectionLost(uint32_t now) {
  if (state_ == WandState::CASTING) endCast(protocol::END_CONNECTION_LOST, now);
}

void WandStateMachine::tick(uint32_t now) {
  if (state_ == WandState::CASTING) {
    uint32_t limit = source_ == protocol::SOURCE_RECORDING ? MAX_RECORDING_MS : MAX_CAST_MS;
    if (now - castStartMs_ >= limit) endCast(protocol::END_MAX_DURATION, now);
  } else if (state_ == WandState::INFLIGHT) {
    // No GESTURE_RESULT in time (the Mac is gone or busy): give up so the wand can cast again.
    if (now - inflightStartMs_ >= RESULT_TIMEOUT_MS) state_ = WandState::IDLE;
  }
}

void WandStateMachine::beginCast(uint8_t source, uint32_t now) {
  state_ = WandState::CASTING;
  source_ = source;
  castStartMs_ = now;
  sampleCount_ = 0;
  events_.castStart(source);
}

void WandStateMachine::endCast(uint8_t reason, uint32_t now) {
  events_.castEnd(sampleCount_, reason);
  if (source_ == protocol::SOURCE_CAST_BUTTON) {
    state_ = WandState::INFLIGHT;  // the Mac classifies; wait for GESTURE_RESULT
    inflightStartMs_ = now;
  } else {
    state_ = WandState::IDLE;  // training recording: nothing to classify
  }
}
