"""Writes editable draw.io versions of the code flowchart and the circuit.

    python3 docs/diagrams/make_drawio.py

Open the .drawio files at https://app.diagrams.net or in the draw.io desktop app.
Arrows and wires are real connectors: they stay attached when you move boxes and parts.
The circuit uses draw.io's built-in electrical symbols (More shapes -> Electrical).
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent

INK = "#1f2430"
MUTED = "#5b6070"
WAND = ("#e8eeff", "#3d5bd9")
MAC = ("#e6f5ec", "#2f8f55")
NEUTRAL = ("#f4f5f8", "#8a8fa0")
TO_MAC = "#d9822b"
TO_WAND = "#7b4fd6"

POWER = "#d32f2f"
RAIL_3V3 = "#ef6c00"
SIGNAL = "#1e3a8a"
I2C = "#00838f"

ELECTRICAL = "pointerEvents=1;shadow=0;dashed=0;html=1;"
# Connection points of draw.io's electrical symbols, read from draw.io itself.
RESISTOR = ("shape=mxgraph.electrical.resistors.resistor_2;", 0.5)
LED = ("shape=mxgraph.electrical.opto_electronics.led_1;", 0.5385)
SWITCH = ("shape=mxgraph.electrical.electro-mechanical.singleSwitch;aspect=fixed;elSwitchState=off;", 0.8)
BUTTON = ("shape=mxgraph.electrical.electro-mechanical.pushbutton;aspect=fixed;elSwitchState=off;", 0.8)
BATTERY = ("shape=mxgraph.electrical.miscellaneous.batteryStack;", 0.5)
GROUND = "shape=mxgraph.electrical.signal_sources.signal_ground;"


def attr(value):
    return escape(str(value), {'"': "&quot;"})


class Drawio:
    def __init__(self, page_name, width, height):
        self.page_name, self.width, self.height = page_name, width, height
        self.cells = []
        self.next_id = 2

    def _id(self):
        self.next_id += 1
        return f"c{self.next_id}"

    def vertex(self, value, x, y, w, h, style):
        cid = self._id()
        self.cells.append(f'<mxCell id="{cid}" value="{attr(value)}" style="{attr(style)}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def text(self, value, x, y, w, h, size=13, colour=INK, bold=False, italic=False, align="left"):
        style = (f"text;html=1;whiteSpace=wrap;align={align};verticalAlign=middle;fontSize={size};"
                 f"fontColor={colour};fontStyle={(1 if bold else 0) + (2 if italic else 0)};")
        return self.vertex(value, x, y, w, h, style)

    def edge(self, source, target, style, value="", points=(), label_at=None, label_offset=(0, 0),
             source_point=None, target_point=None):
        """label_at: position along the edge, -1 (source end) to 1 (target end)."""
        cid = self._id()
        ends = (f' source="{source}"' if source else "") + (f' target="{target}"' if target else "")
        geometry_x = f' x="{label_at}"' if label_at is not None else ""
        inner = ""
        if source_point:
            inner += f'<mxPoint x="{source_point[0]}" y="{source_point[1]}" as="sourcePoint"/>'
        if target_point:
            inner += f'<mxPoint x="{target_point[0]}" y="{target_point[1]}" as="targetPoint"/>'
        if points:
            inner += '<Array as="points">' + "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points) + "</Array>"
        if label_offset != (0, 0):
            inner += f'<mxPoint x="{label_offset[0]}" y="{label_offset[1]}" as="offset"/>'
        self.cells.append(f'<mxCell id="{cid}" value="{attr(value)}" style="{attr(style)}" edge="1" parent="1"{ends}>'
                          f'<mxGeometry{geometry_x} relative="1" as="geometry">{inner}</mxGeometry></mxCell>')
        return cid

    def save(self, name):
        model = (f'<mxGraphModel dx="{self.width}" dy="{self.height}" grid="1" gridSize="10" guides="1" '
                 f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
                 f'pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0">'
                 '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(self.cells) +
                 "</root></mxGraphModel>")
        xml = (f'<mxfile host="SpellWand make_drawio.py"><diagram id="{name}" name="{attr(self.page_name)}">'
               f"{model}</diagram></mxfile>\n")
        path = OUT / f"{name}.drawio"
        path.write_text(xml, encoding="utf-8")
        return path


def anchor(prefix, x, y):
    """Fixed connection point on a shape, as fractions of its width and height."""
    return f"{prefix}X={x};{prefix}Y={y};{prefix}Dx=0;{prefix}Dy=0;{prefix}Perimeter=0;"


def path_length(points):
    return sum(abs(x2 - x1) + abs(y2 - y1) for (x1, y1), (x2, y2) in zip(points, points[1:]))


def label_position(points, distance):
    """Where `distance` px from the source falls, on draw.io's -1..1 scale along the edge."""
    return round(-1 + 2 * distance / path_length(points), 4)


