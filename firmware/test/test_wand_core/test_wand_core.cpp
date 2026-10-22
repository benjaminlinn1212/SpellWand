// Tests for the hardware-independent wand logic in lib/wand_core.
// They run on the Mac, no ESP32 needed:
//
//     ~/.platformio/penv/bin/pio test -e native

#include <string.h>
#include <unity.h>

#include "action_output.h"
#include "debouncer.h"
#include "gyro_bias.h"
#include "imu_units.h"
#include "rgb_led.h"
#include "protocol.h"
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

// ---------- action LED (EXECUTE_ACTION) ----------

static void test_toggle_switches_the_action_led() {
  ActionOutput output;
  TEST_ASSERT_FALSE(output.level(0));
  TEST_ASSERT_TRUE(output.execute(protocol::ACTION_TOGGLE_LED, 0));
  TEST_ASSERT_TRUE(output.level(1));
  TEST_ASSERT_TRUE(output.execute(protocol::ACTION_TOGGLE_LED, 2));
  TEST_ASSERT_FALSE(output.level(3));
}

static void test_pulse_lights_the_action_led_briefly() {
  ActionOutput output;
  TEST_ASSERT_TRUE(output.execute(protocol::ACTION_PULSE_LED, 1000));
  TEST_ASSERT_TRUE(output.level(1000));
  TEST_ASSERT_TRUE(output.level(1000 + ActionOutput::PULSE_MS - 1));
  TEST_ASSERT_FALSE(output.level(1000 + ActionOutput::PULSE_MS));
}

static void test_unknown_action_is_refused() {
  ActionOutput output;
  TEST_ASSERT_FALSE(output.execute(99, 0));
  TEST_ASSERT_FALSE(output.level(0));
}

// ---------- MPU-9250 / MPU-6500 raw data ----------

static void test_register_bytes_combine_high_byte_first() {
  TEST_ASSERT_EQUAL_INT16(4096, imu_units::fromBigEndian(0x10, 0x00));
  TEST_ASSERT_EQUAL_INT16(-200, imu_units::fromBigEndian(0xFF, 0x38));
  TEST_ASSERT_EQUAL_INT16(-32768, imu_units::fromBigEndian(0x80, 0x00));
}

static void test_raw_readings_convert_to_si_units() {
  // +-8 g range: 4096 counts per g. +-2000 deg/s range: 16.4 counts per deg/s.
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, 9.80665f, imu_units::accelToMs2(4096));
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, -19.6133f, imu_units::accelToMs2(-8192));
  TEST_ASSERT_FLOAT_WITHIN(1e-5f, 0.174533f, imu_units::gyroToRadS(164));     // 10 deg/s
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, -1.745329f, imu_units::gyroToRadS(-1640));  // -100 deg/s
}

// ---------- learning the gyro offset while the wand is still ----------

static const float LEVEL[3] = {0.0f, 0.0f, 9.81f};

// Feeds `n` readings: a constant gyro value plus a tiny +-0.002 rad/s wobble.
static bool feedStill(GyroBias& bias, float gx, float gy, float gz, int n) {
  bool learnt = false;
  for (int i = 0; i < n; i++) {
    float wobble = (i % 2 == 0) ? 0.002f : -0.002f;
    float gyro[3] = {gx + wobble, gy - wobble, gz + wobble};
    learnt = bias.update(gyro, LEVEL) || learnt;
  }
  return learnt;
}

static void test_holding_still_reveals_the_gyro_offset() {
  GyroBias bias;
  TEST_ASSERT_FALSE(bias.ready());
  TEST_ASSERT_TRUE(feedStill(bias, 0.03f, -0.02f, 0.05f, GyroBias::WINDOW));
  TEST_ASSERT_TRUE(bias.ready());
  float gyro[3] = {1.03f, -0.02f, 0.05f};
  bias.correct(gyro);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 1.0f, gyro[0]);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, gyro[1]);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, gyro[2]);
}

static void test_a_moving_wand_teaches_nothing() {
  GyroBias bias;
  for (int i = 0; i < 3 * GyroBias::WINDOW; i++) {
    // Waving evenly back and forth at 1 rad/s: it averages to exactly zero, so only the
    // "did the gyro stay steady?" check can tell this is not stillness.
    float swing = (i % 10 < 5) ? 1.0f : -1.0f;
    float gyro[3] = {swing, 0.0f, 0.0f};
    TEST_ASSERT_FALSE(bias.update(gyro, LEVEL));
  }
  TEST_ASSERT_FALSE(bias.ready());
}

static void test_a_slow_steady_turn_is_not_mistaken_for_an_offset() {
  // Turning steadily about the vertical axis at 0.3 rad/s: the gyro reading is constant
  // and gravity doesn't change, but 17 deg/s is far more than any real offset.
  GyroBias bias;
  TEST_ASSERT_FALSE(feedStill(bias, 0.0f, 0.0f, 0.3f, 2 * GyroBias::WINDOW));
  TEST_ASSERT_FALSE(bias.ready());
}

static void test_tilting_slowly_is_not_mistaken_for_an_offset() {
  // A steady small gyro reading, but the accelerometer shows the wand tipping over.
  GyroBias bias;
  for (int i = 0; i < GyroBias::WINDOW; i++) {
    float gyro[3] = {0.05f, 0.0f, 0.0f};
    float accel[3] = {0.0f, 0.06f * i, 9.81f};
    TEST_ASSERT_FALSE(bias.update(gyro, accel));
  }
  TEST_ASSERT_FALSE(bias.ready());
}

static void test_restart_drops_a_half_measured_window() {
  GyroBias bias;
  feedStill(bias, 0.10f, 0.0f, 0.0f, GyroBias::WINDOW / 2);
  bias.restart();  // e.g. a cast began
  TEST_ASSERT_TRUE(feedStill(bias, 0.02f, 0.0f, 0.0f, GyroBias::WINDOW));
  float gyro[3] = {0.02f, 0.0f, 0.0f};
  bias.correct(gyro);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, gyro[0]);
}

static void test_later_still_moments_follow_a_drifting_offset() {
  // The offset changes as the chip warms up; each still period re-measures it.
  GyroBias bias;
  feedStill(bias, 0.02f, 0.0f, 0.0f, GyroBias::WINDOW);
  feedStill(bias, 0.04f, 0.0f, 0.0f, GyroBias::WINDOW);
  float gyro[3] = {0.04f, 0.0f, 0.0f};
  bias.correct(gyro);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, gyro[0]);
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

int main() {
  UNITY_BEGIN();
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
  RUN_TEST(test_toggle_switches_the_action_led);
  RUN_TEST(test_pulse_lights_the_action_led_briefly);
  RUN_TEST(test_unknown_action_is_refused);
  RUN_TEST(test_register_bytes_combine_high_byte_first);
  RUN_TEST(test_raw_readings_convert_to_si_units);
  RUN_TEST(test_holding_still_reveals_the_gyro_offset);
  RUN_TEST(test_a_moving_wand_teaches_nothing);
  RUN_TEST(test_a_slow_steady_turn_is_not_mistaken_for_an_offset);
  RUN_TEST(test_tilting_slowly_is_not_mistaken_for_an_offset);
  RUN_TEST(test_restart_drops_a_half_measured_window);
  RUN_TEST(test_later_still_moments_follow_a_drifting_offset);
  RUN_TEST(test_common_cathode_led_is_driven_by_brightness_directly);
  RUN_TEST(test_common_anode_led_is_driven_inverted);
  return UNITY_END();
}
