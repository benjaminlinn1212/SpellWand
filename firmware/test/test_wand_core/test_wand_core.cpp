// Tests for the hardware-independent wand logic in lib/wand_core.
// They run on the Mac, no ESP32 needed:
//
//     ~/.platformio/penv/bin/pio test -e native

#include <string.h>
#include <unity.h>

#include "debouncer.h"
#include "imu_pairing.h"
#include "rgb_led.h"
#include "protocol.h"
#include "send_queue.h"
#include "wand_axes.h"
#include "wand_state.h"

void setUp() {}
void tearDown() {}

// ---------- protocol (example bytes from docs/protocol.md) ----------

static void test_events_encode_to_the_documented_bytes() {
  uint8_t out[protocol::MAX_MESSAGE_BYTES];

  const uint8_t castStart[] = {0x01, 0x00};
  TEST_ASSERT_EQUAL(2, protocol::encodeCastStart(out, protocol::SOURCE_CAST_BUTTON));
  TEST_ASSERT_EQUAL_HEX8_ARRAY(castStart, out, 2);

  protocol::MotionSample s = {7, 123456, 0.12f, -9.81f, 1.00f, 0.5f, -1.25f, 3.0f};
  const uint8_t motion[] = {0x02, 0x07, 0x00, 0x40, 0xe2, 0x01, 0x00, 0x0c, 0x00, 0x2b,
                            0xfc, 0x64, 0x00, 0xf4, 0x01, 0x1e, 0xfb, 0xb8, 0x0b};
  TEST_ASSERT_EQUAL(19, protocol::encodeMotionSample(out, s));
  TEST_ASSERT_EQUAL_HEX8_ARRAY(motion, out, 19);

  const uint8_t castEnd[] = {0x03, 0x96, 0x00, 0x01};
  TEST_ASSERT_EQUAL(4, protocol::encodeCastEnd(out, 150, protocol::END_MAX_DURATION));
  TEST_ASSERT_EQUAL_HEX8_ARRAY(castEnd, out, 4);

  const uint8_t actionComplete[] = {0x04, 0x02, 0x01};
  TEST_ASSERT_EQUAL(3, protocol::encodeActionComplete(out, 2, true));
  TEST_ASSERT_EQUAL_HEX8_ARRAY(actionComplete, out, 3);
}

static void test_documented_command_bytes_decode() {
  protocol::Command c;

  const uint8_t start[] = {0x81};
  TEST_ASSERT_TRUE(protocol::decodeCommand(start, 1, c));
  TEST_ASSERT_EQUAL_HEX8(protocol::START_RECORDING, c.type);

  const uint8_t stop[] = {0x82};
  TEST_ASSERT_TRUE(protocol::decodeCommand(stop, 1, c));
  TEST_ASSERT_EQUAL_HEX8(protocol::STOP_RECORDING, c.type);

  const uint8_t result[] = {0x83, 0x00, 0x50, 0xff, 0x43, 0x49, 0x52, 0x43, 0x4c, 0x45};
  TEST_ASSERT_TRUE(protocol::decodeCommand(result, sizeof(result), c));
  TEST_ASSERT_EQUAL_HEX8(protocol::GESTURE_RESULT, c.type);
  TEST_ASSERT_EQUAL_STRING("CIRCLE", c.label);
  TEST_ASSERT_EQUAL(0, c.color.r);
  TEST_ASSERT_EQUAL(80, c.color.g);
  TEST_ASSERT_EQUAL(255, c.color.b);

  const uint8_t action[] = {0x84, 0x01};
  TEST_ASSERT_TRUE(protocol::decodeCommand(action, 2, c));
  TEST_ASSERT_EQUAL_HEX8(protocol::EXECUTE_ACTION, c.type);
  TEST_ASSERT_EQUAL(1, c.action);
}

