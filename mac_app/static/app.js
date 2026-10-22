// SpellWand UI: talks to app.py's JSON API and listens to its live event stream.

const COLORS = { haze: "#2c2f57", grid: "#262850", mist: "#9a9cc4", newGesture: "#b48cff" };
const AXES = ["x (along wand)", "y (left)", "z (up)"];
const AXIS_COLORS = ["#ff8fa3", "#8fd3ff", "#c4f28f"];
const MOTION_NAMES = {
  CIRCLE: "Draw a circle",
  ZIGZAG: "Draw a zigzag",
  HORIZONTAL_LINE: "Draw a horizontal line",
  WOBBLE: "Wave it around",
  STILL: "Hold it still",
};
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const plotConfig = { displayModeBar: false, responsive: true };

const state = { status: null, config: null, meta: null, samples: [], checks: {}, liveStart: null };
const $ = (id) => document.getElementById(id);

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
  if (!config) return COLORS.mist;
  if (label === "UNKNOWN") return config.unknown_color;
  return config.gestures[label]?.color ?? COLORS.newGesture;
}

const fmt = (x) => (x === null || x === undefined ? "–" : Number(x).toFixed(2));

function recordedAt(sampleId) {
  const m = sampleId.match(/_(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : sampleId;
}

// ---------- live signal charts ----------

function signalLayout(title) {
  return {
    title: { text: title, x: 0.02, font: { size: 13, color: COLORS.mist } },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Recursive, system-ui, sans-serif", color: COLORS.mist, size: 11 },
    margin: { l: 44, r: 12, t: 36, b: 32 },
    legend: { orientation: "h", x: 0.35, y: 1.18 },
    xaxis: { title: { text: "seconds" }, gridcolor: COLORS.grid, zeroline: false },
    yaxis: { gridcolor: COLORS.grid, zerolinecolor: COLORS.haze },
  };
}

function signalTraces(t = [], columns = [[], [], []]) {
  return AXES.map((name, i) => ({
    x: t, y: columns[i], name, mode: "lines", line: { color: AXIS_COLORS[i], width: 1.5 },
  }));
}

function setSignals(t, accel, gyro) {
  Plotly.react("accel-chart", signalTraces(t, accel), signalLayout("Accelerometer (m/s²)"), plotConfig);
  Plotly.react("gyro-chart", signalTraces(t, gyro), signalLayout("Gyroscope (rad/s)"), plotConfig);
}

function appendSignals(rows) {
  if (state.liveStart === null) state.liveStart = rows[0][0];
  const t = rows.map((r) => (r[0] - state.liveStart) / 1000);
  const columns = (first) => [0, 1, 2].map((k) => rows.map((r) => r[first + k]));
  Plotly.extendTraces("accel-chart", { x: [t, t, t], y: columns(1) }, [0, 1, 2]);
  Plotly.extendTraces("gyro-chart", { x: [t, t, t], y: columns(4) }, [0, 1, 2]);
}

// ---------- the trail: where the wand tip went ----------

function trailLayout(trace) {
  // Fix the axes to the whole trail (and the hand at 0,0,0) so nothing jumps while it draws.
  const span = (values) => {
    const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
    const pad = (hi - lo) * 0.08 || 0.05;
    return [lo - pad, hi + pad];
  };
  const ranges = trace ? [span(trace.x), span(trace.y), span(trace.z)] : [[0, 0.3], [-0.2, 0.2], [-0.2, 0.2]];
  const sizes = ranges.map(([lo, hi]) => hi - lo);
  const largest = Math.max(...sizes);
  const axis = (title, range) => ({
    title: { text: title, font: { color: COLORS.mist, size: 11 } },
    range, showbackground: false, gridcolor: COLORS.grid, zeroline: false,
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
      camera: { eye: { x: -1.7, y: 0, z: 0.35 }, up: { x: 0, y: 0, z: 1 } },  // from behind your hand
      xaxis: axis("forward", ranges[0]),
      yaxis: axis("left", ranges[1]),
      zaxis: axis("up", ranges[2]),
    },
  };
}

function trailTraces(trace, color, count) {
  const x = trace.x.slice(0, count), y = trace.y.slice(0, count), z = trace.z.slice(0, count);
  const tip = count - 1;
  const line = (width, opacity) => ({
    type: "scatter3d", mode: "lines", x, y, z, opacity, hoverinfo: "skip", line: { width, color },
  });
  return [
    line(18, 0.18),  // glow
    line(5, 1),      // the trail itself
    { type: "scatter3d", mode: "lines", hoverinfo: "skip", line: { width: 3, color: COLORS.haze },
      x: [0, x[tip]], y: [0, y[tip]], z: [0, z[tip]] },  // the wand, from your hand to its tip
  ];
}

let trailFrame = null;
function drawTrail(motion, color, caption) {
  cancelAnimationFrame(trailFrame);
  $("trail-caption").textContent = caption;
  const trace = motion?.trace;
  if (!trace || trace.x.length < 2) {
    // Just the hand, so the empty scene is still 3D (an empty plot would default to 2D).
    const hand = { type: "scatter3d", mode: "markers", x: [0], y: [0], z: [0], hoverinfo: "skip",
      marker: { size: 4, color: COLORS.haze } };
    Plotly.react("trail", [hand], trailLayout(null), plotConfig);
    return;
  }
  const total = trace.x.length;
  const layout = trailLayout(trace);
  if (reduceMotion) {
    Plotly.react("trail", trailTraces(trace, color, total), layout, plotConfig);
    return;
  }
  const started = performance.now();
  const step = (now) => {
    const count = Math.max(2, Math.ceil(total * Math.min(1, (now - started) / 800)));
    Plotly.react("trail", trailTraces(trace, color, count), layout, plotConfig);
    if (count < total) trailFrame = requestAnimationFrame(step);
  };
  trailFrame = requestAnimationFrame(step);
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
  chip.dataset.state = connected ? status.wand_state : "IDLE";

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
}

function renderHistory(history) {
  const list = $("history");
  list.replaceChildren(...history.map((entry) => el("li", {}, [
    el("span", { className: "swatch", style: `background:${colorFor(entry.label)}` }),
    el("span", { className: "name" }, entry.label),
    el("span", { className: "distance" }, entry.distance === null ? "no motion" : fmt(entry.distance)),
  ])));
  if (!history.length) list.replaceChildren(el("li", { className: "detail" }, "Nothing cast yet."));
}

function renderDatasetSummary(counts) {
  const entries = Object.entries(counts);
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  $("dataset-summary").textContent = total
    ? `${total} samples: ` + entries.map(([label, n]) => `${n} ${label}`).join(", ") + "."
    : "No samples yet. Record a few examples of each gesture under Train a gesture.";
}

// ---------- results ----------

function showResult(result) {
  const label = $("verdict-label");
  label.textContent = result.label;
  label.style.color = result.color;
  let detail;
  if (result.label === "UNKNOWN") {
    detail = result.distance === null
      ? "The wand barely moved, or the cast was too short."
      : `Nearest is ${result.nearest_label} at distance ${fmt(result.distance)}, above the threshold of ${fmt(result.threshold)}.`;
  } else {
    detail = `Distance ${fmt(result.distance)}, within the threshold of ${fmt(result.threshold)}.`;
  }
  if (result.dropped > 0) detail += ` ${result.dropped} samples were lost on the way.`;
  $("verdict-detail").textContent = detail;
  $("verdict-action").textContent = "";
  const seconds = result.t.length ? result.t[result.t.length - 1].toFixed(2) : "0";
  drawTrail(result, result.color, `${result.label}: ${result.sample_count} samples over ${seconds} s`);
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
  state.config.gestures[name] = { color: COLORS.newGesture, action: { type: "none" } };
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
      const detail = await api("GET", `/api/samples/${encodeURIComponent(sample.sample_id)}`);
      drawTrail(detail, colorFor(detail.label), `${detail.label} sample recorded ${recordedAt(sample.sample_id)}`);
      setSignals(detail.t, detail.accel, detail.gyro);
      $("trail").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
    }));
    const remove = el("button", { type: "button", className: "danger" }, "Delete");
    remove.addEventListener("click", () => attempt(async () => {
      if (!confirm(`Delete this ${sample.label} sample? This can't be undone.`)) return;
      await api("DELETE", `/api/samples/${encodeURIComponent(sample.sample_id)}`);
      delete state.checks[sample.sample_id];
      await loadSamples();
      toast(`Deleted the ${sample.label} sample.`);
    }));
    return el("tr", {}, [
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
    $("trail-caption").textContent = data.source === "recording" ? "Recording…" : "Casting…";
  });
  on("motion", (data) => appendSignals(data.rows));
  on("result", showResult);
  on("action", showAction);
  on("sample_saved", (data) => attempt(async () => {
    toast(`Saved a ${data.label} example (${data.sample_count} samples).`);
    await loadSamples();
    const detail = await api("GET", `/api/samples/${encodeURIComponent(data.sample_id)}`);
    drawTrail(detail, colorFor(data.label), `New ${data.label} example`);
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

  $("sim-buttons").replaceChildren(...state.meta.simulated_motions.map((motion) => {
    const button = el("button", { type: "button", className: "quiet" }, MOTION_NAMES[motion] ?? `Cast ${motion}`);
    button.addEventListener("click", () => attempt(() => api("POST", "/api/simulate", { motion })));
    return button;
  }));
}

async function start() {
  [state.meta, state.config] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/config")]);
  wireButtons();
  renderConfig();
  setSignals([], [[], [], []], [[], [], []]);
  drawTrail(null, COLORS.mist, "No casts yet. Hold the cast button and draw a gesture.");
  listen();
  await loadSamples();
}

start().catch((error) => toast(`The page couldn't start: ${error.message}`, true));