# ---------- code flowchart ----------

def box_style(scheme, size=12.5):
    return (f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor={scheme[0]};strokeColor={scheme[1]};"
            f"align=left;verticalAlign=top;spacingLeft=12;spacingTop=2;fontSize={size};fontColor={INK};")


def step(d, x, y, w, title, items, scheme):
    h = 34 + 18 * len(items) if items else 40
    value = f"<b style='font-size:13.5px'>{escape(title)}</b>" + "".join(f"<br>{escape(s)}" for s in items)
    return d.vertex(value, x, y, w, h, box_style(scheme)), h


def flow_arrow(d, source, target, value="", style_extra=""):
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor={INK};"
             f"strokeWidth=1.5;fontSize=11;fontColor={MUTED};labelBackgroundColor=#ffffff;" + style_extra)
    return d.edge(source, target, style, value)


def code_flowchart():
    d = Drawio("Code flow", 1240, 1180)
    d.text("SpellWand: code flow", 30, 22, 700, 30, size=22, bold=True)
    d.text("What the wand firmware and the Mac app do, and the BLE_LINK messages between them.",
           30, 54, 900, 20, size=13, colour=MUTED)

    def header(x, title, subtitle, scheme):
        value = f"<b style='font-size:14px'>{escape(title)}</b><br><span style='font-size:11px;color:{MUTED}'>{escape(subtitle)}</span>"
        d.vertex(value, x, 92, 380, 46, f"rounded=1;arcSize=10;whiteSpace=wrap;html=1;fillColor={scheme[0]};"
                                         f"strokeColor={scheme[1]};fontColor={INK};")
    header(30, "Wand firmware (ESP32)", "firmware/src/main.cpp + lib/wand_core", WAND)
    header(430, "BLE_LINK messages", "docs/protocol.md", ("#fbf3ea", TO_MAC))
    header(830, "Mac app (Python)", "mac_app/: app.py, controller.py, classifier.py, ...", MAC)

    container = "rounded=1;arcSize=2;dashed=1;fillColor=none;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=14;spacingTop=4;fontStyle=1;fontSize=13.5;"
    d.vertex("loop(): runs continuously", 30, 362, 380, 600, container + f"strokeColor={WAND[1]};fontColor={WAND[1]};")
    d.vertex("controller.py: for each message from the wand", 830, 362, 380, 712,
             container + f"strokeColor={MAC[1]};fontColor={MAC[1]};")

    pill = "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fontStyle=1;fontSize=13;"
    # --- wand column ---
    wx, ww = 50, 340
    power = d.vertex("Power on (slide switch)", 105, 156, 230, 36, pill + f"fillColor={WAND[0]};strokeColor={WAND[1]};")
    setup, _ = step(d, wx, 212, ww, "setup()", [
        "Serial, CAST_BUTTON pull-up, RGB LED PWM",
        "Find the IMU at 0x68 / 0x69, read WHO_AM_I",
        "Set 100 Hz, ±8 g, ±2000 °/s, 45 Hz low-pass",
        "Measure gyro offset (wand still, up to 3 s)",
        'Start BLE, advertise "SpellWand"'], WAND)
    flow_arrow(d, power, setup)
    read, read_h = step(d, wx, 402, ww, "Read the IMU (new reading every 10 ms)", [
        "convert to m/s² and rad/s, subtract gyro offset;",
        "while IDLE, keep re-measuring the offset"], WAND)
    flow_arrow(d, setup, read)
    send, send_h = step(d, wx, 488, ww, "If CASTING: send MOTION_SAMPLE", ["index, time, accel, gyro (19 bytes)"], WAND)
    flow_arrow(d, read, send)
    commands, commands_h = step(d, wx, 560, ww, "Handle commands from the Mac", [
        "START / STOP_RECORDING, GESTURE_RESULT"], WAND)
    flow_arrow(d, send, commands)
    button, button_h = step(d, wx, 648, ww, "Read CAST_BUTTON (debounced 30 ms)", [
        "pressed in IDLE: CAST_START, now CASTING",
        "released: CAST_END, now INFLIGHT (amber)"], WAND)
    flow_arrow(d, commands, button)
    tick, tick_h = step(d, wx, 736, ww, "tick(): time limits", [
        "cast 3 s / recording 5 s: CAST_END",
        "no GESTURE_RESULT within 2 s: magenta flashes"], WAND)
    flow_arrow(d, button, tick)
    leds, leds_h = step(d, wx, 824, ww, "Update STATUS_LED", ["state colour, spell colour, or flashes"], WAND)
    flow_arrow(d, tick, leds)
    loop_y = 824 + leds_h + 22
    d.edge(leds, read, f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor={INK};"
                       f"strokeWidth=1.5;" + anchor("exit", 0.5, 1) + anchor("entry", 0, 0.5),
           points=[(220, loop_y), (40, loop_y), (40, 402 + read_h / 2)])
    d.text("back to the top", 56, loop_y + 8, 160, 20, size=11.5, colour=MUTED, italic=True)
    d.text("States IDLE / CASTING / INFLIGHT in detail: wand_states.svg", 30, 980, 420, 20, size=12,
           colour=MUTED, italic=True)

    # --- Mac column ---
    mx, mw = 850, 340
    start = d.vertex("python3 app.py   (or --simulate)", 875, 156, 290, 36, pill + f"fillColor={MAC[0]};strokeColor={MAC[1]};")
    startup, _ = step(d, mx, 212, mw, "Startup", [
        "Load config.json: threshold, gestures, colours",
        "Load samples from data/, fit the classifier",
        "Connect: BLE Manager (Bleak) or simulated wand",
        "Open the SpellWand UI in the browser",
        "(live updates through server-sent events)"], MAC)
    flow_arrow(d, start, startup)
    decode, decode_h = step(d, mx, 402, mw, "Decode the message (protocol.py)", [], MAC)
    flow_arrow(d, startup, decode)
    depending, _ = step(d, mx, 460, mw, "Depending on the message", [
        "CAST_START: clear the buffer, UI shows Casting…",
        "MOTION_SAMPLE: add to buffer, live charts",
        "CAST_END: continue below"], MAC)
    flow_arrow(d, decode, depending)
    rhombus = "rhombus;whiteSpace=wrap;html=1;fontStyle=1;fontSize=12.5;" + f"fillColor={MAC[0]};strokeColor={MAC[1]};"
    training = d.vertex("Training<br>recording?", 844, 588, 192, 64, rhombus)
    flow_arrow(d, depending, training, style_extra=anchor("exit", 0.2647, 1) + anchor("entry", 0.5, 0))
    recorder = d.vertex("Sample Recorder:<br>≥ 10 samples? save<br>CSV, retrain", 1078, 584, 122, 74,
                        box_style(MAC, size=11.5))
    flow_arrow(d, training, recorder, "yes", anchor("exit", 1, 0.5) + anchor("entry", 0, 0.5))
    classify, _ = step(d, mx, 676, mw, "Gesture Classifier (classifier.py)", [
        "GestureResult: label or UNKNOWN, distance,",
        "nearest gesture (see classifier_pipeline.svg)"], MAC)
    flow_arrow(d, training, classify, "no", anchor("exit", 0.5, 1) + anchor("entry", 0.2647, 0))
    result, result_h = step(d, mx, 764, mw, "Send GESTURE_RESULT", ["label + colour from config.json"], MAC)
    flow_arrow(d, classify, result)
    show, _ = step(d, mx, 834, mw, "Show the result in the UI", ["label, distance, 3D trail, live charts"], MAC)
    flow_arrow(d, result, show)
    has_action = d.vertex("Not UNKNOWN and<br>an action is set?", 900, 920, 240, 64, rhombus)
    flow_arrow(d, show, has_action)
    d.text("no: done", 1146, 942, 70, 20, size=11.5, colour=MUTED)
    action, _ = step(d, mx, 1002, mw, "Action Dispatcher", [
        "Mac notification, or web request",
        "(e.g. a Home Assistant webhook)"], MAC)
    flow_arrow(d, has_action, action, "yes")
    training_ui, training_ui_h = step(d, mx, 1094, mw, "Training buttons in the SpellWand UI",
                                      ["Start recording / Stop and save"], NEUTRAL)

    # --- BLE_LINK messages ---
    bus_a, bus_b = 600, 660
    message = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeWidth=2;"
               "fontSize=11;fontStyle=1;labelBackgroundColor=#ffffff;")
    decode_y = 402 + decode_h / 2
    for source, top, height, line_y, label in [
        (send, 488, send_h, 488 + send_h / 2, "MOTION_SAMPLE ×N (≈100/s)"),
        (button, 648, button_h, 648 + button_h / 2, "CAST_START / CAST_END"),
        (tick, 736, tick_h, 736 + tick_h / 2, "CAST_END (time limit)"),
    ]:
        pts = [(390, line_y), (bus_a, line_y), (bus_a, decode_y), (850, decode_y)]
        d.edge(source, decode, message + f"strokeColor={TO_MAC};fontColor={TO_MAC};"
               + anchor("exit", 1, round((line_y - top) / height, 4)) + anchor("entry", 0, 0.5),
               value=label, points=pts[1:3], label_at=label_position(pts, 105), label_offset=(0, -11))
    d.text("to the Mac (BLE notify)", 612, decode_y - 22, 200, 18, size=11.5, colour=TO_MAC, italic=True)

    command_in_y = 560 + commands_h - 14
    for source, top, height, line_y, label in [
        (result, 764, result_h, 764 + result_h / 2, "GESTURE_RESULT"),
        (training_ui, 1094, training_ui_h, 1094 + training_ui_h / 2, "START_ / STOP_RECORDING"),
    ]:
        pts = [(850, line_y), (bus_b, line_y), (bus_b, command_in_y), (390, command_in_y)]
        d.edge(source, commands, message + f"strokeColor={TO_WAND};fontColor={TO_WAND};jumpStyle=arc;jumpSize=12;"
               + anchor("exit", 0, round((line_y - top) / height, 4))
               + anchor("entry", 1, round((command_in_y - 560) / commands_h, 4)),
               value=label, points=pts[1:3], label_at=label_position(pts, 95), label_offset=(0, -11))
    d.text("to the wand (BLE write)", 412, command_in_y + 8, 160, 18, size=11.5, colour=TO_WAND, italic=True)
    return d.save("code_flowchart")