static void test_out_of_range_readings_are_clamped() {
  uint8_t out[protocol::MAX_MESSAGE_BYTES];
  protocol::MotionSample s = {0, 0, 1000.0f, -1000.0f, 0, 50.0f, -50.0f, 0};
  protocol::encodeMotionSample(out, s);
  // ax = 32767 (ff 7f), ay = -32768 (00 80), gx = 32767, gy = -32768
  const uint8_t expected[] = {0xff, 0x7f, 0x00, 0x80, 0x00, 0x00, 0xff, 0x7f, 0x00, 0x80};
  TEST_ASSERT_EQUAL_HEX8_ARRAY(expected, out + 7, 10);
}

static void test_malformed_commands_are_rejected() {
  protocol::Command c;
  const uint8_t shortResult[] = {0x83, 0x00, 0x50};
  const uint8_t badAction[] = {0x84};
  const uint8_t unknownType[] = {0x01, 0x00};
  uint8_t longResult[21] = {0x83, 1, 2, 3};
  memset(longResult + 4, 'A', 17);  // 17-character label: one too many

  TEST_ASSERT_FALSE(protocol::decodeCommand(nullptr, 0, c));
  TEST_ASSERT_FALSE(protocol::decodeCommand(shortResult, sizeof(shortResult), c));
  TEST_ASSERT_FALSE(protocol::decodeCommand(longResult, sizeof(longResult), c));
  TEST_ASSERT_FALSE(protocol::decodeCommand(badAction, sizeof(badAction), c));
  TEST_ASSERT_FALSE(protocol::decodeCommand(unknownType, sizeof(unknownType), c));
}

// ---------- CAST_BUTTON debouncing ----------

static void test_bounces_shorter_than_settle_time_are_ignored() {
  Debouncer button(30);
  TEST_ASSERT_FALSE(button.update(true, 0));
  TEST_ASSERT_FALSE(button.update(false, 5));
  TEST_ASSERT_FALSE(button.update(true, 10));
  TEST_ASSERT_FALSE(button.update(false, 20));
  TEST_ASSERT_FALSE(button.update(false, 100));
  TEST_ASSERT_FALSE(button.pressed());
}

static void test_press_and_release_each_reported_once_after_settling() {
  Debouncer button(30);
  TEST_ASSERT_FALSE(button.update(true, 0));
  TEST_ASSERT_FALSE(button.update(true, 29));
  TEST_ASSERT_TRUE(button.update(true, 30));
  TEST_ASSERT_TRUE(button.pressed());
  TEST_ASSERT_FALSE(button.update(true, 31));  // reported only once

  TEST_ASSERT_FALSE(button.update(false, 500));
  TEST_ASSERT_TRUE(button.update(false, 530));
  TEST_ASSERT_FALSE(button.pressed());
}

// ---------- state machine ----------

struct RecordedEvents : WandEvents {
  int starts = 0, ends = 0;
  uint8_t source = 255, reason = 255;
  uint16_t count = 0;
  void castStart(uint8_t s) override { starts++; source = s; }
  void castEnd(uint16_t c, uint8_t r) override { ends++; count = c; reason = r; }
};

static void assertColor(Rgb expected, Rgb actual) {
  TEST_ASSERT_EQUAL_UINT8(expected.r, actual.r);
  TEST_ASSERT_EQUAL_UINT8(expected.g, actual.g);
  TEST_ASSERT_EQUAL_UINT8(expected.b, actual.b);
}

static const Rgb OFF = {0, 0, 0};

static void test_starts_idle_with_dim_white_led() {
  RecordedEvents events;
  WandStateMachine wand(events);
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());
  TEST_ASSERT_FALSE(wand.streaming());
  assertColor(colors::IDLE, wand.ledColor(0));
}

static void test_holding_the_button_casts_and_numbers_samples() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 1000);
  TEST_ASSERT_EQUAL(WandState::CASTING, wand.state());
  TEST_ASSERT_TRUE(wand.streaming());
  TEST_ASSERT_EQUAL(1, events.starts);
  TEST_ASSERT_EQUAL(protocol::SOURCE_CAST_BUTTON, events.source);
  assertColor(colors::CASTING, wand.ledColor(1000));
  TEST_ASSERT_EQUAL(0, wand.nextSampleIndex());
  TEST_ASSERT_EQUAL(1, wand.nextSampleIndex());
  TEST_ASSERT_EQUAL(2, wand.nextSampleIndex());
}

