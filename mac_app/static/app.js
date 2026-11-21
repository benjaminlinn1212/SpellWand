// SpellWand UI: talks to app.py's JSON API and listens to its live event stream.

const AXES = ["x (along wand)", "y (left)", "z (up)"];
const CHART_FONT = "Archivo, 'Helvetica Neue', Arial, sans-serif";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// A double-click on a zoomed chart zooms back out. Plotly's own limit of 0.3 s between the two
// presses is shorter than an ordinary double-click, so it is raised to the Mac's usual 0.5 s.
const plotConfig = { displayModeBar: false, responsive: true, doubleClickDelay: 500 };
const SIGNAL_CHARTS = ["accel-chart", "gyro-chart"];

const state = {
  status: null, config: null, meta: null, samples: [], checks: {},
  liveStart: null, liveTrail: null,
  trail: null,  // what the 3D view shows: { trace, color, box }, so it can be redrawn in another theme
  resultShown: false,
};
const $ = (id) => document.getElementById(id);

// ---------- theme ----------
// The colours are defined in style.css. Charts cannot use CSS variables, so their colours are
// read from there, and the charts are redrawn when the theme changes.

function readInk() {
  const css = getComputedStyle(document.documentElement);
  const value = (name) => css.getPropertyValue(name).trim();
  return {
    text: value("--ink"),
    soft: value("--ink-soft"),
    line: value("--line"),
    strong: value("--line-strong"),
    surface: value("--surface"),
    series: [value("--series-x"), value("--series-y"), value("--series-z")],
    // the motion view
    stage: value("--stage"),
    stageWall: value("--stage-wall"),
    stageLine: value("--stage-line"),
    stageZero: value("--stage-zero"),
    stageText: value("--stage-text"),
    stageLight: value("--stage-light"),
  };
}
let ink = readInk();

// The theme switch is shared (shared.js). When the theme changes, the charts are redrawn in
// its colours.
function wireTheme() {
  Shared.onThemeChange(() => {
    ink = readInk();
    redrawCharts();
  });
}

// ---------- helpers ----------

async function api(method, url, body) {
  const options = { method, headers: {} };
  if (method !== "GET") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body ?? {});
  }
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.includes("-")) node.setAttribute(key, value);  // e.g. aria-label is an attribute
    else node[key] = value;
  }
  for (const child of [].concat(children)) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function toast(text, isError = false) {
  Shared.toast(text, isError);  // the message box is shared with the Living room page (shared.js)
}

async function attempt(action) {
  try {
    return await action();
  } catch (error) {
    toast(error.message, true);
  }
}

// A gesture's label written as words, for reading: HORIZONTAL_LINE is "Horizontal line".
const nameOf = (label) => Shared.gestureName(label);

function colorFor(label) {
  const config = state.config;
  if (!config) return ink.soft;
  if (label === "UNKNOWN") return config.unknown_color;
  return config.gestures[label]?.color ?? ink.soft;   // a gesture no longer in the settings: grey
}

const fmt = (x) => (x === null || x === undefined ? "–" : Number(x).toFixed(2));

function recordedAt(sampleId) {
  const m = sampleId.match(/_(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : sampleId;
}

// ---------- live signal charts ----------

// An empty chart cannot be zoomed (fixedrange): with no readings to fit, Plotly has nothing to
// zoom back out to, and the chart would stay stuck on whatever was dragged.
function signalLayout(empty = false) {
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: CHART_FONT, color: ink.soft, size: 11 },
    margin: { l: 36, r: 4, t: 32, b: 36 },
    legend: { orientation: "h", x: 0, xanchor: "left", y: 1, yanchor: "bottom", font: { color: ink.soft, size: 12 } },
    hovermode: "x unified",
    hoverlabel: { bgcolor: ink.surface, bordercolor: ink.strong, font: { family: CHART_FONT, color: ink.text, size: 12 } },
    // Only level lines across: the readings are read against height, and time is on the axis.
    xaxis: { title: { text: "seconds", standoff: 6 }, hoverformat: ".2f", showgrid: false, zeroline: false,
             ticks: "outside", ticklen: 4, tickcolor: ink.line, linecolor: ink.line, showline: true, fixedrange: empty },
    yaxis: { gridcolor: ink.line, zerolinecolor: ink.strong, zerolinewidth: 1, nticks: 6, fixedrange: empty },
  };
}

