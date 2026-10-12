"""SpellWand controller: the glue between the BLE Manager (or the simulated wand), the
Sample Recorder, the Gesture Classifier and the Action Dispatcher.

The SpellWand UI (app.py) calls its methods and listens to the events it publishes:
  status        connection, wand state, recording, dataset counts
  cast_start    a cast or training recording began
  motion        a batch of live MotionSamples
  result        a GestureResult, with the motion for display
  action        what the Action Dispatcher did
  sample_saved  a training recording was saved
  message       something the user should know (e.g. a recording was too short)
"""

import copy
import math
import queue
import threading
from collections import Counter, deque
from dataclasses import asdict

import numpy as np

from action_dispatcher import ActionDispatcher
from classifier import MIN_SAMPLES, GestureClassifier, leave_one_out
from config import CONFIG_PATH, load_config, save_config
from motion_trace import tip_trace
from protocol import (
    ActionComplete, CastEnd, CastStart, MotionSample, ProtocolError, END_MAX_DURATION, SOURCE_RECORDING,
    decode_event, encode_gesture_result, encode_start_recording, encode_stop_recording,
)
from recorder import DATA_DIR, delete_sample, list_samples, load_dataset, load_sample, save_sample, sequence_from_samples
from simulator import GESTURES, SimulatedWand

MOTION_BATCH = 5  # live motion goes to the UI in batches of this many samples


def run_in_thread(task):
    threading.Thread(target=task, daemon=True).start()


def hex_to_rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _finite(value):
    """JSON has no infinity; send None instead."""
    return None if value is None or math.isinf(value) else round(float(value), 4)


