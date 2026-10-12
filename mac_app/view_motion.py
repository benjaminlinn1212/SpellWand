"""Show a saved sample in 3D in your web browser.

    .venv/bin/python view_motion.py                  # list saved samples
    .venv/bin/python view_motion.py SAMPLE_ID        # e.g. CIRCLE_20261011-231502-123456
    .venv/bin/python view_motion.py path/to/file.csv

Draws the path of the wand tip (see motion_trace.py), coloured by time, seen from
behind your hand, plus the raw accelerometer and gyroscope readings. Drag to rotate.
Needs an internet connection the first time, to load the Plotly charting library.
"""

import argparse
import html
import json
import sys
import tempfile
import webbrowser
from pathlib import Path

import numpy as np

from motion_trace import tip_trace
from recorder import list_samples, load_sample

PLOTLY_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SpellWand: __TITLE__</title>
<script src="__PLOTLY__"></script>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 960px; margin: 16px auto;
         padding: 0 16px; color: #1d1d1f; background: #fff; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  p { color: #666; margin: 0 0 12px; }
  #trace { height: 520px; }
  .chart { height: 240px; }
</style>
</head>
<body>
<h1>__TITLE__</h1>
<p>__INFO__</p>
<div id="trace"></div>
<div id="accel" class="chart"></div>
<div id="gyro" class="chart"></div>
<script>
const d = __DATA__;
const last = d.x.length - 1;

function wand(k, name, color) {
  return { type: "scatter3d", mode: "lines+markers", name,
           x: [0, d.x[k]], y: [0, d.y[k]], z: [0, d.z[k]],
           line: { width: 4, color }, marker: { size: [3, 6], color } };
}

Plotly.newPlot("trace", [
  { type: "scatter3d", mode: "lines", name: "wand tip path",
    x: d.x, y: d.y, z: d.z, text: d.t.map(t => t.toFixed(2) + " s"),
    hovertemplate: "%{text}<extra></extra>",
    line: { width: 8, color: d.t, colorscale: "Viridis", showscale: true,
            colorbar: { title: { text: "time (s)" } } } },
  wand(0, "wand at start", "#2e7d32"),
  wand(last, "wand at end", "#c62828"),
], {
  margin: { l: 0, r: 0, t: 0, b: 0 },
  legend: { x: 0, y: 1 },
  scene: {
    aspectmode: "data",
    xaxis: { title: { text: "forward (m)" } },
    yaxis: { title: { text: "left (m)" } },
    zaxis: { title: { text: "up (m)" } },
    camera: { eye: { x: -1.6, y: 0, z: 0.5 }, up: { x: 0, y: 0, z: 1 } },  // behind your hand
  },
});

const axes = ["x (along wand)", "y (left)", "z (up)"];
function signals(div, columns, title) {
  Plotly.newPlot(div, columns.map((values, i) => ({ x: d.t, y: values, name: axes[i], mode: "lines" })), {
    title: { text: title }, margin: { l: 50, r: 10, t: 40, b: 40 }, xaxis: { title: { text: "time (s)" } },
  });
}
signals("accel", d.accel, "Accelerometer (m/s²)");
signals("gyro", d.gyro, "Gyroscope (rad/s)");
</script>
</body>
</html>
"""


def motion_page(sequence, title):
    """A standalone HTML page showing one GestureSequence."""
    t = np.asarray(sequence.t_ms, dtype=float)
    imu = np.asarray(sequence.imu, dtype=float)
    trace = tip_trace(sequence)

    def rounded(values):
        return np.round(values, 4).tolist()

    data = {
        "t": rounded((t - t[0]) / 1000.0),
        "x": rounded(trace[:, 0]), "y": rounded(trace[:, 1]), "z": rounded(trace[:, 2]),
        "accel": [rounded(imu[:, k]) for k in range(0, 3)],
        "gyro": [rounded(imu[:, k]) for k in range(3, 6)],
    }
    info = f"{sequence.label or 'unlabelled'} · {len(t)} samples · {(t[-1] - t[0]) / 1000:.2f} s"
    return (PAGE.replace("__PLOTLY__", PLOTLY_URL)
                .replace("__TITLE__", html.escape(title))
                .replace("__INFO__", html.escape(info))
                .replace("__DATA__", json.dumps(data)))


def main():
    parser = argparse.ArgumentParser(description="Show a saved SpellWand sample in 3D in your browser.")
    parser.add_argument("sample", nargs="?", help="sample id from data/, or a path to a .csv file; omit to list samples")
    parser.add_argument("--no-open", action="store_true", help="only write the page and print where it is")
    args = parser.parse_args()

    if args.sample is None:
        samples = list_samples()
        for info in samples:
            print(f"{info.sample_id}   {info.n_samples} samples, {info.duration_ms / 1000:.2f} s")
        if not samples:
            print("No samples saved yet in data/")
        return

    path = Path(args.sample)
    try:
        if path.suffix == ".csv":
            sequence, name = load_sample(path.stem, path.parent), path.stem
        else:
            sequence, name = load_sample(args.sample), args.sample
    except (ValueError, FileNotFoundError) as error:
        sys.exit(f"Can't open {args.sample}: {error}\nRun without arguments to list saved samples.")

    page = Path(tempfile.gettempdir()) / f"spellwand_{name}.html"
    page.write_text(motion_page(sequence, name))
    print(page)
    if not args.no_open:
        webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()
