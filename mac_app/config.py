"""Settings kept in config.json and edited from the SpellWand UI.

These stay on the Mac. The wand only ever receives a GestureLabel and its colour
(in GESTURE_RESULT); the DTW threshold and the dataset are never sent to it.
"""

import copy
import json
import math
import os
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

ACTION_TYPES = {
    "none": "Do nothing",
    "wand_led": "Switch the LED on the wand (EXECUTE_ACTION)",
    "notify": "Show a Mac notification",
    "webhook": "Send a web request (e.g. a Home Assistant webhook)",
}
WAND_LED_MODES = ("toggle", "pulse")

DEFAULT_CONFIG = {
    "dtw_threshold": 1.0,
    "unknown_color": "#ff0000",
    "gestures": {
        "CIRCLE": {"color": "#0050ff", "action": {"type": "wand_led", "mode": "toggle"}},
        "ZIGZAG": {"color": "#ff4000", "action": {"type": "notify", "message": "Zigzag cast!"}},
        "HORIZONTAL_LINE": {"color": "#00c828", "action": {"type": "none"}},
    },
}

_LABEL = re.compile(r"[A-Z][A-Z0-9_]{0,15}")  # also fits in a GESTURE_RESULT message
_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


class ConfigError(ValueError):
    """A setting that is not allowed; the message says which and why."""


def load_config(path=CONFIG_PATH):
    """Read config.json, or return the defaults if it does not exist yet."""
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    return validate_config(json.loads(path.read_text()))


def save_config(config, path=CONFIG_PATH):
    """Check the settings, then write them. An invalid config is never written."""
    config = validate_config(config)
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n")
    os.replace(temporary, path)  # all-or-nothing, so a crash can't leave half a file
    return config


def validate_config(config):
    """Return a cleaned copy of `config`, or raise ConfigError."""
    if not isinstance(config, dict):
        raise ConfigError("settings must be a JSON object")

    threshold = config.get("dtw_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) \
            or not math.isfinite(threshold) or threshold <= 0:
        raise ConfigError("dtw_threshold must be a number greater than 0")

    gestures = config.get("gestures")
    if not isinstance(gestures, dict) or not gestures:
        raise ConfigError("there must be at least one gesture")

    clean = {
        "dtw_threshold": float(threshold),
        "unknown_color": _colour(config.get("unknown_color"), "unknown_color"),
        "gestures": {},
    }
    for label, settings in gestures.items():
        if not isinstance(label, str) or not _LABEL.fullmatch(label) or label == "UNKNOWN":
            raise ConfigError(f"gesture label {label!r} must be 1-16 uppercase letters, digits or _ "
                              "starting with a letter, and not UNKNOWN")
        if not isinstance(settings, dict):
            raise ConfigError(f"{label}: settings must be an object")
        clean["gestures"][label] = {
            "color": _colour(settings.get("color"), f"{label} colour"),
            "action": _action(settings.get("action"), label),
        }
    return clean


def _colour(value, name):
    if not isinstance(value, str) or not _COLOUR.fullmatch(value):
        raise ConfigError(f"{name} must look like #00aaff")
    return value.lower()


def _action(action, label):
    if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
        raise ConfigError(f"{label}: action type must be one of {', '.join(ACTION_TYPES)}")
    kind = action["type"]
    if kind == "wand_led":
        if action.get("mode") not in WAND_LED_MODES:
            raise ConfigError(f"{label}: wand LED mode must be toggle or pulse")
        return {"type": kind, "mode": action["mode"]}
    if kind == "notify":
        message = action.get("message")
        if not isinstance(message, str) or not 0 < len(message) <= 200:
            raise ConfigError(f"{label}: notification message must be 1-200 characters")
        return {"type": kind, "message": message}
    if kind == "webhook":
        url = action.get("url")
        if not isinstance(url, str) or not re.match(r"https?://[^\s]+$", url):
            raise ConfigError(f"{label}: webhook URL must start with http:// or https://")
        return {"type": kind, "url": url}
    return {"type": "none"}