function signalTraces(t = [], columns = [[], [], []]) {
  return AXES.map((name, i) => ({
    x: t, y: columns[i], name, mode: "lines", hovertemplate: "%{y:.2f}", line: { color: ink.series[i], width: 2 },
  }));
}

// Draws one sensor chart. A fresh drawing shows the whole cast, so its Reset zoom button goes.
function drawSignal(id, traces) {
  const empty = !traces.some((trace) => trace.x.length);
  Plotly.react(id, traces, signalLayout(empty), plotConfig);
  showZoomButton(id);
}

function setSignals(t, accel, gyro) {
  drawSignal("accel-chart", signalTraces(t, accel));
  drawSignal("gyro-chart", signalTraces(t, gyro));
}

// A chart that is zoomed in (drag across it) shows a Reset zoom button in its corner.
function showZoomButton(id) {
  const button = document.querySelector(`[data-zoom-out="${id}"]`);
  const { xaxis, yaxis } = $(id).layout;
  if (button) button.hidden = xaxis.autorange !== false && yaxis.autorange !== false;
}

function wireZoomButtons() {
  for (const id of SIGNAL_CHARTS) {
    const button = el("button", { type: "button", className: "quiet zoom-out", hidden: true, "data-zoom-out": id }, "Reset zoom");
    button.addEventListener("click", () => Plotly.relayout(id, { "xaxis.autorange": true, "yaxis.autorange": true }));
    $(id).parentElement.append(button);
    $(id).on("plotly_relayout", () => showZoomButton(id));
  }
}

function appendSignals(rows) {
  if (state.liveStart === null) state.liveStart = rows[0][0];
  const t = rows.map((r) => (r[0] - state.liveStart) / 1000);
  const columns = (first) => [0, 1, 2].map((k) => rows.map((r) => r[first + k]));
  Plotly.extendTraces("accel-chart", { x: [t, t, t], y: columns(1) }, [0, 1, 2]);
  Plotly.extendTraces("gyro-chart", { x: [t, t, t], y: columns(4) }, [0, 1, 2]);
}

// ---------- the trail: where the wand tip went ----------

// The box that holds any path: the tip is always one wand length from the hand (at 0,0,0).
// Its axes never move, which lets the trail be drawn while the cast is still going on.
function fullBox(trace) {
  const wandLength = trace?.x.length ? Math.hypot(trace.x[0], trace.y[0], trace.z[0]) : 0.3;
  const reach = 1.1 * wandLength;
  return [[-reach, reach], [-reach, reach], [-reach, reach]];
}

// The smallest box that holds a finished path and the hand, with a little room around them.
// No side is under 0.6 of the longest, so a small movement is not shown in a thin sliver.
function fittedBox(trace) {
  const span = (values) => {
    const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
    const pad = (hi - lo) * 0.08 || 0.05;
    return [lo - pad, hi + pad];
  };
  const box = [span(trace.x), span(trace.y), span(trace.z)];
  const shortest = 0.6 * Math.max(...box.map(([lo, hi]) => hi - lo));
  return box.map(([lo, hi]) => {
    const extra = Math.max(0, shortest - (hi - lo)) / 2;
    return [lo - extra, hi + extra];
  });
}

// The side of one grid square: a sixth of the wand's length, rounded to 1, 2 or 5 of a unit
// (5 cm for a 30 cm wand). It depends on the wand alone, so the grid stays the same while the
// view closes in on a trail.
function gridStep(trace) {
  const raw = fullBox(trace)[0][1] / 6.6;
  const unit = 10 ** Math.floor(Math.log10(raw));
  const digit = raw / unit;
  return (digit < 1.5 ? 1 : digit < 3.5 ? 2 : digit < 7.5 ? 5 : 10) * unit;
}

