// SpellWand UI: talks to app.py's JSON API and listens to its live event stream.

const NEW_GESTURE_COLOR = "#b48cff";  // the LED colour a newly added gesture starts with
const AXES = ["x (along wand)", "y (left)", "z (up)"];
const CHART_FONT = "Archivo, 'Helvetica Neue', Arial, sans-serif";
const MOTION_NAMES = {
  CIRCLE: "Draw a circle",
  ZIGZAG: "Draw a zigzag",
  HORIZONTAL_LINE: "Draw a horizontal line",
  WOBBLE: "Wave it around",
  STILL: "Hold it still",
};
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const plotConfig = { displayModeBar: false, responsive: true };

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
    // the motion view is a dark stage in both themes
    stageLine: value("--stage-line"),
    stageText: value("--stage-text"),
    stageLight: value("--stage-light"),
  };
}
let ink = readInk();

function showThemeChoice() {
  const theme = document.documentElement.dataset.theme;
  for (const button of document.querySelectorAll("[data-theme-choice]")) {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === theme));
  }
}

let themeFade = null;
function setTheme(theme) {
  const root = document.documentElement;
  root.classList.add("theme-fade");  // style.css lets the colours cross-fade while this is on
  clearTimeout(themeFade);
  themeFade = setTimeout(() => root.classList.remove("theme-fade"), 300);
  root.dataset.theme = theme;
  ink = readInk();
  showThemeChoice();
  redrawCharts();
}

function wireTheme() {
  showThemeChoice();
  for (const button of document.querySelectorAll("[data-theme-choice]")) {
    button.addEventListener("click", () => {
      try { localStorage.setItem("spellwand-theme", button.dataset.themeChoice); } catch { /* private window */ }
      setTheme(button.dataset.themeChoice);
    });
  }
  // Until a theme is chosen here, follow the system's.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
    let saved = null;
    try { saved = localStorage.getItem("spellwand-theme"); } catch { /* private window */ }
    if (!saved) setTheme(event.matches ? "dark" : "light");
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

let toastTimer = null;
function toast(text, isError = false) {
  const box = $("toast");
  box.textContent = text;
  box.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.className = "toast"), isError ? 6000 : 3500);
}

async function attempt(action) {
  try {
    return await action();
  } catch (error) {
    toast(error.message, true);
  }
}

function colorFor(label) {
  const config = state.config;
  if (!config) return ink.soft;
  if (label === "UNKNOWN") return config.unknown_color;
  return config.gestures[label]?.color ?? NEW_GESTURE_COLOR;
}

const fmt = (x) => (x === null || x === undefined ? "–" : Number(x).toFixed(2));

function recordedAt(sampleId) {
  const m = sampleId.match(/_(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : sampleId;
}

// ---------- live signal charts ----------

function signalLayout() {
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: CHART_FONT, color: ink.soft, size: 12 },
    margin: { l: 40, r: 8, t: 30, b: 40 },
    legend: { orientation: "h", x: 1, xanchor: "right", y: 1, yanchor: "bottom", font: { color: ink.text } },
    hovermode: "x unified",
    hoverlabel: { bgcolor: ink.surface, bordercolor: ink.strong, font: { family: CHART_FONT, color: ink.text, size: 12 } },
    xaxis: { title: { text: "seconds", standoff: 8 }, hoverformat: ".2f", gridcolor: ink.line, zeroline: false },
    yaxis: { gridcolor: ink.line, zerolinecolor: ink.strong },
  };
}

function signalTraces(t = [], columns = [[], [], []]) {
  return AXES.map((name, i) => ({
    x: t, y: columns[i], name, mode: "lines", hovertemplate: "%{y:.2f}", line: { color: ink.series[i], width: 2 },
  }));
}

