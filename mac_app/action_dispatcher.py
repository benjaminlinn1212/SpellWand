"""Action Dispatcher: runs the action mapped to a recognized gesture (see config.py).

Never runs anything for UNKNOWN. Action types:
  none      do nothing
  notify    show a macOS notification
  webhook   POST {"gesture": ..., "source": "SpellWand"} to a URL, e.g. a Home Assistant webhook
"""

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

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
    def __init__(self, notifier=show_mac_notification, http_timeout_s=3.0):
        self._notify = notifier
        self._http_timeout_s = http_timeout_s

    def dispatch(self, label, action):
        """Run the action for `label`. Returns an ActionOutcome, or None if nothing ran."""
        kind = action.get("type", "none")
        if label == UNKNOWN or kind == "none":
            return None
        try:
            if kind == "notify":
                ok = self._notify(action["message"])
                detail = "notification shown" if ok else "osascript failed"
            elif kind == "webhook":
                ok, detail = self._webhook(action["url"], label)
            else:
                ok, detail = False, f"unknown action type {kind!r}"
        except Exception as error:  # an action must never take the app down
            ok, detail = False, str(error)
        return ActionOutcome(label, kind, ok, detail)

    def _webhook(self, url, label):
        body = json.dumps({"gesture": label, "source": "SpellWand"}).encode()
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._http_timeout_s) as response:
                return 200 <= response.status < 300, f"HTTP {response.status}"
        except (urllib.error.URLError, OSError) as error:
            return False, f"webhook failed: {error}"
