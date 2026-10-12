#include "wand_state.h"

#include <string.h>

const char* stateName(WandState state) {
  switch (state) {
    case WandState::IDLE: return "IDLE";
    case WandState::CASTING: return "CASTING";
    case WandState::INFLIGHT: return "INFLIGHT";
  }
  return "?";
}

Rgb spellColor(const char* label) {
  if (strcmp(label, "CIRCLE") == 0) return colors::CIRCLE;
  if (strcmp(label, "ZIGZAG") == 0) return colors::ZIGZAG;
  if (strcmp(label, "HORIZONTAL_LINE") == 0) return colors::HORIZONTAL_LINE;
  if (strcmp(label, "UNKNOWN") == 0) return colors::UNKNOWN;
  return colors::OTHER_SPELL;
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

void WandStateMachine::gestureResult(const char* label, Rgb color, uint32_t now) {
  if (state_ != WandState::INFLIGHT || feedbackActive_) return;  // late or unexpected
  if (isBlack(color)) color = spellColor(label);
  bool unknown = strcmp(label, "UNKNOWN") == 0;
  showFeedback(color, unknown ? 3 : 0, now);
}

void WandStateMachine::connectionLost(uint32_t now) {
  if (state_ == WandState::CASTING) endCast(protocol::END_CONNECTION_LOST, now);
}

void WandStateMachine::tick(uint32_t now) {
  if (state_ == WandState::CASTING) {
    uint32_t limit = source_ == protocol::SOURCE_RECORDING ? MAX_RECORDING_MS : MAX_CAST_MS;
    if (now - castStartMs_ >= limit) endCast(protocol::END_MAX_DURATION, now);
  } else if (state_ == WandState::INFLIGHT) {
    if (feedbackActive_) {
      if (now - feedbackStartMs_ >= feedbackDuration()) {
        feedbackActive_ = false;
        state_ = WandState::IDLE;
      }
    } else if (now - inflightStartMs_ >= RESULT_TIMEOUT_MS) {
      showFeedback(colors::NO_ANSWER, 2, now);
    }
  }
}

Rgb WandStateMachine::ledColor(uint32_t now) const {
  if (feedbackActive_) {
    if (feedbackFlashes_ == 0) return feedbackColor_;
    bool lit = ((now - feedbackStartMs_) / FLASH_MS) % 2 == 0;
    return lit ? feedbackColor_ : Rgb{0, 0, 0};
  }
  switch (state_) {
    case WandState::CASTING: return colors::CASTING;
    case WandState::INFLIGHT: return colors::INFLIGHT;
    default: return colors::IDLE;
  }
}

void WandStateMachine::beginCast(uint8_t source, uint32_t now) {
  state_ = WandState::CASTING;
  source_ = source;
  castStartMs_ = now;
  sampleCount_ = 0;
  feedbackActive_ = false;
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

void WandStateMachine::showFeedback(Rgb color, uint8_t flashes, uint32_t now) {
  feedbackActive_ = true;
  feedbackColor_ = color;
  feedbackFlashes_ = flashes;
  feedbackStartMs_ = now;
}

uint32_t WandStateMachine::feedbackDuration() const {
  return feedbackFlashes_ == 0 ? SPELL_SHOW_MS : 2u * FLASH_MS * feedbackFlashes_;
}
