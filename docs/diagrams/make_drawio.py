"""Writes the code flowchart and the circuit as editable draw.io files.

    python3 docs/diagrams/make_drawio.py

This overwrites any edits made in draw.io. Open the .drawio files at https://app.diagrams.net
or in the draw.io desktop app, and use File > Export as > PNG to update the pictures.
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

# Circuit colours: dark, with large labels, to read well on a slide.
BACKGROUND = "#11112b"
PANEL = "#1b1b3f"
BORDER = "#f2c94c"
LABEL = "#f4f4fb"
WIRE = "#b9b9d6"
POWER = "#f2917a"

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
    def __init__(self, page_name, width, height, background=None):
        self.page_name, self.width, self.height, self.background = page_name, width, height, background
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
                 f'pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0"'
                 + (f' background="{self.background}"' if self.background else "") + ">"
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
    controller = d.vertex("controller.py: for each message from the wand", 830, 362, 380, 712,
             container + f"strokeColor={MAC[1]};fontColor={MAC[1]};")

    pill = "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fontStyle=1;fontSize=13;"
    # --- wand column ---
    wx, ww = 50, 340
    power = d.vertex("Power on (slide switch)", 105, 156, 230, 36, pill + f"fillColor={WAND[0]};strokeColor={WAND[1]};")
    setup, _ = step(d, wx, 212, ww, "setup()", [
        "Serial, CAST_BUTTON pull-up, RGB LED PWM",
        "Find the IMU at 0x4B / 0x4A, reset it (RST)",
        "Take every report with our own handler",
        "Turn on 100 Hz accelerometer + gyro reports",
        'Start BLE, advertise "SpellWand"'], WAND)
    flow_arrow(d, power, setup)
    read, read_h = step(d, wx, 402, ww, "Read the IMU (when INT goes low)", [
        "each gyro report + newest accel = one reading;",
        "m/s² and rad/s; the IMU removes its gyro offset"], WAND)
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
    flow_arrow(d, startup, controller, style_extra=anchor("exit", 0.5, 1) + anchor("entry", 0.5, 0))
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
    flow_arrow(d, training, recorder, style_extra=anchor("exit", 1, 0.5) + anchor("entry", 0, 0.4865))
    d.text("yes", 1040, 598, 34, 18, size=11.5, colour=MUTED, align="center")
    classify, _ = step(d, mx, 676, mw, "Gesture Classifier (classifier.py)", [
        "GestureResult: label or UNKNOWN, distance,",
        "nearest gesture"], MAC)
    flow_arrow(d, training, classify, style_extra=anchor("exit", 0.5, 1) + anchor("entry", 0.2647, 0))
    d.text("no", 948, 654, 30, 18, size=11.5, colour=MUTED)
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
    flow_arrow(d, has_action, action)
    d.text("yes", 1028, 984, 34, 18, size=11.5, colour=MUTED)
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
    d = Drawio("Circuit", 1180, 720, background=BACKGROUND)

    def label(value, x, y, w=220, size=20, colour=LABEL, bold=False, align="left"):
        d.text(value, x, y - 15, w, 30, size=size, colour=colour, bold=bold, align=align)

    def symbol(kind, x, y, w, h, extra=""):
        return part(d, kind, "", x, y, w, h, label_on="none", extra=f"strokeColor={WIRE};strokeWidth=2;fillColor=none;" + extra)

    def ground(x, y):
        return symbol(GROUND, x - 15, y, 30, 20)

    board = ("rounded=1;arcSize=5;whiteSpace=wrap;html=1;verticalAlign=top;spacingTop=14;"
             f"fillColor={PANEL};strokeColor={BORDER};strokeWidth=2.5;fontColor={LABEL};fontSize=25;fontStyle=1;")

    # ESP32 board; wires attach at the pin heights
    ex, ey, ew, eh = 300, 30, 330, 660
    esp = d.vertex("ESP32-WROOM-32", ex, ey, ew, eh, board)

    def pin(y, side):
        return (0 if side == "left" else 1, round((y - ey) / eh, 4))

    for name, y in {"5V / VIN": 250, "GND": 560}.items():
        label(name, ex + 16, y)
    for name, y in {"GPIO21 (SDA)": 115, "GPIO22 (SCL)": 160, "GPIO4 (INT)": 205, "GPIO26 (RST)": 250, "3V3": 295,
                    "GPIO18": 470, "GPIO19": 525, "GPIO23": 580, "GPIO27": 645}.items():
        label(name, ex + ew - 236, y, align="right")

    # Batteries and on/off switch
    battery = symbol(BATTERY, 50, 400, 100, 60, f"strokeColor={LABEL};")
    switch = symbol(SWITCH, 195, 250 - 0.8 * 20, 75, 20)
    wire(d, battery, switch, POWER, exit_at=(1, 0.5), entry_at=(0, 0.8), points=[(175, 430), (175, 250)])
    wire(d, switch, esp, POWER, exit_at=(1, 0.8), entry_at=pin(250, "left"))
    battery_ground = ground(170, 590)
    wire(d, battery, battery_ground, WIRE, exit_at=(0, 0.5), entry_at=(0.5, 0),
         points=[(30, 430), (30, 560), (170, 560)])
    wire(d, esp, battery_ground, WIRE, exit_at=pin(560, "left"), entry_at=(0.5, 0), points=[(170, 560)])
    label("On/off switch", 130, 205, w=170, colour=WIRE, align="center")
    label("4 × AAA", 50, 482, w=130, size=22, bold=True)
    label("≈ 6 V", 50, 512, w=130, colour=WIRE)
    label("+", 150, 400, w=24, size=24, colour=POWER, bold=True)
    label("−", 30, 400, w=24, size=24, colour=WIRE, bold=True)

    # IMU
    ix, iy, iw, ih = 880, 30, 250, 385
    imu = d.vertex("BNO080 / BNO085", ix, iy, iw, ih, board)
    imu_pins = {"SDA": 115, "SCL": 160, "INT": 205, "RST": 250, "VCC": 295, "GND": 330, "PS0": 360, "PS1": 390}
    for name, y in imu_pins.items():
        label(name, ix + 16, y, w=90)

    def imu_pin(name):
        return (0, round((imu_pins[name] - iy) / ih, 4))

    for y, name in [(115, "SDA"), (160, "SCL"), (205, "INT"), (250, "RST")]:
        wire(d, esp, imu, WIRE, exit_at=pin(y, "right"), entry_at=imu_pin(name))
    wire(d, esp, imu, POWER, exit_at=pin(295, "right"), entry_at=imu_pin("VCC"))
    label("I²C bus", 655, 90, w=200, colour=WIRE, align="center")
    label("3.3 V", 655, 275, w=200, colour=POWER, align="center")
    imu_ground = ground(850, 420)
    for name in ("GND", "PS0", "PS1"):
        wire(d, imu, imu_ground, WIRE, exit_at=imu_pin(name), entry_at=(0.5, 0), points=[(850, imu_pins[name])])

    # RGB LED (common cathode)
    led_ground = ground(960, 615)
    for y, value, colour in [(470, "220 Ω", "#ee5a52"), (525, "100 Ω", "#5cc26f"), (580, "100 Ω", "#4f74f7")]:
        resistor = symbol(RESISTOR, 690, y - 8, 80, 16)
        led = symbol(LED, 830, y - 0.5385 * 32, 50, 32, f"fillColor={colour};")
        wire(d, esp, resistor, WIRE, exit_at=pin(y, "right"), entry_at=(0, 0.5))
        wire(d, resistor, led, WIRE, exit_at=(1, 0.5), entry_at=(0, LED[1]))
        wire(d, led, led_ground, WIRE, exit_at=(1, LED[1]), entry_at=(0.5, 0), points=[(960, y)])
        label(value, 680, y - 22, w=100, size=17, colour=WIRE, align="center")
    label("RGB LED", 985, 500, w=180, size=22, bold=True)
    label("common cathode", 985, 532, w=180, size=17, colour=WIRE)

    # Cast button
    button = symbol(BUTTON, 760, 645 - 0.8 * 16, 70, 16)
    wire(d, esp, button, WIRE, exit_at=pin(645, "right"), entry_at=(0, 0.8))
    button_ground = ground(880, 660)
    wire(d, button, button_ground, WIRE, exit_at=(1, 0.8), entry_at=(0.5, 0), points=[(880, 645)])
    label("Cast button", 985, 650, w=180, size=22, bold=True)

    d.text("All ground symbols connect to the ESP32's GND.", 30, 640, 250, 44, size=14, colour=WIRE)
    return d.save("circuit")


if __name__ == "__main__":
    for make in (code_flowchart, circuit):
        print(f"wrote {make().name}")