static void test_release_ends_cast_and_waits_for_result_in_amber() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 1000);
  for (int i = 0; i < 5; i++) wand.nextSampleIndex();
  wand.buttonChanged(false, 1500);
  TEST_ASSERT_EQUAL(WandState::INFLIGHT, wand.state());
  TEST_ASSERT_FALSE(wand.streaming());
  TEST_ASSERT_EQUAL(1, events.ends);
  TEST_ASSERT_EQUAL(5, events.count);
  TEST_ASSERT_EQUAL(protocol::END_NORMAL, events.reason);
  assertColor(colors::INFLIGHT, wand.ledColor(1500));
}

static void test_next_cast_numbers_samples_from_zero_again() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 0);
  wand.nextSampleIndex();
  wand.buttonChanged(false, 500);
  wand.gestureResult("CIRCLE", Rgb{1, 2, 3}, 600);
  wand.tick(600 + WandStateMachine::SPELL_SHOW_MS);
  wand.buttonChanged(true, 3000);
  TEST_ASSERT_EQUAL(0, wand.nextSampleIndex());
}

static void test_result_shows_spell_color_then_returns_to_idle() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 0);
  wand.buttonChanged(false, 800);
  Rgb purple = {120, 0, 200};
  wand.gestureResult("CIRCLE", purple, 900);
  assertColor(purple, wand.ledColor(900));
  wand.tick(900 + WandStateMachine::SPELL_SHOW_MS - 1);
  TEST_ASSERT_EQUAL(WandState::INFLIGHT, wand.state());
  assertColor(purple, wand.ledColor(900 + WandStateMachine::SPELL_SHOW_MS - 1));
  wand.tick(900 + WandStateMachine::SPELL_SHOW_MS);
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());
  assertColor(colors::IDLE, wand.ledColor(900 + WandStateMachine::SPELL_SHOW_MS));
}

// Spell colours live only in the Mac's config.json: the wand has none of its own.
static void test_wand_shows_exactly_the_colour_the_mac_sends() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 0);
  wand.buttonChanged(false, 800);
  wand.gestureResult("ZIGZAG", OFF, 900);  // even black: no built-in fallback
  assertColor(OFF, wand.ledColor(900));
}

static void test_unknown_flashes_the_macs_colour_three_times_then_idle() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 0);
  wand.buttonChanged(false, 800);
  const Rgb cyan = {0, 255, 255};  // not red, so a built-in colour can't pass this test
  wand.gestureResult("UNKNOWN", cyan, 1000);
  const uint32_t f = WandStateMachine::FLASH_MS;
  assertColor(cyan, wand.ledColor(1000));          // flash 1 on
  assertColor(OFF, wand.ledColor(1000 + f));       // off
  assertColor(cyan, wand.ledColor(1000 + 2 * f));  // flash 2 on
  assertColor(cyan, wand.ledColor(1000 + 4 * f));  // flash 3 on
  assertColor(OFF, wand.ledColor(1000 + 5 * f));
  wand.tick(1000 + 6 * f - 1);
  TEST_ASSERT_EQUAL(WandState::INFLIGHT, wand.state());
  wand.tick(1000 + 6 * f);
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());
}

static void test_no_answer_flashes_magenta_then_idle() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 0);
  wand.buttonChanged(false, 500);
  wand.tick(500 + WandStateMachine::RESULT_TIMEOUT_MS - 1);
  assertColor(colors::INFLIGHT, wand.ledColor(500 + WandStateMachine::RESULT_TIMEOUT_MS - 1));
  const uint32_t timeout = 500 + WandStateMachine::RESULT_TIMEOUT_MS;
  wand.tick(timeout);
  assertColor(colors::NO_ANSWER, wand.ledColor(timeout));
  wand.tick(timeout + 4 * WandStateMachine::FLASH_MS);
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());
}

