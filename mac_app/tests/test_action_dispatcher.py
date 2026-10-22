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


class Notifications:
    """Stands in for macOS notifications so tests don't pop anything up."""

    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)
        return True


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
    def setUp(self):
        self.notifications = Notifications()
        self.dispatcher = ActionDispatcher(notifier=self.notifications)

    def test_unknown_never_runs_an_action(self):
        outcome = self.dispatcher.dispatch("UNKNOWN", {"type": "notify", "message": "should not appear"})
        self.assertIsNone(outcome)
        self.assertEqual(self.notifications.messages, [])

    def test_none_action_does_nothing(self):
        self.assertIsNone(self.dispatcher.dispatch("CIRCLE", {"type": "none"}))
        self.assertEqual(self.notifications.messages, [])

    def test_notify_shows_the_message(self):
        outcome = self.dispatcher.dispatch("ZIGZAG", {"type": "notify", "message": "Zigzag cast!"})
        self.assertTrue(outcome.ok)
        self.assertEqual(self.notifications.messages, ["Zigzag cast!"])

    def test_unknown_action_type_is_reported_not_crashed(self):
        outcome = self.dispatcher.dispatch("CIRCLE", {"type": "wand_led", "mode": "toggle"})
        self.assertFalse(outcome.ok)
        self.assertIn("unknown action type", outcome.detail)

    def test_webhook_posts_the_gesture(self):
        RecordingHandler.requests = []
        with socketserver.TCPServer(("127.0.0.1", 0), RecordingHandler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.server_address[1]
            outcome = self.dispatcher.dispatch("CIRCLE", {"type": "webhook", "url": f"http://127.0.0.1:{port}/hook"})
            server.shutdown()
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertEqual(RecordingHandler.requests, [("/hook", {"gesture": "CIRCLE", "source": "SpellWand"})])

    def test_unreachable_webhook_reports_failure_instead_of_crashing(self):
        with socket.socket() as s:  # find a port with nothing listening
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        outcome = self.dispatcher.dispatch("CIRCLE", {"type": "webhook", "url": f"http://127.0.0.1:{port}/hook"})
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