# ---------- circuit ----------

def wire(d, source, target, colour, exit_at=None, entry_at=None, points=()):
    style = (f"endArrow=none;html=1;rounded=0;edgeStyle=orthogonalEdgeStyle;strokeWidth=2;strokeColor={colour};")
    if exit_at:
        style += anchor("exit", *exit_at)
    if entry_at:
        style += anchor("entry", *entry_at)
    return d.edge(source, target, style, points=points)


def part(d, kind, value, x, y, w, h, label_on="bottom", extra=""):
    shape = kind[0] if isinstance(kind, tuple) else kind
    if label_on == "top":
        place = "verticalLabelPosition=top;verticalAlign=bottom;"
    elif label_on == "none":
        place = "noLabel=1;"
    else:
        place = "verticalLabelPosition=bottom;verticalAlign=top;"
    return d.vertex(value, x, y, w, h, ELECTRICAL + place + "fontSize=11;fontStyle=1;" + shape + extra)


def ground_at(d, x, y):
    """Ground symbol whose connection point (top centre) is at (x, y)."""
    return part(d, GROUND, "", x - 15, y, 30, 20, label_on="none")


def circuit():
    d = Drawio("Circuit", 1180, 800)
    d.text("SpellWand: circuit (mpu9250 branch)", 30, 22, 700, 30, size=22, bold=True)
    d.text("ESP32 dev board, MPU-9250/6500 IMU, RGB status LED, cast button, "
           "4× AAA with a slide switch.", 30, 52, 1000, 20, size=13, colour=MUTED)

    # ESP32 board; wires attach at the pin heights
    ex, ey, ew, eh = 440, 104, 240, 480
    esp = d.vertex("<b style='font-size:15px'>ESP32-WROOM-32</b><br><span style='color:#5b6070'>dev board (1117 regulator)</span>",
                   ex, ey, ew, eh, "rounded=1;arcSize=3;whiteSpace=wrap;html=1;verticalAlign=top;spacingTop=10;"
                                   "fillColor=#f4f6fb;strokeColor=#1f2430;strokeWidth=2;fontSize=12;")

    def pin(y, side):
        return (0 if side == "left" else 1, round((y - ey) / eh, 4))

    left = {"5V / VIN": 210, "GND": 300, "3V3": 390}
    right = {"GPIO21 (SDA)": 168, "GPIO22 (SCL)": 208, "GPIO18": 350, "GPIO19": 390, "GPIO23": 430,
             "GPIO27": 530}
    for name, y in left.items():
        d.text(name, ex + 10, y - 10, 110, 20, size=12.5, bold=True)
    for name, y in right.items():
        d.text(name, ex + ew - 130, y - 10, 120, 20, size=12.5, bold=True, align="right")

    # Batteries and slide switch
    battery = part(d, BATTERY, "BT1: 4× AAA (≈ 6 V)", 70, 370, 100, 60)
    switch = part(d, SWITCH, "SW1 slide switch", 222, 194, 75, 20, label_on="top")
    wire(d, battery, switch, POWER, exit_at=(1, 0.5), entry_at=(0, 0.8), points=[(190, 400), (190, 210)])
    wire(d, switch, esp, POWER, exit_at=(1, 0.8), entry_at=pin(210, "left"))
    battery_ground = ground_at(d, 320, 480)
    wire(d, battery, battery_ground, INK, exit_at=(0, 0.5), entry_at=(0.5, 0), points=[(50, 400), (50, 460), (320, 460)])
    wire(d, battery_ground, esp, INK, exit_at=(0.5, 0), entry_at=pin(300, "left"), points=[(320, 300)])
    d.text("+", 172, 372, 14, 16, size=15, colour=POWER, bold=True)
    d.text("−", 56, 372, 14, 16, size=15, bold=True)

    flag_style = (f"rounded=1;arcSize=20;whiteSpace=wrap;html=1;fillColor=#fff3e6;strokeColor={RAIL_3V3};"
                  f"fontColor={RAIL_3V3};fontStyle=1;fontSize=11.5;")
    flag_left = d.vertex("3V3", 340, 380, 46, 20, flag_style)
    wire(d, esp, flag_left, RAIL_3V3, exit_at=pin(390, "left"), entry_at=(1, 0.5))

    # IMU
    ix, iy, iw, ih = 860, 124, 220, 176
    imu = d.vertex("<b style='font-size:14px'>MPU-9250 / 6500</b>", ix, iy, iw, ih,
                   f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;verticalAlign=top;spacingTop=6;"
                   f"fillColor=#eef7f8;strokeColor={I2C};strokeWidth=2;")
    imu_pins = {"SDA": 168, "SCL": 208, "VCC": 240, "GND": 266}
    for name, y in imu_pins.items():
        d.text(name, ix + 8, y - 10, 50, 20, size=12, bold=True)
    d.text("AD0, NCS, FSYNC,<br>INT: leave open<br>(address 0x68)", ix + 64, 186, 150, 52, size=11, colour=MUTED)
    d.text("mount: x axis → wand tip", ix, iy + ih - 26, iw, 20, size=11, colour=MUTED, align="center")

    def imu_pin(name):
        return (0, round((imu_pins[name] - iy) / ih, 4))

    wire(d, esp, imu, I2C, exit_at=pin(168, "right"), entry_at=imu_pin("SDA"))
    wire(d, esp, imu, I2C, exit_at=pin(208, "right"), entry_at=imu_pin("SCL"))
    d.text("SDA", 750, 148, 50, 18, size=11.5, colour=I2C, bold=True, align="center")
    d.text("SCL", 750, 188, 50, 18, size=11.5, colour=I2C, bold=True, align="center")
    flag_imu = d.vertex("3V3", 780, 230, 46, 20, flag_style)
    wire(d, flag_imu, imu, RAIL_3V3, exit_at=(1, 0.5), entry_at=imu_pin("VCC"))
    imu_ground = ground_at(d, 830, 290)
    wire(d, imu, imu_ground, INK, exit_at=imu_pin("GND"), entry_at=(0.5, 0), points=[(830, 266)])

    # RGB status LED (common cathode)
    d.vertex("", 800, 318, 158, 136, "rounded=1;arcSize=6;dashed=1;fillColor=none;strokeColor=#8a8fa0;")
    d.text("D1: 4-leg RGB LED<br>(common cathode)", 968, 332, 200, 36, size=11.5, bold=True)
    d.text("Legs, typically:<br>red, common (longest),<br>green, blue", 968, 372, 200, 52, size=11,
           colour=MUTED)
    rgb_ground = ground_at(d, 930, 470)
    for y, name, colour in [(350, "R1 220 Ω", "#e53935"), (390, "R2 100 Ω", "#2e9d4f"), (430, "R3 100 Ω", "#2f55ff")]:
        resistor = part(d, RESISTOR, name, 716, y - 7, 64, 14, label_on="top")
        led = part(d, LED, "", 836, y - 0.5385 * 32, 50, 32, label_on="none", extra=f"fillColor={colour};")
        wire(d, esp, resistor, SIGNAL, exit_at=pin(y, "right"), entry_at=(0, 0.5))
        wire(d, resistor, led, SIGNAL, exit_at=(1, 0.5), entry_at=(0, LED[1]))
        wire(d, led, rgb_ground, INK, exit_at=(1, LED[1]), entry_at=(0.5, 0), points=[(930, y)])
    d.text("common leg (longest)", 944, 456, 140, 16, size=10.5, colour=MUTED)

    # CAST_BUTTON
    button = part(d, BUTTON, "SW2: CAST_BUTTON", 826, 530 - 0.8 * 16, 60, 16, label_on="top")
    wire(d, esp, button, SIGNAL, exit_at=pin(530, "right"), entry_at=(0, 0.8))
    button_ground = ground_at(d, 930, 546)
    wire(d, button, button_ground, INK, exit_at=(1, 0.8), entry_at=(0.5, 0), points=[(930, 530)])
    d.text("uses the ESP32's internal pull-up", 706, 540, 200, 16, size=10.5, colour=MUTED)

    # Notes
    notes = "<br>".join([
        "<b style='font-size:13.5px'>Notes</b>",
        "Batteries (≈ 6 V) go into 5V / VIN, never 3V3;",
        "the board's 1117 regulator makes the 3.3 V.",
        "Switch the batteries off while USB is plugged in.",
        "Check + and − before switching on.",
        "All ground symbols are one wire: battery −,",
        "ESP32 GND and every part's ground.",
        "Both 3V3 flags are the same wire.",
        "Common-anode RGB LED: long leg to 3V3, and set",
        "STATUS_LED_COMMON_ANODE = true in main.cpp.",
    ])
    d.vertex(notes, 30, 530, 380, 240, "rounded=1;arcSize=4;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
                                       "spacingLeft=14;spacingTop=8;fillColor=#fafafc;strokeColor=#d0d3dc;fontSize=12;")

    # Wire colour key
    d.text("Wire colours (only in this drawing)", 712, 704, 300, 18, size=11.5, bold=True)
    for i, (colour, label) in enumerate([(POWER, "battery +"), (RAIL_3V3, "3.3 V"), (INK, "ground"),
                                          (I2C, "I²C"), (SIGNAL, "GPIO signals")]):
        x = 712 + (i % 3) * 150
        y = 740 + (i // 3) * 26
        d.edge(None, None, f"endArrow=none;html=1;strokeWidth=3;strokeColor={colour};",
               source_point=(x, y), target_point=(x + 26, y))
        d.text(label, x + 34, y - 9, 110, 18, size=11.5)
    return d.save("circuit")


if __name__ == "__main__":
    for make in (code_flowchart, circuit):
        print(f"wrote {make().name}")