// box = the range shown along each axis: [[x from, x to], [y from, y to], [z from, z to]]
// The view is a room: three walls ruled in squares of `step`, the same size on every wall, and
// on each wall a stronger line level with your hand.
function trailLayout(box, step) {
  const sizes = box.map(([lo, hi]) => hi - lo);
  const largest = Math.max(...sizes);
  const axis = (title, range) => ({
    title: { text: title, font: { family: CHART_FONT, color: ink.stageText, size: 12 } },
    range, tick0: 0, dtick: step,
    showbackground: true, backgroundcolor: ink.stageWall,
    gridcolor: ink.stageLine, gridwidth: 1,
    zeroline: true, zerolinecolor: ink.stageZero, zerolinewidth: 2,
    showticklabels: false, showspikes: false,
  });
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    margin: { l: 0, r: 0, t: 0, b: 0 },
    showlegend: false,
    uirevision: "keep-camera",  // keep the viewer's rotation between casts
    scene: {
      aspectmode: "manual",
      aspectratio: { x: sizes[0] / largest, y: sizes[1] / largest, z: sizes[2] / largest },
      // From behind your hand, turned very slightly to one side. Looking exactly along the
      // forward axis left Plotly two equally good edges for the axis names, and it switched
      // between them from frame to frame, so the names flashed.
      camera: { eye: { x: -1.5, y: -0.06, z: 0.3 }, up: { x: 0, y: 0, z: 1 } },
      xaxis: axis("forward", box[0]),
      yaxis: axis("left", box[1]),
      zaxis: axis("up", box[2]),
    },
  };
}

// How bright a colour ("#rrggbb") is, from 0 (black) to 1 (white).
function luminance(color) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

// A spell's colour as drawn in the motion view. A colour too close to the background (yellow
// or white on the light one) is mixed toward the text colour until it stands out.
function onStage(color) {
  const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  const back = luminance(ink.stage);
  const part = (hex, i) => parseInt(hex.slice(i, i + 2), 16);
  let shown = color;
  for (let share = 0.15; share <= 0.75 && ratio(luminance(shown), back) < 2.4; share += 0.15) {
    shown = "#" + [1, 3, 5].map((i) => Math.round(part(color, i) * (1 - share) + part(ink.text, i) * share)
      .toString(16).padStart(2, "0")).join("");
  }
  return shown;
}

// color = null draws the trail in the theme colour: the spell is not known yet.
function trailTraces(trace, color, count) {
  const x = trace.x.slice(0, count), y = trace.y.slice(0, count), z = trace.z.slice(0, count);
  const tip = count - 1;
  const stroke = color ? onStage(color) : ink.stageLight;
  const line = (width, opacity) => ({
    type: "scatter3d", mode: "lines", x, y, z, opacity, hoverinfo: "skip", line: { width, color: stroke },
  });
  return [
    line(18, 0.18),  // glow
    line(5, 1),      // the trail itself
    { type: "scatter3d", mode: "lines", hoverinfo: "skip", line: { width: 3, color: ink.stageText },
      x: [0, x[tip]], y: [0, y[tip]], z: [0, z[tip]] },  // the wand, from your hand to its tip
  ];
}