static void test_cast_stops_at_maximum_duration_and_late_release_is_ignored() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 0);
  wand.tick(WandStateMachine::MAX_CAST_MS - 1);
  TEST_ASSERT_EQUAL(WandState::CASTING, wand.state());
  wand.tick(WandStateMachine::MAX_CAST_MS);
  TEST_ASSERT_EQUAL(WandState::INFLIGHT, wand.state());
  TEST_ASSERT_EQUAL(protocol::END_MAX_DURATION, events.reason);
  wand.buttonChanged(false, WandStateMachine::MAX_CAST_MS + 500);
  TEST_ASSERT_EQUAL(1, events.ends);
  TEST_ASSERT_EQUAL(WandState::INFLIGHT, wand.state());
}

static void test_button_is_ignored_while_inflight() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.buttonChanged(true, 0);
  wand.buttonChanged(false, 500);
  wand.buttonChanged(true, 600);
  TEST_ASSERT_EQUAL(WandState::INFLIGHT, wand.state());
  TEST_ASSERT_EQUAL(1, events.starts);
}

static void test_mac_controls_training_recordings() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.startRecording(0);
  TEST_ASSERT_EQUAL(WandState::CASTING, wand.state());
  TEST_ASSERT_EQUAL(protocol::SOURCE_RECORDING, events.source);
  wand.nextSampleIndex();
  wand.nextSampleIndex();
  wand.buttonChanged(true, 100);   // the button does nothing during training
  wand.buttonChanged(false, 200);
  TEST_ASSERT_EQUAL(WandState::CASTING, wand.state());
  wand.stopRecording(1500);
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());  // nothing to classify
  TEST_ASSERT_EQUAL(2, events.count);
  TEST_ASSERT_EQUAL(protocol::END_NORMAL, events.reason);
}

static void test_recording_stops_itself_at_maximum_duration() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.startRecording(0);
  wand.tick(WandStateMachine::MAX_RECORDING_MS);
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());
  TEST_ASSERT_EQUAL(protocol::END_MAX_DURATION, events.reason);
}

static void test_commands_that_do_not_fit_the_state_are_ignored() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.stopRecording(0);                        // not recording
  wand.gestureResult("CIRCLE", OFF, 0);         // not waiting for a result
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());
  assertColor(colors::IDLE, wand.ledColor(0));
  wand.buttonChanged(true, 10);
  wand.startRecording(20);                      // busy casting
  TEST_ASSERT_EQUAL(protocol::SOURCE_CAST_BUTTON, events.source);
  TEST_ASSERT_EQUAL(1, events.starts);
  TEST_ASSERT_EQUAL(0, events.ends);
}

static void test_connection_loss_ends_a_recording() {
  RecordedEvents events;
  WandStateMachine wand(events);
  wand.startRecording(0);
  wand.connectionLost(300);
  TEST_ASSERT_EQUAL(WandState::IDLE, wand.state());
  TEST_ASSERT_EQUAL(protocol::END_CONNECTION_LOST, events.reason);
}

// ---------- pairing accelerometer and gyroscope reports ----------

static void test_gyro_report_before_any_accelerometer_report_gives_no_reading() {
  ImuPairing pairing;
  ImuReading reading;
  TEST_ASSERT_FALSE(pairing.gyro(0.1f, 0.2f, 0.3f, reading));
}

