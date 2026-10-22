"""SpellWand UI: the local web app.

    .venv/bin/python app.py              # real wand over Bluetooth (connect from the page)
    .venv/bin/python app.py --simulate   # simulated wand and demo dataset, no hardware needed

Then open http://127.0.0.1:8780. Start it from VS Code's terminal or the Claude desktop
Terminal panel so macOS lets it use Bluetooth (see README).

The page talks only to this Python backend; the browser never talks to the wand directly.
"""

import argparse
import functools
import json
import queue
import shutil
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from config import ACTION_TYPES, CONFIG_PATH, load_config, save_config
from controller import SpellWandController
from recorder import DATA_DIR
from simulator import GESTURES, OTHER_MOTIONS

HOST = "127.0.0.1"  # this machine only: never reachable from the network
PORT = 8780         # (macOS uses 5000 for AirPlay)
APP_DIR = Path(__file__).parent
SAMPLE_DATA_DIR = APP_DIR / "sample_data"
SIMULATION_DIR = APP_DIR / "sim_data"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
HEARTBEAT_S = 15


def create_app(controller):
    app = Flask(__name__)

    @app.before_request
    def protect():
        # Only answer requests addressed to this machine by name (blocks DNS rebinding),
        # and only accept JSON for changes: a form on another website can't send JSON
        # here without the browser asking permission first.
        host = request.host or ""
        name = host[1:host.find("]")] if host.startswith("[") else host.rsplit(":", 1)[0]
        if name not in ALLOWED_HOSTS:
            return jsonify(error="unknown host"), 403
        if request.method in ("POST", "PUT", "DELETE") and not request.is_json:
            return jsonify(error="send JSON (Content-Type: application/json)"), 415
        return None

    def api(view):
        """Turn the controller's exceptions into readable JSON errors."""
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            try:
                return view(*args, **kwargs)
            except FileNotFoundError:
                return jsonify(error="no such sample"), 404
            except (ConnectionError, RuntimeError) as error:
                return jsonify(error=str(error)), 409
            except ValueError as error:
                return jsonify(error=str(error)), 400
        return wrapper

    def body():
        return request.get_json(silent=True) or {}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        return jsonify(controller.status())

    @app.get("/api/meta")
    def meta():
        return jsonify(action_types=ACTION_TYPES, simulated_motions=list(GESTURES) + list(OTHER_MOTIONS))

    @app.post("/api/connect")
    @api
    def connect():
        controller.connect(body().get("mode", "ble"))
        return jsonify(controller.status())

    @app.post("/api/disconnect")
    @api
    def disconnect():
        controller.disconnect()
        return jsonify(controller.status())

    @app.post("/api/simulate")
    @api
    def simulate():
        controller.simulate_cast(body().get("motion", ""))
        return jsonify(ok=True)

    @app.post("/api/recording/start")
    @api
    def start_recording():
        controller.start_recording(body().get("label", ""))
        return jsonify(controller.status())

    @app.post("/api/recording/stop")
    @api
    def stop_recording():
        controller.stop_recording()
        return jsonify(controller.status())

    @app.get("/api/samples")
    @api
    def samples():
        return jsonify(controller.samples())

    # <path:...> so that ids containing "/" reach the recorder's own validation (400)
    @app.get("/api/samples/<path:sample_id>")
    @api
    def sample(sample_id):
        return jsonify(controller.sample_detail(sample_id))

    @app.delete("/api/samples/<path:sample_id>")
    @api
    def delete(sample_id):
        controller.delete_sample(sample_id)
        return jsonify(ok=True)

    @app.post("/api/dataset/check")
    @api
    def check_dataset():
        return jsonify(controller.check_dataset())

    @app.get("/api/config")
    def get_config():
        return jsonify(controller.get_config())

    @app.put("/api/config")
    @api
    def put_config():
        return jsonify(controller.update_config(body()))

    @app.get("/api/events")
    def events():
        """Server-sent events: the page receives live updates as they happen."""
        subscription = controller.subscribe()

        def stream():
            try:
                yield _sse("status", controller.status())
                while True:
                    try:
                        event = subscription.get(timeout=HEARTBEAT_S)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    yield _sse(event["type"], event["data"])
            finally:
                controller.unsubscribe(subscription)

        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})

    return app


def _sse(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, allow_nan=False)}\n\n"


def prepare_simulation_folder():
    """Simulation mode keeps its own data and settings, so it never touches the real ones.
    The first time, it starts from the bundled simulated samples."""
    data_dir = SIMULATION_DIR / "data"
    config_path = SIMULATION_DIR / "config.json"
    if not data_dir.exists():
        data_dir.mkdir(parents=True)
        for csv_file in SAMPLE_DATA_DIR.glob("*.csv"):
            shutil.copy(csv_file, data_dir)
    if not config_path.exists():
        save_config(load_config(CONFIG_PATH), config_path)
    return data_dir, config_path


def main():
    parser = argparse.ArgumentParser(description="Run the SpellWand UI.")
    parser.add_argument("--simulate", action="store_true",
                        help="use the simulated wand and a separate demo dataset (sim_data/)")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()

    if args.simulate:
        data_dir, config_path = prepare_simulation_folder()
    else:
        data_dir, config_path = DATA_DIR, CONFIG_PATH
    controller = SpellWandController(data_dir=data_dir, config_path=config_path)
    if args.simulate:
        controller.connect("simulated")

    url = f"http://{HOST}:{args.port}"
    print(f"SpellWand UI running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    create_app(controller).run(host=HOST, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