let trailFrame = null;
// Shows a finished trail, fitted to the view. replay = true draws it again from its start;
// false is for a trail that was just drawn live: the view only closes in on it.
// asked = true means the user pressed Replay, so it plays even if they prefer reduced motion.
function drawTrail(motion, color, caption, replay = true, asked = false) {
  cancelAnimationFrame(trailFrame);
  $("trail-caption").textContent = caption;
  const trace = motion?.trace?.x.length > 1 ? motion.trace : null;
  state.trail = { trace, color, box: trace ? fittedBox(trace) : fullBox(null) };
  showReplayButton();
  if (!trace || (reduceMotion && !asked)) {
    paintTrail();
    return;
  }
  const total = trace.x.length, fitted = state.trail.box, wide = fullBox(trace), started = performance.now();
  const step = (now) => {
    const progress = Math.min(1, (now - started) / (replay ? 800 : 500));
    if (replay) {
      paintTrail(Math.max(2, Math.ceil(total * progress)));
    } else {
      const eased = 1 - (1 - progress) ** 3;
      paintTrail(total, wide.map(([lo, hi], k) => [lo + (fitted[k][0] - lo) * eased, hi + (fitted[k][1] - hi) * eased]));
    }
    if (progress < 1) trailFrame = requestAnimationFrame(step);
  };
  trailFrame = requestAnimationFrame(step);
}

// The Replay button on the motion view: usable when a finished trail is showing.
function showReplayButton() {
  $("replay").disabled = !state.trail?.trace || Boolean(state.liveTrail);
}

function replayTrail() {
  const { trace, color } = state.trail ?? {};
  if (!trace || state.liveTrail) return;
  playOnce($("replay"), "spin");
  drawTrail({ trace }, color, $("trail-caption").textContent, true, true);
}

// Plays a CSS animation that style.css ties to this class, from its start.
function playOnce(node, className) {
  node.classList.remove(className);
  void node.offsetWidth;  // without this the browser would not restart the animation
  node.classList.add(className);
}

// Brings the motion view into sight and resolves once the page has stopped scrolling, so
// a replay starts when it can be seen.
function showStage() {
  const stage = $("trail");
  const box = stage.getBoundingClientRect();
  if (box.top >= 0 && box.bottom <= window.innerHeight) return Promise.resolve();
  stage.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
  return new Promise((resolve) => {
    const started = performance.now();
    let last = null, still = 0, moved = false;
    const timeout = setTimeout(resolve, 1500);  // never wait longer than this
    const check = () => {
      const top = stage.getBoundingClientRect().top;
      if (last !== null && top !== last) moved = true;
      still = top === last ? still + 1 : 0;
      last = top;
      // Arrived: it moved and has now been still for a few frames (or it never needed to move).
      if (still >= 4 && (moved || performance.now() - started > 300)) {
        clearTimeout(timeout);
        resolve();
      } else {
        requestAnimationFrame(check);
      }
    };
    requestAnimationFrame(check);
  });
}

// How fast scrolling zooms the motion view, as a multiple of Plotly's own speed, which takes
// a lot of scrolling. Plotly has no public setting for it, so the speed is set on the 3D
// view's camera, an internal part of Plotly 2.35.2 (the version index.html loads). If a later
// version has no such camera, nothing happens and the zoom keeps Plotly's speed.
const TRAIL_ZOOM_SPEED = 4;
function setTrailZoomSpeed() {
  const camera = $("trail")._fullLayout?.scene?._scene?.camera;
  if (camera) camera.zoomSpeed = TRAIL_ZOOM_SPEED;
}

// Draws what state.trail holds, in the current theme: all of it or only its first `count`
// points, in its own box or in the one given.
function paintTrail(count, box) {
  const trail = state.trail;
  $("trail").parentElement.classList.toggle("empty", !trail.trace);
  let traces = null, shown = trail.box;
  if (trail.trace) {
    traces = trailTraces(trail.trace, trail.color, count ?? trail.trace.x.length);
    shown = box ?? trail.box;
  } else {
    // Just the hand, so the empty scene is still 3D (an empty plot would default to 2D).
    traces = [{ type: "scatter3d", mode: "markers", x: [0], y: [0], z: [0], hoverinfo: "skip",
      marker: { size: 4, color: ink.stageText } }];
  }
  Plotly.react("trail", traces, trailLayout(shown, gridStep(trail.trace)), plotConfig).then(setTrailZoomSpeed);
}

// While a cast is going on, the trail grows as the tip positions arrive (in plain light: the
// spell is not known yet).
function startLiveTrail(caption) {
  state.liveTrail = { x: [], y: [], z: [] };
  drawTrail(null, null, caption);  // just the hand, until the first positions arrive
}