function setSignals(t, accel, gyro) {
  Plotly.react("accel-chart", signalTraces(t, accel), signalLayout(), plotConfig);
  Plotly.react("gyro-chart", signalTraces(t, gyro), signalLayout(), plotConfig);
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

// box = the range shown along each axis: [[x from, x to], [y from, y to], [z from, z to]]
function trailLayout(box) {
  const sizes = box.map(([lo, hi]) => hi - lo);
  const largest = Math.max(...sizes);
  const axis = (title, range) => ({
    title: { text: title, font: { family: CHART_FONT, color: ink.stageText, size: 12 } },
    range, showbackground: false, gridcolor: ink.stageLine, zeroline: false,
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
      camera: { eye: { x: -1.5, y: 0, z: 0.3 }, up: { x: 0, y: 0, z: 1 } },  // from behind your hand
      xaxis: axis("forward", box[0]),
      yaxis: axis("left", box[1]),
      zaxis: axis("up", box[2]),
    },
  };
}

// color = null draws the trail in plain light: the spell is not known yet.
function trailTraces(trace, color, count) {
  const x = trace.x.slice(0, count), y = trace.y.slice(0, count), z = trace.z.slice(0, count);
  const tip = count - 1;
  const stroke = color ?? ink.stageLight;
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

// Draws what state.trail holds, in the current theme: all of it or only its first `count`
// points, in its own box or in the one given.
function paintTrail(count, box) {
  const trail = state.trail;
  if (!trail.trace) {
    // Just the hand, so the empty scene is still 3D (an empty plot would default to 2D).
    const hand = { type: "scatter3d", mode: "markers", x: [0], y: [0], z: [0], hoverinfo: "skip",
      marker: { size: 4, color: ink.stageText } };
    Plotly.react("trail", [hand], trailLayout(trail.box), plotConfig);
    return;
  }
  const traces = trailTraces(trail.trace, trail.color, count ?? trail.trace.x.length);
  Plotly.react("trail", traces, trailLayout(box ?? trail.box), plotConfig);
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
  for (const id of ["accel-chart", "gyro-chart"]) {
    const shown = $(id).data;
    if (!shown) continue;
    const traces = shown.map((trace, i) => ({ ...trace, line: { ...trace.line, color: ink.series[i] } }));
    Plotly.react(id, traces, signalLayout(), plotConfig);
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
  $("link-dot").className = "dot" + (connected ? " connected" : "");
  $("link-text").textContent = !connected ? "Not connected"
    : status.mode === "simulated" ? "Simulated wand connected" : "Wand connected";
  const chip = $("wand-state");
  chip.textContent = connected ? status.wand_state : "Offline";
  chip.dataset.state = connected ? status.wand_state : "OFFLINE";

  $("connect-ble").hidden = connected;
  $("connect-sim").hidden = connected;
  $("disconnect").hidden = !connected;
  $("sim-panel").hidden = status.mode !== "simulated";

  const recording = status.recording;
  const idle = connected && status.wand_state === "IDLE" && !recording;
  $("record-start").hidden = Boolean(recording);
  $("record-stop").hidden = !recording;
  $("record-start").disabled = !idle;
  $("train-label").disabled = Boolean(recording);
  $("record-status").textContent = recording
    ? `Recording ${recording}. Perform the gesture, then press Stop and save.`
    : connected ? "" : "Connect the wand to record.";
  for (const button of document.querySelectorAll("#sim-buttons button")) button.disabled = !idle;

  renderHistory(status.history);
  renderDatasetSummary(status.dataset);
  renderTrainCount();
}

// Under the gesture picker: how many examples that gesture has, and whether that is enough.
function renderTrainCount() {
  const label = $("train-label").value;
  const n = state.status?.dataset?.[label] ?? 0;
  $("train-count").textContent = !label ? ""
    : n === 0 ? `${label} has no examples yet. Record five or more.`
    : n < 5 ? `${label} has ${n} ${n === 1 ? "example" : "examples"}. Five or more works well.`
    : `${label} has ${n} examples.`;
}

let historyShown = null;  // what the list last showed, to tell when a cast has been added
function renderHistory(history) {
  const list = $("history");
  list.replaceChildren(...history.map((entry) => el("li", {}, [
    el("span", { className: "swatch", style: `background:${colorFor(entry.label)}` }),
    el("span", { className: "name" }, entry.label),
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
    ? `${total} samples: ` + entries.map(([label, n]) => `${n} ${label}`).join(", ") + "."
    : "No samples yet. Record a few examples of each gesture under Train a gesture.";
}

// ---------- results ----------

// Black or white, whichever is easier to read on this colour ("#rrggbb").
function textOn(color) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.179 ? "#16161a" : "#ffffff";
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
  $("verdict-label").textContent = result.label;
  fitSpellName();
  void verdict.offsetWidth;  // lets the "lit" animation play again for this result
  verdict.classList.add("lit");

  const trained = Object.values(state.status?.dataset ?? {}).some((n) => n > 0);
  $("verdict-detail").textContent = result.label !== "UNKNOWN"
    ? `Distance ${fmt(result.distance)}, within the threshold of ${fmt(result.threshold)}.`
    : result.distance !== null
      ? `Nearest is ${result.nearest_label} at distance ${fmt(result.distance)}, above the threshold of ${fmt(result.threshold)}.`
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
  drawTrail(result, result.color, `${result.label}: ${result.sample_count} samples over ${seconds} s`, !endLiveTrail());
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

function actionEditor(action) {
  const type = el("select", { className: "action-type", "aria-label": "Action" },
    Object.entries(state.meta.action_types).map(([value, text]) => el("option", { value }, text)));
  type.value = action.type;
  const extra = el("div", { className: "action-extra" });
  const renderExtra = () => {
    const kind = type.value;
    if (kind === "notify") {
      extra.replaceChildren(el("input", { type: "text", className: "action-message", placeholder: "Message to show",
        value: action.message ?? "", maxLength: 200, "aria-label": "Notification message" }));
    } else if (kind === "webhook") {
      extra.replaceChildren(el("input", { type: "url", className: "action-url", placeholder: "https://…",
        value: action.url ?? "", "aria-label": "Web address" }));
    } else {
      extra.replaceChildren();
    }
  };
  type.addEventListener("change", renderExtra);
  renderExtra();
  return el("div", { className: "action-cell" }, [type, extra]);
}

function renderConfig() {
  const config = state.config;
  $("threshold").value = config.dtw_threshold;
  $("unknown-color").value = config.unknown_color;
  if (!state.resultShown) showGauge(null, config.dtw_threshold);
  $("gesture-rows").replaceChildren(...Object.entries(config.gestures).map(([label, settings]) => {
    const remove = el("button", { type: "button", className: "danger" }, "Remove");
    remove.addEventListener("click", () => {
      state.config = readConfigForm();
      delete state.config.gestures[label];
      renderConfig();
      toast(`Removed ${label}. Its samples stay in the dataset. Press Save settings to apply.`);
    });
    const row = el("tr", {}, [
      el("td", {}, label),
      el("td", {}, el("input", { type: "color", className: "gesture-color", value: settings.color, "aria-label": `${label} colour` })),
      el("td", {}, actionEditor(settings.action)),
      el("td", {}, remove),
    ]);
    row.dataset.label = label;
    return row;
  }));

  const select = $("train-label");
  const chosen = select.value;
  select.replaceChildren(...Object.keys(config.gestures).map((label) => el("option", { value: label }, label)));
  if (chosen in config.gestures) select.value = chosen;
  if (state.status) renderStatus(state.status);
}

function readConfigForm() {
  const gestures = {};
  for (const row of $("gesture-rows").children) {
    const type = row.querySelector(".action-type").value;
    const action = { type };
    if (type === "notify") action.message = row.querySelector(".action-message").value;
    if (type === "webhook") action.url = row.querySelector(".action-url").value;
    gestures[row.dataset.label] = { color: row.querySelector(".gesture-color").value, action };
  }
  return {
    dtw_threshold: Number($("threshold").value),
    unknown_color: $("unknown-color").value,
    gestures,
  };
}

function addGesture() {
  const name = $("new-gesture").value.trim().toUpperCase().replace(/\s+/g, "_");
  if (!/^[A-Z][A-Z0-9_]{0,15}$/.test(name) || name === "UNKNOWN") {
    toast("Use 1–16 letters, digits or _, starting with a letter (not UNKNOWN).", true);
    return;
  }
  state.config = readConfigForm();
  if (name in state.config.gestures) {
    toast(`${name} is already a gesture.`, true);
    return;
  }
  state.config.gestures[name] = { color: NEW_GESTURE_COLOR, action: { type: "none" } };
  $("new-gesture").value = "";
  renderConfig();
  toast(`Added ${name}. Press Save settings to keep it, then record some examples.`);
}

// ---------- dataset ----------

async function loadSamples() {
  state.samples = await api("GET", "/api/samples");
  renderSamples();
}

function checkText(check) {
  if (!check) return ["", ""];
  if (check.nearest_label === null) return ["Only sample, nothing to compare with", "check-ok"];
  if (check.nearest_label !== check.label) return [`Looks like ${check.nearest_label} (${fmt(check.distance)})`, "check-bad"];
  if (check.suspicious) return [`Far from the others (${fmt(check.distance)})`, "check-bad"];
  return [`OK (${fmt(check.distance)})`, "check-ok"];
}

function renderSamples() {
  const rows = state.samples.map((sample) => {
    const [text, cls] = checkText(state.checks[sample.sample_id]);
    const view = el("button", { type: "button", className: "quiet" }, "View");
    view.addEventListener("click", () => attempt(async () => {
      // Fetch the sample while the page scrolls up; the replay starts once the motion view is in sight.
      const [detail] = await Promise.all([
        api("GET", `/api/samples/${encodeURIComponent(sample.sample_id)}`),
        showStage(),
      ]);
      endLiveTrail();
      drawTrail(detail, colorFor(detail.label), `${detail.label} sample recorded ${recordedAt(sample.sample_id)}`, true, true);
      setSignals(detail.t, detail.accel, detail.gyro);
    }));
    const remove = el("button", { type: "button", className: "danger" }, "Delete");
    remove.addEventListener("click", () => attempt(async () => {
      if (!confirm(`Delete this ${sample.label} sample? This can't be undone.`)) return;
      await api("DELETE", `/api/samples/${encodeURIComponent(sample.sample_id)}`);
      delete state.checks[sample.sample_id];
      await loadSamples();
      toast(`Deleted the ${sample.label} sample.`);
    }));
    return el("tr", { id: `sample-${sample.sample_id}` }, [
      el("td", {}, recordedAt(sample.sample_id)),
      el("td", { className: "gesture" }, [
        el("span", { className: "swatch", style: `background:${colorFor(sample.label)}` }), " ", sample.label,
      ]),
      el("td", { className: "num" }, sample.n_samples),
      el("td", { className: "num" }, `${(sample.duration_ms / 1000).toFixed(2)} s`),
      el("td", { className: cls }, text),
      el("td", { className: "actions" }, [view, remove]),
    ]);
  });
  $("sample-rows").replaceChildren(...rows);
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

function listen() {
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
    toast(`Saved a ${data.label} example (${data.sample_count} samples).`);
    await loadSamples();
    document.getElementById(`sample-${data.sample_id}`)?.classList.add("new");  // its row lights up briefly
    const detail = await api("GET", `/api/samples/${encodeURIComponent(data.sample_id)}`);
    drawTrail(detail, colorFor(data.label), `New ${data.label} example`, !endLiveTrail());
    setSignals(detail.t, detail.accel, detail.gyro);
  }));
  on("message", (data) => toast(data.text, data.level === "warning"));
  events.onerror = () => {
    $("link-dot").className = "dot";
    $("link-text").textContent = "Lost contact with app.py. Is it still running?";
  };
}

// ---------- buttons ----------

function wireButtons() {
  $("connect-ble").addEventListener("click", () => attempt(async () => {
    $("connect-ble").disabled = true;
    $("link-dot").className = "dot searching";
    $("link-text").textContent = "Looking for the wand (up to 10 s)…";
    try {
      await api("POST", "/api/connect", { mode: "ble" });
    } finally {
      $("connect-ble").disabled = false;
      if (state.status) renderStatus(state.status);
    }
  }));
  $("connect-sim").addEventListener("click", () => attempt(() => api("POST", "/api/connect", { mode: "simulated" })));
  $("disconnect").addEventListener("click", () => attempt(() => api("POST", "/api/disconnect")));
  $("record-start").addEventListener("click", () =>
    attempt(() => api("POST", "/api/recording/start", { label: $("train-label").value })));
  $("record-stop").addEventListener("click", () => attempt(() => api("POST", "/api/recording/stop")));
  $("add-gesture").addEventListener("click", addGesture);
  $("new-gesture").addEventListener("keydown", (e) => { if (e.key === "Enter") addGesture(); });
  $("save-settings").addEventListener("click", () => attempt(async () => {
    state.config = await api("PUT", "/api/config", readConfigForm());
    renderConfig();
    renderSamples();
    toast("Settings saved.");
  }));
  $("check-dataset").addEventListener("click", checkDataset);
  $("train-label").addEventListener("change", renderTrainCount);
  $("replay").addEventListener("click", replayTrail);
  new ResizeObserver(fitSpellName).observe($("verdict"));
  document.fonts.ready.then(fitSpellName);

  $("sim-buttons").replaceChildren(...state.meta.simulated_motions.map((motion) => {
    const button = el("button", { type: "button", className: "quiet" }, MOTION_NAMES[motion] ?? `Cast ${motion}`);
    button.addEventListener("click", () => attempt(() => api("POST", "/api/simulate", { motion })));
    return button;
  }));
}

async function start() {
  [state.meta, state.config] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/config")]);
  wireTheme();
  wireButtons();
  renderConfig();
  setSignals([], [[], [], []], [[], [], []]);
  drawTrail(null, null, "No casts yet. Hold the cast button and draw a gesture.");
  listen();
  await loadSamples();
}

start().catch((error) => toast(`The page couldn't start: ${error.message}`, true));