class SpellWandController:
    def __init__(self, data_dir=DATA_DIR, config_path=CONFIG_PATH, run_in_background=run_in_thread,
                 simulator_realtime=True, simulator_seed=None):
        self.data_dir = data_dir
        self.config_path = config_path
        self.config = load_config(config_path)
        self.classifier = GestureClassifier(self.config["dtw_threshold"])
        self.dispatcher = ActionDispatcher(send_to_wand=self._send)
        self._background = run_in_background
        self._simulator_realtime = simulator_realtime
        self._simulator_seed = simulator_seed
        self._lock = threading.RLock()
        self._subscribers = []
        self._link = None
        self._mode = None
        self._wand_state = "IDLE"
        self._cast_source = None
        self._cast_samples = []
        self._recording_label = None
        self._dataset_counts = {}
        self._history = deque(maxlen=20)
        self._retrain()

    # ---------- connection ----------

    def connect(self, mode):
        """mode "ble" for the real wand, "simulated" for the simulated wand."""
        if mode == "simulated":
            link = SimulatedWand(realtime=self._simulator_realtime, seed=self._simulator_seed)
        elif mode == "ble":
            from ble_manager import BleWandLink  # only needs Bluetooth when actually used
            link = BleWandLink()
        else:
            raise ValueError(f"unknown connection mode {mode!r}")
        self.disconnect()
        link.on_event = self._on_event
        link.on_disconnect = self._on_link_lost
        link.connect()  # raises ConnectionError if the wand can't be reached
        with self._lock:
            self._link, self._mode = link, mode
        self._publish_status()

    def disconnect(self):
        with self._lock:
            link, self._link, self._mode = self._link, None, None
            self._reset_cast()
        if link:
            link.on_disconnect = None
            link.disconnect()
        self._publish_status()

    @property
    def simulated_wand(self):
        link = self._link
        return link if isinstance(link, SimulatedWand) else None

    def simulate_cast(self, motion):
        """Simulation mode only: the simulated user casts `motion`."""
        wand = self.simulated_wand
        if wand is None:
            raise ConnectionError("connect the simulated wand first")
        if not wand.cast(motion):
            raise RuntimeError("the wand is busy")

    # ---------- training ----------

    def start_recording(self, label):
        if label not in self.config["gestures"]:
            raise ValueError(f"{label!r} is not one of the configured gestures")
        with self._lock:
            if self._link is None:
                raise ConnectionError("connect the wand first")
            if self._recording_label or self._wand_state != "IDLE":
                raise RuntimeError("the wand is busy")
            self._recording_label = label
        wand = self.simulated_wand
        if wand:  # the simulated user performs the gesture being recorded
            wand.perform(label if label in GESTURES else "WOBBLE")
        self._publish_status()
        self._send(encode_start_recording())

    def stop_recording(self):
        with self._lock:
            if not self._recording_label:
                return
        self._send(encode_stop_recording())

    # ---------- dataset ----------

    def samples(self):
        return [asdict(info) for info in list_samples(self.data_dir)]

    def sample_detail(self, sample_id):
        sequence = load_sample(sample_id, self.data_dir)
        return {"sample_id": sample_id, "label": sequence.label, "sample_count": len(sequence.t_ms),
                **self._motion_payload(sequence)}

    def delete_sample(self, sample_id):
        delete_sample(sample_id, self.data_dir)
        self._retrain()
        self._publish_status()

    def check_dataset(self):
        """Compare every saved sample with all the others (see classifier.leave_one_out)."""
        infos = list_samples(self.data_dir)
        checks = leave_one_out([load_sample(info.sample_id, self.data_dir) for info in infos])
        threshold = self.config["dtw_threshold"]
        return [{
            "sample_id": info.sample_id,
            "label": check.label,
            "nearest_label": check.nearest_label,
            "distance": _finite(check.distance),
            "suspicious": check.nearest_label != check.label or check.distance > threshold,
        } for info, check in zip(infos, checks)]

    # ---------- settings ----------

    def get_config(self):
        return copy.deepcopy(self.config)

    def update_config(self, new_config):
        saved = save_config(new_config, self.config_path)  # raises ConfigError if invalid
        with self._lock:
            self.config = saved
        self._retrain()
        self._publish_status()
        return copy.deepcopy(saved)

    # ---------- status and events for the UI ----------

    def status(self):
        with self._lock:
            return {
                "connected": self._link is not None,
                "mode": self._mode,
                "link_name": getattr(self._link, "name", None),
                "wand_state": self._wand_state,
                "recording": self._recording_label,
                "dataset": dict(self._dataset_counts),
                "threshold": self.config["dtw_threshold"],
                "history": list(self._history),
            }

    def subscribe(self):
        events = queue.Queue(maxsize=2000)
        with self._lock:
            self._subscribers.append(events)
        return events

    def unsubscribe(self, events):
        with self._lock:
            if events in self._subscribers:
                self._subscribers.remove(events)

    # ---------- internals ----------

    def _send(self, data):
        link = self._link
        if link is None:
            raise ConnectionError("wand not connected")
        link.send(data)

    def _on_event(self, data):
        try:
            event = decode_event(data)
        except ProtocolError as error:
            self._publish("message", {"level": "warning", "text": f"Ignored a bad message from the wand: {error}"})
            return

        if isinstance(event, CastStart):
            with self._lock:
                self._cast_source = event.source
                self._cast_samples = []
                self._wand_state = "CASTING"
            self._publish("cast_start", {"source": "recording" if event.source == SOURCE_RECORDING else "button"})
            self._publish_status()

        elif isinstance(event, MotionSample):
            with self._lock:
                if self._cast_source is None:
                    return  # a stray sample outside a cast
                self._cast_samples.append(event)
                full_batch = len(self._cast_samples) % MOTION_BATCH == 0
                batch = self._cast_samples[-MOTION_BATCH:] if full_batch else None
            if batch:
                self._publish("motion", {"rows": [[s.t_ms, s.ax, s.ay, s.az, s.gx, s.gy, s.gz] for s in batch]})

        elif isinstance(event, CastEnd):
            with self._lock:
                samples, source = self._cast_samples, self._cast_source
                self._cast_samples, self._cast_source = [], None
                label = self._recording_label if source == SOURCE_RECORDING else None
                if source == SOURCE_RECORDING:
                    self._recording_label = None
                self._wand_state = "INFLIGHT" if source is not None and source != SOURCE_RECORDING else "IDLE"
            if source is None:
                return
            self._publish_status()
            if source == SOURCE_RECORDING:
                self._background(lambda: self._finish_recording(samples, label, event))
            else:
                self._background(lambda: self._finish_cast(samples, event))

        elif isinstance(event, ActionComplete):
            self.dispatcher.action_complete(event)

    def _finish_cast(self, samples, end):
        sequence = sequence_from_samples(samples)
        with self._lock:
            result = self.classifier.classify(sequence)
            config = self.config
        gesture = config["gestures"].get(result.label)
        colour = gesture["color"] if gesture else config["unknown_color"]
        try:
            self._send(encode_gesture_result(result.label, hex_to_rgb(colour)))
        except ConnectionError:
            pass  # the wand will time out and flash "no answer"
        with self._lock:
            self._wand_state = "IDLE"
            self._history.appendleft({"label": result.label, "distance": _finite(result.distance)})

        self._publish("result", {
            "label": result.label,
            "distance": _finite(result.distance),
            "nearest_label": result.nearest_label,
            "threshold": config["dtw_threshold"],
            "color": colour,
            "sample_count": len(sequence.t_ms),
            "dropped": max(0, end.sample_count - len(sequence.t_ms)),
            **self._motion_payload(sequence),
        })
        self._publish_status()

        outcome = self.dispatcher.dispatch(result.label, gesture["action"] if gesture else {"type": "none"})
        if outcome:
            self._publish("action", asdict(outcome))

    def _finish_recording(self, samples, label, end):
        if label is None:
            return
        sequence = sequence_from_samples(samples, label)
        n = len(sequence.t_ms)
        if n < MIN_SAMPLES:
            self._publish("message", {"level": "warning",
                                      "text": f"Recording was too short ({n} samples), so it was not saved."})
            return
        sample_id = save_sample(sequence, self.data_dir)
        self._retrain()
        self._publish("sample_saved", {"sample_id": sample_id, "label": label, "sample_count": n,
                                       "dropped": max(0, end.sample_count - n)})
        if end.reason == END_MAX_DURATION:
            self._publish("message", {"level": "info", "text": "Recording reached the 5 s limit and stopped itself."})
        self._publish_status()

    def _on_link_lost(self):
        with self._lock:
            if self._link is None:
                return
            self._link, self._mode = None, None
            self._reset_cast()
        self._publish("message", {"level": "warning", "text": "The wand disconnected."})
        self._publish_status()

    def _reset_cast(self):
        self._cast_samples, self._cast_source = [], None
        self._recording_label = None
        self._wand_state = "IDLE"

    def _retrain(self):
        """Refit the classifier on the saved samples of the configured gestures."""
        dataset = load_dataset(self.data_dir)
        with self._lock:
            labels = self.config["gestures"]
            self.classifier.threshold = self.config["dtw_threshold"]
            self.classifier.fit([s for s in dataset if s.label in labels and len(s.t_ms) >= MIN_SAMPLES])
            self._dataset_counts = dict(Counter(s.label for s in dataset))

    def _motion_payload(self, sequence):
        """Time, raw signals and 3D tip path of a GestureSequence, ready for the UI's charts."""
        if len(sequence.t_ms) == 0:
            return {"t": [], "accel": [[], [], []], "gyro": [[], [], []], "trace": {"x": [], "y": [], "z": []}}
        t = np.asarray(sequence.t_ms, dtype=float)
        imu = np.asarray(sequence.imu, dtype=float)
        trace = tip_trace(sequence)

        def rounded(values):
            return np.round(values, 4).tolist()

        return {
            "t": rounded((t - t[0]) / 1000.0),
            "accel": [rounded(imu[:, k]) for k in range(0, 3)],
            "gyro": [rounded(imu[:, k]) for k in range(3, 6)],
            "trace": {"x": rounded(trace[:, 0]), "y": rounded(trace[:, 1]), "z": rounded(trace[:, 2])},
        }

    def _publish_status(self):
        self._publish("status", self.status())

    def _publish(self, kind, data):
        with self._lock:
            subscribers = list(self._subscribers)
        for events in subscribers:
            try:
                events.put_nowait({"type": kind, "data": data})
            except queue.Full:
                pass  # a stalled browser tab must not block the wand
