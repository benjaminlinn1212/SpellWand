"""Draws the SpellWand diagrams in this folder as SVG files (plain Python, no packages).

    python3 docs/diagrams/make_diagrams.py

Also makes PNG copies with macOS Quick Look (qlmanage), for documents that can't take SVG.
Diagrams: code_flowchart, wand_states, classifier_pipeline, circuit.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent
FONT = "Helvetica Neue, Helvetica, Arial, sans-serif"
INK = "#1f2430"
MUTED = "#5b6070"
WHITE = "#ffffff"

WAND = ("#e8eeff", "#3d5bd9")     # fill, stroke
MAC = ("#e6f5ec", "#2f8f55")
NEUTRAL = ("#f4f5f8", "#8a8fa0")
TO_MAC = "#d9822b"                # wand -> Mac messages
TO_WAND = "#7b4fd6"               # Mac -> wand messages
NO = ("#fdecec", "#c62828")

ARROW_COLOURS = {"ink": INK, "tomac": TO_MAC, "towand": TO_WAND, "no": NO[1], "muted": MUTED}


class Svg:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.parts = []

    def add(self, markup):
        self.parts.append(markup)

    def text(self, x, y, s, size=13, anchor="start", weight=400, fill=INK, italic=False, halo=False):
        extra = ' font-style="italic"' if italic else ""
        if halo:  # white outline so the label stays readable on top of lines
            extra += ' paint-order="stroke" stroke="#ffffff" stroke-width="5" stroke-linejoin="round"'
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
                 f'text-anchor="{anchor}" fill="{fill}"{extra}>{escape(s)}</text>')

    def lines(self, x, y, items, size=12.5, gap=18, **kwargs):
        for i, s in enumerate(items):
            self.text(x, y + i * gap, s, size=size, **kwargs)

    def rect(self, x, y, w, h, fill, stroke, rx=8, dash=None, width=1.5):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{width}"{d}/>')

    def line(self, points, colour=INK, width=2, arrow=None, dash=None):
        pts = " ".join(f"{x},{y}" for x, y in points)
        d = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#arrow-{arrow})"' if arrow else ""
        self.add(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="{width}" '
                 f'stroke-linejoin="round"{d}{m}/>')

    def path(self, d, colour=INK, width=2, arrow=None, fill="none", dash=None):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#arrow-{arrow})"' if arrow else ""
        self.add(f'<path d="{d}" fill="{fill}" stroke="{colour}" stroke-width="{width}" '
                 f'stroke-linejoin="round"{da}{m}/>')

    def circle(self, x, y, r, fill, stroke=None, width=1.5):
        s = f' stroke="{stroke}" stroke-width="{width}"' if stroke else ""
        self.add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"{s}/>')

    def save_with_size(self, name, title):
        return self.save(name, title), self.width, self.height

    def save(self, name, title):
        markers = "".join(
            f'<marker id="arrow-{key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{colour}"/></marker>'
            for key, colour in ARROW_COLOURS.items())
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
               f'viewBox="0 0 {self.width} {self.height}" font-family="{FONT}">\n'
               f'<title>{escape(title)}</title>\n<defs>{markers}</defs>\n'
               f'<rect width="100%" height="100%" fill="{WHITE}"/>\n' + "\n".join(self.parts) + "\n</svg>\n")
        path = OUT / f"{name}.svg"
        path.write_text(svg, encoding="utf-8")
        return path


# ---------- shared flowchart pieces ----------

def step(svg, x, y, w, title, items, scheme, size=12.5):
    """A box with a bold title and a few lines; returns its height."""
    h = 34 + 18 * len(items) if items else 40
    svg.rect(x, y, w, h, scheme[0], scheme[1])
    svg.text(x + 14, y + 24, title, size=13.5, weight=700)
    svg.lines(x + 14, y + 44, items, size=size, fill=INK)
    return h


def pill(svg, cx, y, w, label, scheme, h=36):
    svg.rect(cx - w / 2, y, w, h, scheme[0], scheme[1], rx=h / 2)
    svg.text(cx, y + h / 2 + 5, label, size=13, anchor="middle", weight=600)


def diamond(svg, cx, cy, hw, hh, items, scheme):
    svg.path(f"M{cx},{cy - hh} L{cx + hw},{cy} L{cx},{cy + hh} L{cx - hw},{cy} Z",
             colour=scheme[1], width=1.5, fill=scheme[0])
    top = cy - (len(items) - 1) * 8 + 4
    for i, s in enumerate(items):
        svg.text(cx, top + i * 16, s, size=12.5, anchor="middle", weight=600)


def down(svg, x, y1, y2, colour=INK):
    svg.line([(x, y1), (x, y2)], colour=colour, width=1.8, arrow="ink")


def header(svg, x, w, title, subtitle, scheme):
    svg.rect(x, 92, w, 46, scheme[0], scheme[1])
    svg.text(x + w / 2, 112, title, size=14, anchor="middle", weight=700)
    svg.text(x + w / 2, 129, subtitle, size=11, anchor="middle", fill=MUTED)


# ---------- 1. code flowchart ----------

def code_flowchart():
    svg = Svg(1240, 1180)
    svg.text(30, 44, "SpellWand: code flow", size=22, weight=700)
    svg.text(30, 68, "What the wand firmware and the Mac app do, and the BLE_LINK messages between them.",
             size=13, fill=MUTED)

    header(svg, 30, 380, "Wand firmware (ESP32)", "firmware/src/main.cpp + lib/wand_core", WAND)
    header(svg, 430, 380, "BLE_LINK messages", "docs/protocol.md", ("#fbf3ea", TO_MAC))
    header(svg, 830, 380, "Mac app (Python)", "mac_app/: app.py, controller.py, classifier.py, ...", MAC)

    # --- wand column ---
    wx, ww, wc = 50, 340, 220
    pill(svg, wc, 156, 230, "Power on (slide switch)", WAND)
    down(svg, wc, 192, 210)
    step(svg, wx, 212, ww, "setup()", [
        "Serial, CAST_BUTTON pull-up, RGB LED PWM",
        "Find the IMU at 0x68 / 0x69, read WHO_AM_I",
        "Set 100 Hz, ±8 g, ±2000 °/s, 45 Hz low-pass",
        "Measure gyro offset (wand still, up to 3 s)",
        'Start BLE, advertise "SpellWand"',
    ], WAND)
    down(svg, wc, 338, 360)

    svg.rect(30, 362, 380, 600, "none", WAND[1], rx=12, dash="6 5")
    svg.text(46, 386, "loop(): runs continuously", size=13.5, weight=700, fill=WAND[1])
    y = 402
    h = step(svg, wx, y, ww, "Read the IMU (new reading every 10 ms)", [
        "convert to m/s² and rad/s, subtract gyro offset;",
        "while IDLE, keep re-measuring the offset"], WAND)
    read_mid = y + h / 2
    down(svg, wc, y + h, y + h + 18)
    y = 488
    h = step(svg, wx, y, ww, "If CASTING: send MOTION_SAMPLE", ["index, time, accel, gyro (19 bytes)"], WAND)
    sample_y = y + h / 2
    down(svg, wc, y + h, y + h + 18)
    y = 560
    h = step(svg, wx, y, ww, "Handle commands from the Mac", [
        "START / STOP_RECORDING, GESTURE_RESULT,",
        "EXECUTE_ACTION (replies ACTION_COMPLETE)"], WAND)
    command_out_y, command_in_y = y + 24, y + h - 14
    down(svg, wc, y + h, y + h + 18)
    y = 648
    h = step(svg, wx, y, ww, "Read CAST_BUTTON (debounced 30 ms)", [
        "pressed in IDLE: CAST_START, now CASTING",
        "released: CAST_END, now INFLIGHT (amber)"], WAND)
    button_y = y + h / 2
    down(svg, wc, y + h, y + h + 18)
    y = 736
    h = step(svg, wx, y, ww, "tick(): time limits", [
        "cast 3 s / recording 5 s: CAST_END",
        "no GESTURE_RESULT within 2 s: magenta flashes"], WAND)
    tick_y = y + h / 2
    down(svg, wc, y + h, y + h + 18)
    y = 824
    h = step(svg, wx, y, ww, "Update STATUS_LED and action LED", [
        "state colour, spell colour, or flashes"], WAND)
    svg.line([(wc, y + h), (wc, y + h + 22), (40, y + h + 22), (40, read_mid), (48, read_mid)],
             width=1.8, arrow="ink")
    svg.text(56, y + h + 40, "back to the top", size=11.5, fill=MUTED, italic=True)
    svg.text(30, 990, "States IDLE / CASTING / INFLIGHT in detail: wand_states.svg", size=12, fill=MUTED,
             italic=True)

    # --- Mac column ---
    mx, mw, mc = 850, 340, 1020
    pill(svg, mc, 156, 290, "python3 app.py   (or --simulate)", MAC)
    down(svg, mc, 192, 210)
    step(svg, mx, 212, mw, "Startup", [
        "Load config.json: threshold, gestures, colours",
        "Load samples from data/, fit the classifier",
        "Connect: BLE Manager (Bleak) or simulated wand",
        "Open the SpellWand UI in the browser",
        "(live updates through server-sent events)",
    ], MAC)
    down(svg, mc, 338, 360)

    svg.rect(830, 362, 380, 712, "none", MAC[1], rx=12, dash="6 5")
    svg.text(846, 386, "controller.py: for each message from the wand", size=13.5, weight=700, fill=MAC[1])
    y = 402
    h = step(svg, mx, y, mw, "Decode the message (protocol.py)", [], MAC)
    decode_y = y + h / 2
    down(svg, mc, y + h, y + h + 18)
    y = 460
    h = step(svg, mx, y, mw, "Depending on the message", [
        "CAST_START: clear the buffer, UI shows Casting…",
        "MOTION_SAMPLE: add to buffer, live charts",
        "ACTION_COMPLETE: give to the Action Dispatcher",
        "CAST_END: continue below"], MAC)
    down(svg, 940, y + h, 588)

    diamond(svg, 940, 620, 96, 32, ["Training", "recording?"], MAC)
    svg.line([(1036, 620), (1076, 620)], width=1.8, arrow="ink")
    svg.text(1044, 612, "yes", size=11.5, fill=MUTED)
    svg.rect(1078, 584, 122, 74, MAC[0], MAC[1])
    svg.lines(1086, 602, ["Sample Recorder:", "≥ 10 samples? save", "CSV, retrain"], size=11.5, gap=16)
    down(svg, 940, 652, 674)
    svg.text(948, 668, "no", size=11.5, fill=MUTED)

    y = 676
    h = step(svg, mx, y, mw, "Gesture Classifier (classifier.py)", [
        "GestureResult: label or UNKNOWN, distance,",
        "nearest gesture (see classifier_pipeline.svg)"], MAC)
    down(svg, mc, y + h, y + h + 18)
    y = 764
    h = step(svg, mx, y, mw, "Send GESTURE_RESULT", ["label + colour from config.json"], MAC)
    result_y = y + h / 2
    down(svg, mc, y + h, y + h + 18)
    y = 834
    h = step(svg, mx, y, mw, "Show the result in the UI", ["label, distance, 3D trail, live charts"], MAC)
    down(svg, mc, y + h, 920)

    diamond(svg, mc, 952, 120, 32, ["Not UNKNOWN and", "an action is set?"], MAC)
    svg.text(mc + 128, 948, "no: done", size=11.5, fill=MUTED)
    down(svg, mc, 984, 1000)
    svg.text(mc + 8, 996, "yes", size=11.5, fill=MUTED)
    y = 1002
    h = step(svg, mx, y, mw, "Action Dispatcher", [
        "wand LED (EXECUTE_ACTION), notification,",
        "or web request (e.g. Home Assistant)"], MAC)
    action_y = y + 24

    y = 1094
    h = step(svg, mx, y, mw, "Training buttons in the SpellWand UI", [
        "Start recording / Stop and save"], NEUTRAL)
    train_y = y + h / 2

    # --- messages: wand -> Mac (one shared line into "Decode") ---
    bus_a, bus_b = 600, 660
    for yy, label in [(sample_y, "MOTION_SAMPLE ×N (≈100/s)"), (command_out_y, "ACTION_COMPLETE"),
                      (button_y, "CAST_START / CAST_END"), (tick_y, "CAST_END (time limit)")]:
        svg.line([(390, yy), (bus_a, yy)], colour=TO_MAC, width=2.2)
        svg.text(398, yy - 7, label, size=11.5, fill=TO_MAC, weight=600, halo=True)
    svg.line([(bus_a, tick_y), (bus_a, decode_y), (848, decode_y)], colour=TO_MAC, width=2.2, arrow="tomac")
    svg.text(612, decode_y - 8, "to the Mac (BLE notify)", size=11.5, fill=TO_MAC, italic=True, halo=True)

    # --- messages: Mac -> wand (one shared line into "Handle commands") ---
    for yy, label in [(result_y, "GESTURE_RESULT"), (action_y, "EXECUTE_ACTION"),
                      (train_y, "START_ / STOP_RECORDING")]:
        svg.line([(850, yy), (bus_b, yy)], colour=TO_WAND, width=2.2)
        svg.text(842, yy - 7, label, size=11.5, anchor="end", fill=TO_WAND, weight=600, halo=True)
    hop = 7  # little bridge where this line crosses the wand -> Mac line
    svg.path(f"M{bus_b},{train_y} L{bus_b},{command_in_y} L{bus_a + hop},{command_in_y} "
             f"A{hop},{hop} 0 0 0 {bus_a - hop},{command_in_y} L392,{command_in_y}",
             colour=TO_WAND, width=2.2, arrow="towand")
    svg.text(486, command_in_y + 18, "to the wand (BLE write)", size=11.5, fill=TO_WAND, italic=True,
             anchor="middle", halo=True)
    return svg.save_with_size("code_flowchart", "SpellWand code flow")


# ---------- 2. wand states ----------

def wand_states():
    svg = Svg(980, 480)
    svg.text(30, 40, "SpellWand: wand states", size=22, weight=700)
    svg.text(30, 62, "firmware/lib/wand_core/wand_state.cpp. LED feedback is separate from the three states.",
             size=13, fill=MUTED)

    def state(x, y, name, led, colour):
        svg.rect(x, y, 170, 66, "#ffffff", INK, rx=14, width=2)
        svg.text(x + 85, y + 30, name, size=17, anchor="middle", weight=700)
        svg.circle(x + 44, y + 47, 6, colour, stroke="#8a8fa0", width=1)
        svg.text(x + 56, y + 51, led, size=11.5, fill=MUTED)

    state(70, 220, "IDLE", "LED dim white", "#e4e4ea")
    state(440, 100, "CASTING", "LED blue", "#2f55ff")
    state(440, 350, "INFLIGHT", "LED amber", "#ff9600")

    # IDLE -> CASTING
    svg.path("M150,218 C150,140 300,120 438,128", width=2, arrow="ink")
    svg.lines(44, 104, ["CAST_BUTTON pressed → CAST_START (button)",
                        "START_RECORDING → CAST_START (recording)"], size=12)
    # CASTING -> INFLIGHT
    svg.line([(525, 168), (525, 348)], width=2, arrow="ink")
    svg.lines(538, 236, ["button cast ends: released", "or 3 s limit → CAST_END,",
                         "then wait for the Mac"], size=12)
    # CASTING -> IDLE (recordings)
    svg.path("M438,150 C360,165 300,215 242,240", width=2, arrow="ink")
    svg.lines(268, 214, ["recording ends:", "STOP_RECORDING, 5 s limit", "or connection lost → CAST_END"],
              size=12, halo=True)
    # INFLIGHT -> IDLE
    svg.path("M438,383 C300,390 190,350 160,290", width=2, arrow="ink")
    svg.lines(150, 408, ["GESTURE_RESULT: spell colour for 1 s",
                         "(UNKNOWN: 3 flashes), or no answer",
                         "within 2 s: 2 magenta flashes"], size=12)

    # LED legend
    svg.rect(730, 100, 220, 300, "#fafafc", "#d0d3dc", rx=10)
    svg.text(746, 126, "STATUS_LED", size=13.5, weight=700)
    rows = [("#e4e4ea", "IDLE: dim white"), ("#2f55ff", "CASTING: blue"), ("#ff9600", "INFLIGHT: amber"),
            (None, "spell colour for 1 s"), ("#ff0000", "UNKNOWN colour ×3 flashes"),
            ("#ff00ff", "magenta ×2: no answer")]
    for i, (colour, label) in enumerate(rows):
        yy = 158 + i * 34
        if colour:
            svg.circle(758, yy - 4, 8, colour, stroke="#8a8fa0", width=1)
        else:
            for j, c in enumerate(["#0050ff", "#ff4000", "#00c828"]):
                svg.circle(752 + j * 7, yy - 4, 6, c, stroke="#ffffff", width=1)
        svg.text(776, yy, label, size=12)
    svg.lines(746, 366, ["Spell colours come from config.json", "with each GESTURE_RESULT."], size=11,
              gap=15, fill=MUTED)
    return svg.save_with_size("wand_states", "SpellWand wand states")


# ---------- 3. classifier pipeline ----------

def classifier_pipeline():
    svg = Svg(1560, 340)
    svg.text(30, 42, "SpellWand: how a cast is classified", size=22, weight=700)
    svg.text(30, 64, "mac_app/classifier.py. Training examples get the same steps (once, when the dataset "
             "changes); every new cast is compared with them.", size=13, fill=MUTED)

    y, h, w, gap = 110, 112, 152, 22
    x = 30
    pill_h = 72
    svg.rect(x, y + (h - pill_h) / 2, 132, pill_h, NEUTRAL[0], NEUTRAL[1], rx=16)
    svg.lines(x + 66, y + h / 2 - 6, ["GestureSequence", "t + 6 values/sample"], size=12, anchor="middle",
              weight=600)
    x += 132 + gap
    boxes = [
        ("Cut still time", ["start and end: below", "10 % of peak", "turning speed"]),
        None,  # "moved enough?" check
        ("Remove gravity", ["follow the gyro to", "know which way is", "down, subtract it"]),
        ("Resample", ["40 evenly spaced", "points: fast and slow", "casts line up"]),
        ("Units and size", ["g and half-turns/s,", "scale to size 1: big", "and small match"]),
        ("Compare (DTW)", ["with every stored", "example; average", "distance per point"]),
        ("Decide", ["nearest example within", "the threshold: its", "label, else UNKNOWN"]),
    ]
    for box in boxes:
        svg.line([(x - gap, y + h / 2), (x - 2, y + h / 2)], width=1.8, arrow="ink")
        if box is None:
            cx = x + w / 2
            diamond(svg, cx, y + h / 2, w / 2, h / 2, ["Moved", "enough?"], MAC)
            svg.lines(cx - 10, y + h + 20, ["≥ 10 samples and", "avg turn ≥ 17 °/s?"], size=11, gap=15,
                      anchor="end", fill=MUTED)
            svg.line([(cx, y + h), (cx, 280)], colour=NO[1], width=1.8, arrow="no")
            svg.text(cx + 8, 268, "no", size=11.5, fill=NO[1])
            svg.text(x + w + 2, y + h / 2 - 8, "yes", size=11, fill=MUTED)
            svg.rect(cx - 52, 282, 104, 32, NO[0], NO[1], rx=16)
            svg.text(cx, 303, "UNKNOWN", size=12.5, anchor="middle", weight=700, fill=NO[1])
        else:
            title, items = box
            svg.rect(x, y, w, h, MAC[0], MAC[1])
            svg.text(x + 12, y + 24, title, size=13.5, weight=700)
            svg.lines(x + 12, y + 46, items, size=12)
        x += w + gap
    svg.line([(x - gap, y + h / 2), (x - 2, y + h / 2)], width=1.8, arrow="ink")
    svg.rect(x, y + (h - pill_h) / 2, 140, pill_h, NEUTRAL[0], NEUTRAL[1], rx=16)
    svg.lines(x + 70, y + h / 2 - 6, ["GestureResult", "label, distance"], size=12, anchor="middle", weight=600)
    return svg.save_with_size("classifier_pipeline", "SpellWand classification pipeline")


# ---------- 4. circuit ----------

POWER = "#d32f2f"
RAIL_3V3 = "#ef6c00"
SIGNAL = "#1e3a8a"
I2C = "#00838f"


def ground(svg, x, y):
    """Ground symbol hanging from (x, y)."""
    svg.line([(x, y), (x, y + 10)], width=2)
    for i, half in enumerate([12, 8, 4]):
        svg.line([(x - half, y + 10 + 4 * i), (x + half, y + 10 + 4 * i)], width=2)


def resistor(svg, x, y, length=60, label=None, value=None):
    """Horizontal zigzag resistor from (x, y) to (x + length, y)."""
    lead = 10
    pts = [(x, y), (x + lead, y)]
    n = 6
    step_x = (length - 2 * lead) / n
    for i in range(n):
        pts.append((x + lead + step_x * (i + 0.5), y + (-7 if i % 2 == 0 else 7)))
    pts += [(x + length - lead, y), (x + length, y)]
    svg.line(pts, width=2)
    if label:
        svg.text(x + length / 2, y - 13, f"{label}  {value}", size=11.5, anchor="middle", weight=600, halo=True)


def led(svg, x, y, colour, label=None):
    """LED pointing right: anode at x, cathode at x + 34."""
    svg.path(f"M{x},{y - 10} L{x + 24},{y} L{x},{y + 10} Z", colour=INK, width=1.6, fill=colour)
    svg.line([(x + 24, y - 11), (x + 24, y + 11)], width=2.2)
    svg.line([(x + 24, y), (x + 34, y)], width=2)
    for dx in (6, 14):  # light arrows
        svg.line([(x + dx, y - 13), (x + dx + 8, y - 21)], width=1.3, arrow="ink")
    if label:
        svg.text(x + 12, y + 26, label, size=11, anchor="middle", fill=MUTED)


def flag(svg, x, y, label, pointing):
    """Net label: wires with the same flag are connected."""
    w = 46
    if pointing == "left":
        svg.path(f"M{x},{y} L{x - 10},{y - 10} L{x - w},{y - 10} L{x - w},{y + 10} L{x - 10},{y + 10} Z",
                 colour=RAIL_3V3, width=1.6, fill="#fff3e6")
        svg.text(x - w / 2 - 4, y + 4, label, size=11.5, anchor="middle", weight=700, fill=RAIL_3V3)
    else:
        svg.path(f"M{x},{y} L{x + 10},{y - 10} L{x + w},{y - 10} L{x + w},{y + 10} L{x + 10},{y + 10} Z",
                 colour=RAIL_3V3, width=1.6, fill="#fff3e6")
        svg.text(x + w / 2 + 4, y + 4, label, size=11.5, anchor="middle", weight=700, fill=RAIL_3V3)


def circuit():
    svg = Svg(1180, 800)
    svg.text(30, 42, "SpellWand: circuit (mpu9250 branch)", size=22, weight=700)
    svg.text(30, 64, "ESP32 dev board, MPU-9250/6500 IMU, RGB status LED, cast button, optional action LED, "
             "4× AAA with a slide switch.", size=13, fill=MUTED)

    # ESP32 board with its pins
    ex, ey, ew, eh = 440, 104, 240, 580
    svg.rect(ex, ey, ew, eh, "#f4f6fb", INK, rx=10, width=2)
    svg.text(ex + ew / 2, ey + 32, "ESP32-WROOM-32", size=15, anchor="middle", weight=700)
    svg.text(ex + ew / 2, ey + 50, "dev board (1117 regulator)", size=11.5, anchor="middle", fill=MUTED)
    left_pins = {"5V / VIN": 210, "GND": 300, "3V3": 390}
    right_pins = {"GPIO21 (SDA)": 168, "GPIO22 (SCL)": 208, "GPIO18": 350, "GPIO19": 390, "GPIO23": 430,
                  "GPIO27": 530, "GPIO26": 630}
    for name, yy in left_pins.items():
        svg.line([(ex - 20, yy), (ex, yy)], width=2)
        svg.circle(ex - 20, yy, 3.5, INK)
        svg.text(ex + 12, yy + 4, name, size=12.5, weight=600)
    for name, yy in right_pins.items():
        svg.line([(ex + ew, yy), (ex + ew + 20, yy)], width=2)
        svg.circle(ex + ew + 20, yy, 3.5, INK)
        svg.text(ex + ew - 12, yy + 4, name, size=12.5, anchor="end", weight=600)

    # Batteries, slide switch, 5V/VIN
    bx = 120
    svg.text(40, 196, "BT1", size=12.5, weight=700)
    svg.lines(40, 214, ["4× AAA", "≈ 6 V"], size=11.5, gap=16, fill=MUTED)
    svg.line([(bx, 280), (bx, 210), (226, 210)], colour=POWER, width=2.4)
    for cy in (300, 352):  # two cell symbols stand for the four cells
        svg.line([(bx - 18, cy), (bx + 18, cy)], width=2.4)
        svg.line([(bx - 9, cy + 9), (bx + 9, cy + 9)], width=4)
    svg.line([(bx, 280), (bx, 300)], width=2)
    svg.line([(bx, 309), (bx, 352)], width=2, dash="3 4")
    svg.line([(bx, 361), (bx, 470), (320, 470), (320, 300), (418, 300)], colour=INK, width=2.4)
    svg.text(bx + 24, 296, "+", size=15, weight=700, fill=POWER)
    svg.text(bx + 24, 376, "−", size=15, weight=700)
    ground(svg, 320, 470)

    svg.circle(230, 210, 4, WHITE, stroke=INK, width=2)
    svg.circle(290, 210, 4, WHITE, stroke=INK, width=2)
    svg.line([(233, 207), (284, 190)], width=2.2)
    svg.text(260, 180, "SW1 slide switch", size=11.5, anchor="middle", weight=600)
    svg.text(260, 236, "on / off", size=11, anchor="middle", fill=MUTED)
    svg.line([(294, 210), (418, 210)], colour=POWER, width=2.4)

    # 3V3 rail out of the board
    svg.line([(418, 390), (396, 390)], colour=RAIL_3V3, width=2.2)
    flag(svg, 396, 390, "3V3", "left")

    # IMU
    ix, iy = 860, 124
    svg.rect(ix, iy, 220, 176, "#eef7f8", I2C, rx=8, width=2)
    svg.text(ix + 110, iy + 24, "MPU-9250 / 6500", size=14, anchor="middle", weight=700)
    for name, yy in {"SDA": 168, "SCL": 208, "VCC": 240, "GND": 266}.items():
        svg.line([(ix - 14, yy), (ix, yy)], width=2)
        svg.text(ix + 10, yy + 4, name, size=12, weight=600)
    svg.lines(ix + 66, 196, ["AD0, NCS, FSYNC,", "INT: leave open", "(address 0x68)"], size=11, gap=15,
              fill=MUTED)
    svg.text(ix + 110, iy + 164, "mount: x axis → wand tip", size=11, anchor="middle", fill=MUTED)
    svg.line([(702, 168), (846, 168)], colour=I2C, width=2.2)
    svg.line([(702, 208), (846, 208)], colour=I2C, width=2.2)
    svg.text(774, 160, "SDA", size=11.5, anchor="middle", fill=I2C, weight=700)
    svg.text(774, 200, "SCL", size=11.5, anchor="middle", fill=I2C, weight=700)
    svg.line([(846, 240), (812, 240)], colour=RAIL_3V3, width=2.2)
    flag(svg, 812, 240, "3V3", "left")
    svg.line([(846, 266), (830, 266), (830, 276)], width=2)
    ground(svg, 830, 276)

    # RGB status LED (common cathode)
    svg.rect(800, 322, 158, 128, "none", "#8a8fa0", rx=8, dash="5 4", width=1.3)
    svg.lines(970, 372, ["D1: 4-leg", "RGB LED", "(common", "cathode)"], size=11.5, gap=16, weight=600)
    for yy, name, value, colour, legname in [(350, "R1", "220 Ω", "#e53935", "red"),
                                              (390, "R2", "100 Ω", "#2e9d4f", "green"),
                                              (430, "R3", "100 Ω", "#2f55ff", "blue")]:
        svg.line([(702, yy), (716, yy)], colour=SIGNAL, width=2)
        resistor(svg, 716, yy, 64, name, value)
        svg.line([(780, yy), (836, yy)], colour=SIGNAL, width=2)
        led(svg, 836, yy, colour)
        svg.line([(870, yy), (930, yy)], width=2)
        svg.text(818, yy + 16, legname, size=10.5, fill=MUTED, anchor="middle")
    svg.line([(930, 350), (930, 462)], width=2)
    svg.text(948, 470, "long leg", size=10.5, fill=MUTED)
    ground(svg, 930, 462)

    # CAST_BUTTON
    by = 530
    svg.line([(702, by), (826, by)], colour=SIGNAL, width=2)
    svg.circle(830, by, 4, WHITE, stroke=INK, width=2)
    svg.circle(874, by, 4, WHITE, stroke=INK, width=2)
    svg.line([(822, by - 12), (882, by - 12)], width=2.2)
    svg.line([(852, by - 12), (852, by - 24)], width=2)
    svg.line([(844, by - 24), (860, by - 24)], width=2)
    svg.line([(878, by), (930, by), (930, by + 12)], width=2)
    ground(svg, 930, by + 12)
    svg.text(852, by - 34, "SW2: CAST_BUTTON", size=11.5, anchor="middle", weight=600)
    svg.text(708, by + 22, "uses the ESP32's internal pull-up", size=10.5, fill=MUTED)

    # Optional action LED
    ay = 630
    svg.rect(708, ay - 34, 260, 88, "none", "#8a8fa0", rx=8, dash="5 4", width=1.3)
    svg.text(838, ay - 40, "Optional: action LED (EXECUTE_ACTION demo)", size=11.5, anchor="middle", weight=600)
    svg.line([(702, ay), (716, ay)], colour=SIGNAL, width=2)
    resistor(svg, 716, ay, 64, "R4", "330 Ω")
    svg.line([(780, ay), (836, ay)], colour=SIGNAL, width=2)
    led(svg, 836, ay, "#f2b705")
    svg.line([(870, ay), (930, ay), (930, ay + 14)], width=2)
    ground(svg, 930, ay + 14)
    svg.text(818, ay + 28, "long leg → R4", size=10.5, anchor="middle", fill=MUTED)

    # Notes
    svg.rect(30, 530, 380, 240, "#fafafc", "#d0d3dc", rx=10)
    svg.text(46, 556, "Notes", size=13.5, weight=700)
    svg.lines(46, 582, [
        "Batteries (≈ 6 V) go into 5V / VIN, never 3V3;",
        "the board's 1117 regulator makes the 3.3 V.",
        "Switch the batteries off while USB is plugged in.",
        "Check + and − before switching on.",
        "All ground symbols are one wire: battery −,",
        "ESP32 GND and every part's ground.",
        "Both 3V3 flags are the same wire.",
        "Common-anode RGB LED: long leg to 3V3, and set",
        "STATUS_LED_COMMON_ANODE = true in main.cpp.",
    ], size=12, gap=19)

    # Wire colour key
    kx, ky = 712, 740
    svg.text(kx, ky - 22, "Wire colours (only in this drawing)", size=11.5, weight=700)
    for i, (colour, label) in enumerate([(POWER, "battery +"), (RAIL_3V3, "3.3 V"), (INK, "ground"),
                                          (I2C, "I²C"), (SIGNAL, "GPIO signals")]):
        xx = kx + (i % 3) * 150
        yy = ky + (i // 3) * 26
        svg.line([(xx, yy), (xx + 26, yy)], colour=colour, width=3)
        svg.text(xx + 34, yy + 4, label, size=11.5)
    return svg.save_with_size("circuit", "SpellWand circuit")


def to_png(svg_path, width, height, pixels=2400):
    """PNG copy using macOS Quick Look (qlmanage) and sips, if available.
    Quick Look renders into a square, so the drawing is centred on a square canvas
    first and the PNG is cropped back to the drawing's own shape afterwards."""
    if not (shutil.which("qlmanage") and shutil.which("sips")):
        return None
    side = max(width, height)
    inner = svg_path.read_text(encoding="utf-8")
    inner = inner.replace("<svg ", f'<svg x="{(side - width) / 2}" y="{(side - height) / 2}" ', 1)
    square = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" '
              f'viewBox="0 0 {side} {side}"><rect width="100%" height="100%" fill="#ffffff"/>{inner}</svg>')
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / svg_path.name
        source.write_text(square, encoding="utf-8")
        subprocess.run(["qlmanage", "-t", "-s", str(pixels), "-o", tmp, str(source)],
                       check=True, capture_output=True)
        made = Path(tmp) / (svg_path.name + ".png")
        if not made.exists():
            return None
        crop_w = round(pixels * width / side)
        crop_h = round(pixels * height / side)
        subprocess.run(["sips", "--cropToHeightWidth", str(crop_h), str(crop_w), str(made)],
                       check=True, capture_output=True)
        target = svg_path.with_suffix(".png")
        shutil.move(str(made), target)
        return target


if __name__ == "__main__":
    for make in (code_flowchart, wand_states, classifier_pipeline, circuit):
        path, width, height = make()
        png = to_png(path, width, height)
        print(f"wrote {path.name}" + (f" and {png.name}" if png else ""))
