// Messages waiting to go out over Bluetooth. When the radio is busy it refuses a message; the
// message then stays at the front and is tried again later, so nothing is lost while there is
// room. The last RESERVED slots are kept for important messages (CAST_START, CAST_END,
// ACTION_COMPLETE), so a long backlog of readings can never push out the end of a cast.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "protocol.h"

template <size_t CAPACITY, size_t RESERVED>
class SendQueue {
 public:
  // Returns false, and counts the message as dropped, when there is no room for it.
  bool push(const uint8_t* data, size_t length, bool important) {
    size_t limit = important ? CAPACITY : CAPACITY - RESERVED;
    if (length > protocol::MAX_MESSAGE_BYTES) return false;
    if (count_ >= limit) {
      dropped_++;
      return false;
    }
    Slot& slot = slots_[(head_ + count_) % CAPACITY];
    memcpy(slot.data, data, length);
    slot.length = length;
    count_++;
    return true;
  }

  // The oldest message, without removing it. Returns false when the queue is empty.
  bool front(const uint8_t*& data, size_t& length) const {
    if (count_ == 0) return false;
    data = slots_[head_].data;
    length = slots_[head_].length;
    return true;
  }

  // Removes the oldest message, once it has been sent.
  void pop() {
    if (count_ == 0) return;
    head_ = (head_ + 1) % CAPACITY;
    count_--;
  }

  void clear() {
    head_ = 0;
    count_ = 0;
  }

  size_t size() const { return count_; }
  uint32_t dropped() const { return dropped_; }

 private:
  struct Slot {
    uint8_t data[protocol::MAX_MESSAGE_BYTES];
    size_t length;
  };
  Slot slots_[CAPACITY];
  size_t head_ = 0;
  size_t count_ = 0;
  uint32_t dropped_ = 0;
};