function extendLiveTrail(points) {
  const trace = state.liveTrail;
  if (!trace || !points?.length) return;
  for (const [x, y, z] of points) {
    trace.x.push(x);
    trace.y.push(y);
    trace.z.push(z);
  }
  state.trail = { trace, color: null, box: fullBox(trace) };
  cancelAnimationFrame(trailFrame);  // several batches can arrive between two frames: draw once
  trailFrame = requestAnimationFrame(() => paintTrail());
}

// After a theme change: every chart again, in the new colours.
function redrawCharts() {
  for (const id of SIGNAL_CHARTS) {
    const shown = $(id).data;
    if (!shown) continue;
    drawSignal(id, shown.map((trace, i) => ({ ...trace, line: { ...trace.line, color: ink.series[i] } })));
  }
  if (state.trail) {
    cancelAnimationFrame(trailFrame);
    paintTrail();
  }
}

// Ends the live trail. Returns true if it was drawn, so the finished trail need not be replayed.
function endLiveTrail() {
  const drawn = (state.liveTrail?.x.length ?? 0) > 1;
  state.liveTrail = null;
  showReplayButton();
  return drawn;
}

// ---------- status ----------

function renderStatus(status) {
  state.status = status;
  const connected = status.connected;
  Shared.showStatus(status);  // the top bar: connection, wand state, connect buttons (shared.js)

  const recording = status.recording;
  const idle = connected && status.wand_state === "IDLE" && !recording;
  $("record-start").hidden = Boolean(recording);
  $("record-stop").hidden = !recording;
  $("record-start").disabled = !idle;
  $("train-label").disabled = Boolean(recording);
  $("record-status").textContent = recording
    ? `Recording ${recording}. Perform the gesture, then press Stop and save.`
    : connected ? "" : "Connect the wand to record.";

  renderHistory(status.history);
  renderDatasetSummary(status.dataset);
  renderTrainCount();
}

// Under the gesture picker: how many examples that gesture has, and whether that is enough.
function renderTrainCount() {
  const label = $("train-label").value;
  const n = state.status?.dataset?.[label] ?? 0;
  $("train-count").textContent = !label ? ""
    : n === 0 ? `${nameOf(label)} has no examples yet. Record five or more.`
    : n < 5 ? `${nameOf(label)} has ${n} ${n === 1 ? "example" : "examples"}. Five or more works well.`
    : `${nameOf(label)} has ${n} examples.`;
}

let historyShown = null;  // what the list last showed, to tell when a cast has been added
function renderHistory(history) {
  const list = $("history");
  list.replaceChildren(...history.map((entry) => el("li", {}, [
    el("span", { className: "swatch", style: `background:${colorFor(entry.label)}` }),
    el("span", { className: "name" }, nameOf(entry.label)),
    el("span", { className: "distance" }, entry.distance === null ? "no motion" : fmt(entry.distance)),
  ])));
  if (!history.length) list.replaceChildren(el("li", { className: "none" }, "Nothing cast yet."));
  const key = JSON.stringify(history);
  if (historyShown !== null && key !== historyShown && history.length) list.firstElementChild.classList.add("new");
  historyShown = key;
}

function renderDatasetSummary(counts) {
  const entries = Object.entries(counts);
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  $("dataset-summary").textContent = total
    ? `${total} samples: ` + entries.map(([label, n]) => `${n} ${nameOf(label)}`).join(", ") + "."
    : "No samples yet. Record a few examples of each gesture under Train a gesture.";
}

// ---------- results ----------

// Black or white, whichever is easier to read on this colour ("#rrggbb").
function textOn(color) {
  return luminance(color) > 0.179 ? "#16161a" : "#ffffff";
}

