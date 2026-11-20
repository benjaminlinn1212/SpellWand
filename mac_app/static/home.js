// Living room page: shows the simulated home kept by app.py and switches its devices.
// A cast switches a device when its gesture's action is "Living room" (set on the
// Wand page, under Recognition settings). Pressing a device here switches it too.

const $ = (id) => document.getElementById(id);
const state = { meta: null, config: null, devices: {} };

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
    if (key.includes("-")) node.setAttribute(key, value);
    else node[key] = value;
  }
  for (const child of [].concat(children)) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}

// ---------- theme (the same choice as the Wand page) ----------

function showThemeChoice() {
  const theme = document.documentElement.dataset.theme;
  for (const button of document.querySelectorAll("[data-theme-choice]")) {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === theme));
  }
}

function wireTheme() {
  for (const button of document.querySelectorAll("[data-theme-choice]")) {
    button.addEventListener("click", () => {
      const root = document.documentElement;
      root.classList.add("theme-fade");
      setTimeout(() => root.classList.remove("theme-fade"), 300);
      root.dataset.theme = button.dataset.themeChoice;
      try { localStorage.setItem("spellwand-theme", button.dataset.themeChoice); } catch (error) { /* private window */ }
      showThemeChoice();
    });
  }
  showThemeChoice();
}

// ---------- the devices ----------

function device(id) {
  return state.meta.home_devices.find((d) => d.device === id);
}

// "Lamp" → "the lamp", but "TV" stays "the TV".
function nameInSentence(id) {
  const name = device(id).name;
  return name === name.toUpperCase() ? `the ${name}` : `the ${name.toLowerCase()}`;
}

// "turned the lamp on", "opened the door", "closed the curtains"
function whatHappened(id, on) {
  const d = device(id);
  if (d.on === "on") return `turned ${nameInSentence(id)} ${on ? "on" : "off"}`;
  return `${on ? "opened" : "closed"} ${nameInSentence(id)}`;
}

function capitalise(word) {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

// The gestures whose action switches this device.
function gesturesFor(id) {
  return Object.entries(state.config?.gestures ?? {})
    .filter(([, settings]) => settings.action.type === "home" && settings.action.device === id);
}

function buildDevices() {
  $("devices").replaceChildren(...state.meta.home_devices.map((d) => {
    const button = el("button", { type: "button", className: "device", "data-device": d.device, "aria-pressed": "false" }, [
      el("span", { className: "device-name" }, d.name),
      el("span", { className: "device-state" }, capitalise(d.off)),
      el("span", { className: "device-gesture" }),
    ]);
    button.addEventListener("click", () => toggle(d.device));
    return el("li", {}, button);
  }));
  for (const art of document.querySelectorAll(".device-art")) {
    art.addEventListener("click", () => toggle(art.dataset.device));
  }
  showGestures();
}

function showGestures() {
  for (const d of state.meta.home_devices) {
    const line = document.querySelector(`.device[data-device="${d.device}"] .device-gesture`);
    const gestures = gesturesFor(d.device);
    line.replaceChildren(...(gestures.length
      ? gestures.flatMap(([label, settings], i) => [
        ...(i ? [" or "] : []),
        el("span", { className: "swatch", style: `background:${settings.color}` }), label])
      : ["No gesture yet"]));
  }
}

// Draws every device as `devices` says; `changed` is the one that just switched.
function render(devices, changed) {
  state.devices = devices;
  const room = $("room");
  for (const [id, on] of Object.entries(devices)) {
    room.classList.toggle(`${id}-on`, on);
    const button = document.querySelector(`.device[data-device="${id}"]`);
    button.setAttribute("aria-pressed", String(on));
    button.querySelector(".device-state").textContent = capitalise(on ? device(id).on : device(id).off);
    if (id === changed) {
      button.classList.remove("changed");
      void button.offsetWidth;  // restart the animation
      button.classList.add("changed");
    }
  }
}

// Shows the room as it is, without playing the switching animations: for when the page opens
// or comes back, where nothing has just been switched.
function showRoom(devices) {
  const room = $("room");
  room.classList.add("still");
  render(devices);
  room.getBoundingClientRect();  // apply the state now, while transitions are off
  setTimeout(() => room.classList.remove("still"));  // a timer, not a frame: it also runs in a background tab
}

function caption(text) {
  const line = $("home-caption");
  line.textContent = text;
  line.classList.add("fresh");
}

async function toggle(id) {
  try {
    await api("POST", "/api/home", { device: id });  // the "home" event redraws the room
  } catch (error) {
    caption(`Couldn't switch ${nameInSentence(id)}: ${error.message}`);
  }
}

// ---------- live updates ----------


async function refreshConfig() {
  state.config = await api("GET", "/api/config");
  showGestures();
}

// Each page holds one connection for live updates, and a browser keeps at most 6 open to
// app.py. The connection closes the moment the page is left (Chrome keeps a page you leave
// alive for the Back button), and opens again, with the room's state fetched afresh, if the
// page comes back. See listen() in app.js.
function listen() {
  let events = openEvents();
  window.addEventListener("pagehide", () => events.close());
  window.addEventListener("pageshow", async (event) => {
    if (!event.persisted) return;
    events = openEvents();
    showRoom((await api("GET", "/api/home")).devices);
  });
}

function openEvents() {
  const events = new EventSource("/api/events");
  events.addEventListener("status", (event) => Shared.showStatus(JSON.parse(event.data)));
  events.addEventListener("home", (event) => {
    const data = JSON.parse(event.data);
    render(data.devices, data.changed);
    const did = whatHappened(data.changed, data.devices[data.changed]);
    caption(data.by ? `${data.by} ${did}.` : `You ${did}.`);
  });
  events.addEventListener("result", async (event) => {
    const result = JSON.parse(event.data);
    await refreshConfig().catch(() => {});  // the gestures may have been changed on the Wand page
    const action = state.config?.gestures[result.label]?.action;
    if (result.label === "UNKNOWN") caption("That cast matched no gesture.");
    else if (action?.type !== "home") caption(`${result.label} isn't linked to anything in this room.`);
    // a gesture linked to a device is described by the "home" event that follows
  });
  events.onerror = () => Shared.lostContact();
  return events;
}

async function start() {
  wireTheme();
  const [meta, config, home] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/config"), api("GET", "/api/home")]);
  Object.assign(state, { meta, config });
  buildDevices();
  showRoom(home.devices);
  listen();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshConfig().catch(() => {});
  });
}

start().catch((error) => caption(`Couldn't load the room: ${error.message}`));
