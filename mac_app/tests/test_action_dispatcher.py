"""Tests for the Action Dispatcher. Run from mac_app/:

    .venv/bin/python -m unittest discover -s tests -v
"""

import json
import socket
import socketserver
import threading
import unittest
from http.server import BaseHTTPRequestHandler

from action_dispatcher import ActionDispatcher, show_mac_notification
from protocol import ActionComplete, decode_event
from simulator import SimulatedWand


class Notifications:
    """Stands in for macOS notifications so tests don't pop anything up."""

    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)
        return True


def wand_with_dispatcher(**kwargs):
    """A simulated wand wired to a dispatcher the way the controller wires them."""
    wand = SimulatedWand()
    notifications = Notifications()
    dispatcher = ActionDispatcher(send_to_wand=wand.send, notifier=notifications, **kwargs)

    def on_event(data):
        event = decode_event(data)
        if isinstance(event, ActionComplete):
            dispatcher.action_complete(event)

    wand.on_event = on_event
    wand.connect()
    return wand, dispatcher, notifications


class RecordingHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        RecordingHandler.requests.append((self.path, json.loads(body)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # keep test output quiet


class ActionDispatcherTest(unittest.TestCase):
    def test_unknown_never_runs_an_action(self):
        wand, dispatcher, notifications = wand_with_dispatcher()
        outcome = dispatcher.dispatch("UNKNOWN", {"type": "notify", "message": "should not appear"})
        self.assertIsNone(outcome)
        self.assertEqual(notifications.messages, [])

    def test_none_action_does_nothing(self):
        wand, dispatcher, notifications = wand_with_dispatcher()
        outcome = dispatcher.dispatch("CIRCLE", {"type": "none"})
        self.assertIsNone(outcome)
        self.assertFalse(wand.action_led_on)

    def test_notify_shows_the_message(self):
        wand, dispatcher, notifications = wand_with_dispatcher()
        outcome = dispatcher.dispatch("ZIGZAG", {"type": "notify", "message": "Zigzag cast!"})
        self.assertTrue(outcome.ok)
        self.assertEqual(notifications.messages, ["Zigzag cast!"])

    def test_wand_led_toggle_switches_the_wand_led_and_waits_for_completion(self):
        wand, dispatcher, notifications = wand_with_dispatcher()
        outcome = dispatcher.dispatch("CIRCLE", {"type": "wand_led", "mode": "toggle"})
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertTrue(wand.action_led_on)
        dispatcher.dispatch("CIRCLE", {"type": "wand_led", "mode": "toggle"})
        self.assertFalse(wand.action_led_on)

    def test_wand_led_pulse_sends_the_pulse_action(self):
        sent = []
        dispatcher = ActionDispatcher(send_to_wand=sent.append, notifier=Notifications(), wand_timeout_s=0.05)
        dispatcher.dispatch("CIRCLE", {"type": "wand_led", "mode": "pulse"})
        self.assertEqual(sent, [bytes.fromhex("84 02")])

    def test_wand_led_without_a_reply_reports_failure(self):
        dispatcher = ActionDispatcher(send_to_wand=lambda data: None, notifier=Notifications(), wand_timeout_s=0.05)
        outcome = dispatcher.dispatch("CIRCLE", {"type": "wand_led", "mode": "toggle"})
        self.assertFalse(outcome.ok)
        self.assertIn("ACTION_COMPLETE", outcome.detail)

    def test_wand_led_when_not_connected_reports_failure(self):
        def not_connected(data):
            raise ConnectionError("wand not connected")

        dispatcher = ActionDispatcher(send_to_wand=not_connected, notifier=Notifications())
        outcome = dispatcher.dispatch("CIRCLE", {"type": "wand_led", "mode": "toggle"})
        self.assertFalse(outcome.ok)
        self.assertIn("not connected", outcome.detail)

    def test_webhook_posts_the_gesture(self):
        RecordingHandler.requests = []
        with socketserver.TCPServer(("127.0.0.1", 0), RecordingHandler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.server_address[1]
            dispatcher = ActionDispatcher(send_to_wand=lambda data: None, notifier=Notifications())
            outcome = dispatcher.dispatch("CIRCLE", {"type": "webhook", "url": f"http://127.0.0.1:{port}/hook"})
            server.shutdown()
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertEqual(RecordingHandler.requests, [("/hook", {"gesture": "CIRCLE", "source": "SpellWand"})])

    def test_unreachable_webhook_reports_failure_instead_of_crashing(self):
        with socket.socket() as s:  # find a port with nothing listening
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        dispatcher = ActionDispatcher(send_to_wand=lambda data: None, notifier=Notifications())
        outcome = dispatcher.dispatch("CIRCLE", {"type": "webhook", "url": f"http://127.0.0.1:{port}/hook"})
        self.assertFalse(outcome.ok)


class MacNotificationTest(unittest.TestCase):
    def test_message_is_passed_as_data_not_as_script(self):
        calls = []

        class Done:
            returncode = 0

        def runner(args, **kwargs):
            calls.append(args)
            return Done()

        message = 'He said "hi" & ran away'
        self.assertTrue(show_mac_notification(message, runner=runner))
        [args] = calls
        self.assertEqual(args[0], "osascript")
        self.assertEqual(args[-1], message)                       # handed over as an argument...
        self.assertNotIn(message, " ".join(args[:-1]))            # ...never pasted into the script


if __name__ == "__main__":
    unittest.main()
