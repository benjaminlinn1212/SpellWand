"""The simulated home: a living room whose devices a gesture can switch (action type "home").

Its state lives here on the Mac, so the Home page, a reload and a second browser tab all
show the same room. It is kept in memory only: every device starts off or closed when
app.py starts.
"""

import threading

# device: (name, word when off, word when on), in the order they stand in the room, left to
# right, which is also the order the page lists them
HOME_DEVICES = {
    "door": ("Door", "closed", "open"),
    "curtains": ("Curtains", "closed", "open"),
    "tv": ("TV", "off", "on"),
    "lamp": ("Lamp", "off", "on"),
}


def describe(device, on):
    """For example "Lamp on" or "Door closed"."""
    name, off_word, on_word = HOME_DEVICES[device]
    return f"{name} {on_word if on else off_word}"


class Home:
    def __init__(self):
        self._lock = threading.Lock()
        self._on = {device: False for device in HOME_DEVICES}

    def state(self):
        with self._lock:
            return dict(self._on)

    def toggle(self, device):
        """Switch `device` and return whether it is now on (or open)."""
        if device not in HOME_DEVICES:
            raise ValueError(f"no home device called {device!r}")
        with self._lock:
            self._on[device] = not self._on[device]
            return self._on[device]