static void test_gyro_report_is_paired_with_the_accelerometer_report() {
  ImuPairing pairing;
  ImuReading reading;
  pairing.accel(1.0f, 2.0f, 9.8f);
  TEST_ASSERT_TRUE(pairing.gyro(0.1f, 0.2f, 0.3f, reading));
  TEST_ASSERT_EQUAL_FLOAT(1.0f, reading.accel[0]);
  TEST_ASSERT_EQUAL_FLOAT(2.0f, reading.accel[1]);
  TEST_ASSERT_EQUAL_FLOAT(9.8f, reading.accel[2]);
  TEST_ASSERT_EQUAL_FLOAT(0.1f, reading.gyro[0]);
  TEST_ASSERT_EQUAL_FLOAT(0.2f, reading.gyro[1]);
  TEST_ASSERT_EQUAL_FLOAT(0.3f, reading.gyro[2]);
}

static void test_the_newest_accelerometer_report_is_used() {
  ImuPairing pairing;
  ImuReading reading;
  pairing.accel(1.0f, 0.0f, 0.0f);
  pairing.accel(5.0f, 0.0f, 0.0f);
  pairing.gyro(0.0f, 0.0f, 0.0f, reading);
  TEST_ASSERT_EQUAL_FLOAT(5.0f, reading.accel[0]);
}

static void test_every_gyro_report_gives_a_reading_even_without_a_new_accelerometer_report() {
  ImuPairing pairing;
  ImuReading reading;
  pairing.accel(1.0f, 0.0f, 0.0f);
  TEST_ASSERT_TRUE(pairing.gyro(0.1f, 0.0f, 0.0f, reading));
  TEST_ASSERT_TRUE(pairing.gyro(0.2f, 0.0f, 0.0f, reading));
  TEST_ASSERT_EQUAL_FLOAT(0.2f, reading.gyro[0]);
  TEST_ASSERT_EQUAL_FLOAT(1.0f, reading.accel[0]);
}

// ---------- turning readings from the IMU's axes into the wand's axes ----------
// Wand axes: x along the wand toward the tip, y to the left, z up (wand held level).
// On this wand the IMU's z axis points to the tip and its y axis is up.

static void test_gravity_reads_along_the_wands_x_axis_when_the_tip_points_straight_up() {
  ImuReading imu = {{0.0f, 0.0f, 9.8f}, {0.0f, 0.0f, 0.0f}};  // tip up: the IMU's z axis is up
  ImuReading wand = toWandAxes(imu);
  TEST_ASSERT_EQUAL_FLOAT(9.8f, wand.accel[0]);
  TEST_ASSERT_EQUAL_FLOAT(0.0f, wand.accel[1]);
  TEST_ASSERT_EQUAL_FLOAT(0.0f, wand.accel[2]);
}

static void test_gravity_reads_along_the_wands_z_axis_when_the_wand_is_held_level() {
  ImuReading imu = {{0.0f, 9.8f, 0.0f}, {0.0f, 0.0f, 0.0f}};  // level: the IMU's y axis is up
  ImuReading wand = toWandAxes(imu);
  TEST_ASSERT_EQUAL_FLOAT(0.0f, wand.accel[0]);
  TEST_ASSERT_EQUAL_FLOAT(0.0f, wand.accel[1]);
  TEST_ASSERT_EQUAL_FLOAT(9.8f, wand.accel[2]);
}

static void test_rotation_is_turned_into_the_wands_axes_the_same_way_as_acceleration() {
  ImuReading imu = {{1.0f, 2.0f, 3.0f}, {0.1f, 0.2f, 0.3f}};
  ImuReading wand = toWandAxes(imu);
  // wand x = IMU z, wand y = IMU x, wand z = IMU y
  TEST_ASSERT_EQUAL_FLOAT(3.0f, wand.accel[0]);
  TEST_ASSERT_EQUAL_FLOAT(1.0f, wand.accel[1]);
  TEST_ASSERT_EQUAL_FLOAT(2.0f, wand.accel[2]);
  TEST_ASSERT_EQUAL_FLOAT(0.3f, wand.gyro[0]);  // twisting the wand about its own length
  TEST_ASSERT_EQUAL_FLOAT(0.1f, wand.gyro[1]);
  TEST_ASSERT_EQUAL_FLOAT(0.2f, wand.gyro[2]);
}

