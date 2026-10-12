"""Action Dispatcher: runs the action mapped to a recognized gesture (see config.py).

Never runs anything for UNKNOWN. Action types:
  none      do nothing
  wand_led  switch the low-voltage LED on the wand (EXECUTE_ACTION, waits for ACTION_COMPLETE)
  notify    show a macOS notification
  webhook   POST {"gesture": ..., "source": "SpellWand"} to a URL, e.g. a Home Assistant webhook
"""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from protocol import ACTION_PULSE_LED, ACTION_TOGGLE_LED, encode_execute_action

UNKNOWN = "UNKNOWN"


@dataclass
class ActionOutcome:
    label: str
    action_type: str
    ok: bool
    detail: str


def show_mac_notification(message, runner=subprocess.run):
    """Show a macOS notification. The message is passed to AppleScript as an argument,
    never pasted into the script, so quotes in it can't change what the script does."""
    script = ["on run argv", 'display notification (item 1 of argv) with title "SpellWand"', "end run"]
    args = ["osascript"]
    for line in script:
        args += ["-e", line]
    args.append(message)
    result = runner(args, check=False, capture_output=True, timeout=5)
    return result.returncode == 0


class ActionDispatcher:
    def __init__(self, send_to_wand, notifier=show_mac_notification, wand_timeout_s=2.0, http_timeout_s=3.0):
        self._send_to_wand = send_to_wand
        self._notify = notifier
        self._wand_timeout_s = wand_timeout_s
        self._http_timeout_s = http_timeout_s
        self._waiting = {}  # action code -> [threading.Event, ok]
        self._lock = threading.Lock()

    def dispatch(self, label, action):
        """Run the action for `label`. Returns an ActionOutcome, or None if nothing ran."""
        kind = action.get("type", "none")
        if label == UNKNOWN or kind == "none":
            return None
        try:
            if kind == "wand_led":
                ok, detail = self._wand_led(action["mode"])
            elif kind == "notify":
                ok = self._notify(action["message"])
                detail = "notification shown" if ok else "osascript failed"
            elif kind == "webhook":
                ok, detail = self._webhook(action["url"], label)
            else:
                ok, detail = False, f"unknown action type {kind!r}"
        except Exception as error:  # an action must never take the app down
            ok, detail = False, str(error)
        return ActionOutcome(label, kind, ok, detail)

    def action_complete(self, event):
        """Call with each ACTION_COMPLETE event received from the wand."""
        with self._lock:
            waiting = self._waiting.get(event.action)
        if waiting:
            waiting[1] = event.ok
            waiting[0].set()

    def _wand_led(self, mode):
        code = ACTION_TOGGLE_LED if mode == "toggle" else ACTION_PULSE_LED
        waiting = [threading.Event(), False]
        with self._lock:
            self._waiting[code] = waiting  # before sending: the reply may come back at once
        try:
            self._send_to_wand(encode_execute_action(code))
            if not waiting[0].wait(self._wand_timeout_s):
                return False, "the wand sent no ACTION_COMPLETE"
            return waiting[1], "wand LED switched" if waiting[1] else "the wand refused the action"
        finally:
            with self._lock:
                self._waiting.pop(code, None)

    def _webhook(self, url, label):
        body = json.dumps({"gesture": label, "source": "SpellWand"}).encode()
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._http_timeout_s) as response:
                return 200 <= response.status < 300, f"HTTP {response.status}"
        except (urllib.error.URLError, OSError) as error:
            return False, f"webhook failed: {error}"