// The spell's name stays on one line: a long name gets smaller letters.
function fitSpellName() {
  const name = $("verdict-label");
  name.style.fontSize = "";
  if ($("verdict").classList.contains("empty") || name.scrollWidth <= name.clientWidth) return;
  const size = parseFloat(getComputedStyle(name).fontSize);
  name.style.fontSize = `${Math.floor(size * name.clientWidth / name.scrollWidth)}px`;
}

// The threshold on a scale, and the cast's distance on it when there is one. The mark slides
// to its place (style.css), so two casts are easy to compare.
function showGauge(distance, threshold) {
  const scaleEnd = Math.max(2 * threshold, 1.15 * (distance ?? 0));
  const at = (value) => `${(100 * value / scaleEnd).toFixed(1)}%`;
  $("gauge-accept").style.width = at(threshold);
  $("gauge-limit").style.left = at(threshold);
  $("gauge-limit-label").style.left = at(threshold);
  $("gauge-limit-label").textContent = `threshold ${fmt(threshold)}`;
  const mark = $("gauge-mark");
  mark.hidden = distance === null;
  if (distance === null) return;
  mark.style.left = at(distance);
  mark.dataset.value = fmt(distance);
}

function showResult(result) {
  const verdict = $("verdict");
  verdict.classList.remove("empty", "lit");
  verdict.style.setProperty("--spell", result.color);
  verdict.style.setProperty("--on-spell", textOn(result.color));
  $("verdict-label").textContent = nameOf(result.label);
  fitSpellName();
  void verdict.offsetWidth;  // lets the "lit" animation play again for this result
  verdict.classList.add("lit");

  const trained = Object.values(state.status?.dataset ?? {}).some((n) => n > 0);
  $("verdict-detail").textContent = result.label !== "UNKNOWN"
    ? `Distance ${fmt(result.distance)}, within the threshold of ${fmt(result.threshold)}.`
    : result.distance !== null
      ? `Nearest is ${nameOf(result.nearest_label)} at distance ${fmt(result.distance)}, above the threshold of ${fmt(result.threshold)}.`
      : trained
        ? "The wand barely moved, or the cast was too short."
        : "No gestures are trained yet, so nothing can be recognised. Record examples under Train a gesture.";
  if (result.dropped > 0) $("verdict-detail").textContent += ` ${result.dropped} samples were lost on the way.`;
  state.resultShown = true;
  showGauge(result.distance, result.threshold);

  const seconds = result.t.length ? result.t[result.t.length - 1].toFixed(2) : "0";
  $("fact-samples").textContent = result.sample_count;
  $("fact-length").textContent = `${seconds} s`;
  $("fact-answer").textContent = result.response_ms === null ? "–" : `${Math.round(result.response_ms)} ms`;
  $("verdict-action").textContent = "";
  drawTrail(result, result.color, `${nameOf(result.label)}: ${result.sample_count} samples over ${seconds} s`, !endLiveTrail());
  setSignals(result.t, result.accel, result.gyro);
}

function showAction(outcome) {
  const done = {
    notify: "Showed a Mac notification.",
    webhook: `Sent the web request (${outcome.detail}).`,
  };
  $("verdict-action").textContent = outcome.ok ? done[outcome.action_type] ?? outcome.detail
    : `The action didn't work: ${outcome.detail}`;
}

// ---------- settings ----------
// The Settings panel is shared with the Living room page (settings.js). Here the settings decide
// which gestures can be trained, the threshold on the gauge, and each gesture's colour.

function renderTrainOptions() {
  const select = $("train-label");
  const chosen = select.value;
  select.replaceChildren(...Object.keys(state.config.gestures).map((label) => el("option", { value: label }, nameOf(label))));
  if (chosen in state.config.gestures) select.value = chosen;
  if (state.status) renderStatus(state.status);
}

function followConfig() {
  renderTrainOptions();
  if (!state.resultShown) showGauge(null, state.config.dtw_threshold);
  renderSamples();
}

// ---------- dataset ----------

async function loadSamples() {
  state.samples = await api("GET", "/api/samples");
  renderSamples();
}