// ---------- STATUS_LED as a 4-leg RGB LED (PWM on three pins) ----------

static void test_common_cathode_led_is_driven_by_brightness_directly() {
  // Common cathode: long leg to GND, so a higher PWM duty means brighter.
  TEST_ASSERT_EQUAL_UINT8(255, rgb_led::duty(255, 255, false));
  TEST_ASSERT_EQUAL_UINT8(64, rgb_led::duty(255, 64, false));   // full colour at quarter brightness
  TEST_ASSERT_EQUAL_UINT8(32, rgb_led::duty(128, 64, false));
  TEST_ASSERT_EQUAL_UINT8(0, rgb_led::duty(0, 255, false));
}

static void test_common_anode_led_is_driven_inverted() {
  // Common anode: long leg to 3.3 V, so the pin must go LOW to light the colour.
  TEST_ASSERT_EQUAL_UINT8(0, rgb_led::duty(255, 255, true));    // fully on
  TEST_ASSERT_EQUAL_UINT8(191, rgb_led::duty(255, 64, true));
  TEST_ASSERT_EQUAL_UINT8(255, rgb_led::duty(0, 255, true));    // off
}

// ---------- send queue (messages waiting for Bluetooth) ----------

// A small queue for the tests: room for 4 messages, 1 of them kept for important ones.
typedef SendQueue<4, 1> SmallQueue;

static void pushByte(SmallQueue& queue, uint8_t value, bool important = false) {
  uint8_t message[2] = {value, value};
  queue.push(message, sizeof(message), important);
}

static uint8_t frontByte(const SmallQueue& queue) {
  const uint8_t* data = nullptr;
  size_t length = 0;
  TEST_ASSERT_TRUE(queue.front(data, length));
  TEST_ASSERT_EQUAL(2, length);
  return data[0];
}

static void test_queued_messages_come_out_in_the_order_they_went_in() {
  SmallQueue queue;
  pushByte(queue, 1);
  pushByte(queue, 2);
  TEST_ASSERT_EQUAL_UINT8(1, frontByte(queue));
  queue.pop();
  TEST_ASSERT_EQUAL_UINT8(2, frontByte(queue));
  queue.pop();
  const uint8_t* data;
  size_t length;
  TEST_ASSERT_FALSE(queue.front(data, length));
}

static void test_a_message_the_radio_refused_stays_at_the_front_to_try_again() {
  SmallQueue queue;
  pushByte(queue, 1);
  pushByte(queue, 2);
  frontByte(queue);  // the send failed, so nothing is popped
  TEST_ASSERT_EQUAL_UINT8(1, frontByte(queue));
  TEST_ASSERT_EQUAL(2, queue.size());
}

static void test_readings_are_dropped_and_counted_once_only_the_reserved_room_is_left() {
  SmallQueue queue;
  for (uint8_t i = 1; i <= 4; i++) pushByte(queue, i);
  TEST_ASSERT_EQUAL(3, queue.size());
  TEST_ASSERT_EQUAL_UINT32(1, queue.dropped());
}

static void test_important_messages_still_fit_when_readings_have_filled_their_share() {
  SmallQueue queue;
  for (uint8_t i = 1; i <= 3; i++) pushByte(queue, i);
  uint8_t castEnd[2] = {9, 9};
  TEST_ASSERT_TRUE(queue.push(castEnd, sizeof(castEnd), true));
  TEST_ASSERT_EQUAL(4, queue.size());
  TEST_ASSERT_FALSE(queue.push(castEnd, sizeof(castEnd), true));  // now completely full
  TEST_ASSERT_EQUAL_UINT32(1, queue.dropped());
}

static void test_the_queue_keeps_working_after_wrapping_around() {
  SmallQueue queue;
  for (uint8_t i = 1; i <= 10; i++) {
    pushByte(queue, i);
    pushByte(queue, i + 100);
    TEST_ASSERT_EQUAL_UINT8(i, frontByte(queue));
    queue.pop();
    TEST_ASSERT_EQUAL_UINT8(i + 100, frontByte(queue));
    queue.pop();
  }
  TEST_ASSERT_EQUAL(0, queue.size());
  TEST_ASSERT_EQUAL_UINT32(0, queue.dropped());
}