function checkText(check) {
  if (!check) return ["", ""];
  if (check.nearest_label === null) return ["Only sample, nothing to compare with", "check-ok"];
  if (check.nearest_label !== check.label) return [`Looks like ${nameOf(check.nearest_label)} (${fmt(check.distance)})`, "check-bad"];
  if (check.suspicious) return [`Far from the others (${fmt(check.distance)})`, "check-bad"];
  return [`OK (${fmt(check.distance)})`, "check-ok"];
}

function renderSamples() {
  const rows = state.samples.map((sample) => {
    const [text, cls] = checkText(state.checks[sample.sample_id]);
    const view = el("button", { type: "button", className: "text" }, "View");
    view.addEventListener("click", () => attempt(async () => {
      // Fetch the sample while the page scrolls up; the replay starts once the motion view is in sight.
      const [detail] = await Promise.all([
        api("GET", `/api/samples/${encodeURIComponent(sample.sample_id)}`),
        showStage(),
      ]);
      endLiveTrail();
      drawTrail(detail, colorFor(detail.label), `${nameOf(detail.label)} sample recorded ${recordedAt(sample.sample_id)}`, true, true);
      setSignals(detail.t, detail.accel, detail.gyro);
    }));
    const remove = el("button", { type: "button", className: "text danger" }, "Delete");
    remove.addEventListener("click", () => askFirst(
      `Delete the ${nameOf(sample.label)} sample recorded ${recordedAt(sample.sample_id)}? This can't be undone.`,
      "Delete sample", remove, async () => {
        await api("DELETE", `/api/samples/${encodeURIComponent(sample.sample_id)}`);
        delete state.checks[sample.sample_id];
        await loadSamples();
        toast(`Deleted the ${nameOf(sample.label)} sample.`);
      }));
    return el("tr", { id: `sample-${sample.sample_id}` }, [
      el("td", {}, recordedAt(sample.sample_id)),
      el("td", { className: "gesture" }, [
        el("span", { className: "swatch", style: `background:${colorFor(sample.label)}` }), " ", nameOf(sample.label),
      ]),
      el("td", { className: "num" }, sample.n_samples),
      el("td", { className: "num" }, `${(sample.duration_ms / 1000).toFixed(2)} s`),
      el("td", { className: cls }, text),
      el("td", { className: "actions" }, [view, remove]),
    ]);
  });
  $("sample-rows").replaceChildren(...rows);
  $("clear-dataset").disabled = !state.samples.length;
  markTableOverflow();
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

// Before something that cannot be taken back with a click (deleting a sample, clearing them all),
// the panel asks: the question and two answers above the table. `from` gets the focus back.
const asking = { action: null, from: null };

function askFirst(question, yes, from, action) {
  Object.assign(asking, { action, from });
  $("confirm-question").textContent = question;
  $("confirm-yes").textContent = yes;
  $("dataset-confirm").hidden = false;
  $("confirm-no").focus();
}

function stopAsking() {
  $("dataset-confirm").hidden = true;
  if (asking.from?.isConnected) asking.from.focus();
  Object.assign(asking, { action: null, from: null });
}

async function answerYes() {
  $("confirm-yes").disabled = true;
  try {
    await asking.action();
    stopAsking();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("confirm-yes").disabled = false;
  }
}

// Clearing moves the files to a dated folder in cleared/, beside the data folder, so they can be
// put back by hand.
function askToClear() {
  const count = plural(state.samples.length, "sample");
  askFirst(`Clear all ${count}? Every gesture will need training again. `
    + "The files are kept in the cleared folder, so they can be put back.", `Clear ${count}`, $("clear-dataset"), async () => {
    const result = await api("POST", "/api/dataset/clear");
    state.checks = {};
    await loadSamples();
    toast(`Cleared ${plural(result.moved, "sample")}. They are kept in ${result.folder}.`);
  });
}

// A narrow window makes the table scroll sideways. Its last column (View, Delete) stays in
// sight then, and gets a line at its edge to show that the rest slides under it.
function markTableOverflow() {
  const frame = document.querySelector(".table-scroll");
  frame.classList.toggle("overflowing", frame.scrollWidth > frame.clientWidth);
}

async function checkDataset() {
  const button = $("check-dataset");
  button.disabled = true;
  button.textContent = "Checking…";
  try {
    const checks = await api("POST", "/api/dataset/check");
    state.checks = Object.fromEntries(checks.map((c) => [c.sample_id, c]));
    renderSamples();
    const bad = checks.filter((c) => c.suspicious && c.nearest_label !== null).length;
    toast(bad ? `${bad} of ${checks.length} samples look wrong. Consider deleting them.`
      : `All ${checks.length} samples look consistent.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Check dataset";
  }
}

// ---------- live events from app.py ----------

// A browser keeps at most 6 connections open to app.py, and each page holds one for its live
// updates. Chrome keeps a page you leave alive for a while (for the Back button), connection
// and all, so a few quick switches between the Wand and Living room pages used up all 6 and
// every page hung until one closed. So the connection closes the moment the page is left,
// and opens again if the page comes back.
function listen() {
  let events = openEvents();
  window.addEventListener("pagehide", () => events.close());
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) events = openEvents();
  });
}

function openEvents() {
  const events = new EventSource("/api/events");
  const on = (kind, handler) => events.addEventListener(kind, (e) => handler(JSON.parse(e.data)));
  on("status", renderStatus);
  on("cast_start", (data) => {
    state.liveStart = null;
    setSignals([], [[], [], []], [[], [], []]);
    startLiveTrail(data.source === "recording" ? "Recording…" : "Casting…");
  });
  on("motion", (data) => {
    appendSignals(data.rows);
    extendLiveTrail(data.tip);
  });
  on("result", showResult);
  on("action", showAction);
  on("sample_saved", (data) => attempt(async () => {
    toast(`Saved a ${nameOf(data.label)} example (${data.sample_count} samples).`);
    await loadSamples();
    document.getElementById(`sample-${data.sample_id}`)?.classList.add("new");  // its row lights up briefly
    const detail = await api("GET", `/api/samples/${encodeURIComponent(data.sample_id)}`);
    drawTrail(detail, colorFor(data.label), `New ${nameOf(data.label)} example`, !endLiveTrail());
    setSignals(detail.t, detail.accel, detail.gyro);
  }));
  on("message", (data) => toast(data.text, data.level === "warning"));
  events.onerror = () => Shared.lostContact();
  return events;
}

// ---------- buttons ----------

function wireButtons() {
  $("record-start").addEventListener("click", () =>
    attempt(() => api("POST", "/api/recording/start", { label: $("train-label").value })));
  $("record-stop").addEventListener("click", () => attempt(() => api("POST", "/api/recording/stop")));
  $("check-dataset").addEventListener("click", checkDataset);
  $("clear-dataset").addEventListener("click", askToClear);
  $("confirm-yes").addEventListener("click", answerYes);
  $("confirm-no").addEventListener("click", stopAsking);
  $("dataset-confirm").addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();   // only the question goes, not the panel
      stopAsking();
    }
  });
  // Saved settings (settings.js): which gestures, their colours, the threshold.
  window.addEventListener("spellwand:config", (event) => {
    state.config = event.detail;
    followConfig();
  });
  $("train-label").addEventListener("change", renderTrainCount);
  $("replay").addEventListener("click", replayTrail);
  new ResizeObserver(fitSpellName).observe($("verdict"));
  new ResizeObserver(markTableOverflow).observe(document.querySelector(".table-scroll"));
  document.fonts.ready.then(fitSpellName);
}

async function start() {
  [state.meta, state.config] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/config")]);
  wireTheme();
  wireButtons();
  followConfig();
  setSignals([], [[], [], []], [[], [], []]);
  wireZoomButtons();
  drawTrail(null, null, "No casts yet. Hold the cast button and draw a gesture.");
  listen();
  await loadSamples();
}

start().catch((error) => toast(`The page couldn't start: ${error.message}`, true));