static void test_clearing_the_queue_forgets_waiting_messages() {
  SmallQueue queue;
  pushByte(queue, 1);
  pushByte(queue, 2);
  queue.clear();
  TEST_ASSERT_EQUAL(0, queue.size());
  pushByte(queue, 3);
  TEST_ASSERT_EQUAL_UINT8(3, frontByte(queue));
}

static void test_a_message_longer_than_a_slot_is_refused() {
  SmallQueue queue;
  uint8_t tooLong[protocol::MAX_MESSAGE_BYTES + 1] = {0};
  TEST_ASSERT_FALSE(queue.push(tooLong, sizeof(tooLong), true));
  TEST_ASSERT_EQUAL(0, queue.size());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_queued_messages_come_out_in_the_order_they_went_in);
  RUN_TEST(test_a_message_the_radio_refused_stays_at_the_front_to_try_again);
  RUN_TEST(test_readings_are_dropped_and_counted_once_only_the_reserved_room_is_left);
  RUN_TEST(test_important_messages_still_fit_when_readings_have_filled_their_share);
  RUN_TEST(test_the_queue_keeps_working_after_wrapping_around);
  RUN_TEST(test_clearing_the_queue_forgets_waiting_messages);
  RUN_TEST(test_a_message_longer_than_a_slot_is_refused);
  RUN_TEST(test_events_encode_to_the_documented_bytes);
  RUN_TEST(test_documented_command_bytes_decode);
  RUN_TEST(test_out_of_range_readings_are_clamped);
  RUN_TEST(test_malformed_commands_are_rejected);
  RUN_TEST(test_bounces_shorter_than_settle_time_are_ignored);
  RUN_TEST(test_press_and_release_each_reported_once_after_settling);
  RUN_TEST(test_starts_idle_with_dim_white_led);
  RUN_TEST(test_holding_the_button_casts_and_numbers_samples);
  RUN_TEST(test_release_ends_cast_and_waits_for_result_in_amber);
  RUN_TEST(test_next_cast_numbers_samples_from_zero_again);
  RUN_TEST(test_result_shows_spell_color_then_returns_to_idle);
  RUN_TEST(test_wand_shows_exactly_the_colour_the_mac_sends);
  RUN_TEST(test_unknown_flashes_the_macs_colour_three_times_then_idle);
  RUN_TEST(test_no_answer_flashes_magenta_then_idle);
  RUN_TEST(test_cast_stops_at_maximum_duration_and_late_release_is_ignored);
  RUN_TEST(test_button_is_ignored_while_inflight);
  RUN_TEST(test_mac_controls_training_recordings);
  RUN_TEST(test_recording_stops_itself_at_maximum_duration);
  RUN_TEST(test_commands_that_do_not_fit_the_state_are_ignored);
  RUN_TEST(test_connection_loss_ends_a_recording);
  RUN_TEST(test_common_cathode_led_is_driven_by_brightness_directly);
  RUN_TEST(test_common_anode_led_is_driven_inverted);
  RUN_TEST(test_gyro_report_before_any_accelerometer_report_gives_no_reading);
  RUN_TEST(test_gyro_report_is_paired_with_the_accelerometer_report);
  RUN_TEST(test_the_newest_accelerometer_report_is_used);
  RUN_TEST(test_every_gyro_report_gives_a_reading_even_without_a_new_accelerometer_report);
  RUN_TEST(test_gravity_reads_along_the_wands_x_axis_when_the_tip_points_straight_up);
  RUN_TEST(test_gravity_reads_along_the_wands_z_axis_when_the_wand_is_held_level);
  RUN_TEST(test_rotation_is_turned_into_the_wands_axes_the_same_way_as_acceleration);
  return UNITY_END();
}
