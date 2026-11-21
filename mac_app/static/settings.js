// The Settings panel (templates/_settings.html), on every page: the rejection threshold, and each
// gesture's LED colour and action. It loads the settings from app.py, and saves them back.
// After a save it tells the page, so the page can follow: an event "spellwand:config" on window,
// with the new settings as its detail.
// Everything is inside Settings, so the page scripts' own names ($, el, ...) do not clash.

const Settings = (() => {
  const NEW_GESTURE_COLOR = "#b48cff";  // the LED colour a newly added gesture starts with
  // Colours the wand's RGB LED shows well, for the colour chooser.
  const LED_COLORS = [
    "#ff0000", "#ff4000", "#ffaa00", "#ffe600", "#00c828", "#00d6a0",
    "#00b4ff", "#0050ff", "#7a3cff", "#d028ff", "#ff2d8a", "#ffffff",
  ];
  const $ = (id) => document.getElementById(id);
  const nameOf = (label) => Shared.gestureName(label);
  const state = { meta: null, config: null };

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

  // ---------- colour chooser ----------
  // A colour square is a button that holds its colour as its value. Pressing it opens one small
  // panel under it: the colours the wand's LED shows well, and a field for any other colour.

  const colors = { box: null, hex: null, target: null };

  function setSwatch(button, color) {
    button.value = color;
    button.style.setProperty("--swatch", color);
  }

  function swatchButton(color, name, className) {
    const button = el("button", { type: "button", className: `swatch-button ${className}`,
      "aria-label": `${nameOf(name)} colour`, "aria-haspopup": "dialog" });
    setSwatch(button, color);
    button.addEventListener("click", () => openColors(button, name));
    return button;
  }

  function buildColors() {
    const presets = LED_COLORS.map((color) => {
      const choice = el("button", { type: "button", className: "swatch-button", title: color, "aria-label": color });
      setSwatch(choice, color);
      choice.addEventListener("click", () => {
        setSwatch(colors.target, color);
        closeColors();
      });
      return choice;
    });
    colors.hex = el("input", { type: "text", maxLength: 7, spellcheck: false, autocomplete: "off", placeholder: "#00aaff" });
    colors.hex.addEventListener("input", () => {   // any other colour, as soon as it is complete
      const color = colors.hex.value.trim().toLowerCase();
      if (!/^#[0-9a-f]{6}$/.test(color)) return;
      setSwatch(colors.target, color);
      markColor(color);
    });
    colors.hex.addEventListener("keydown", (e) => { if (e.key === "Enter") closeColors(); });
    colors.box = el("div", { className: "color-pop", hidden: true }, [
      el("p", { className: "color-title" }),
      el("div", { className: "color-presets" }, presets),
      el("label", { className: "color-hex" }, [el("span", {}, "Other"), colors.hex]),
    ]);
    colors.box.setAttribute("role", "dialog");
    document.body.append(colors.box);

    document.addEventListener("pointerdown", (e) => {   // a press anywhere else closes it
      if (colors.target && !colors.box.contains(e.target) && e.target !== colors.target) closeColors(false);
    });
    // Escape closes the chooser first, and only the chooser (the panel under it stays open).
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && colors.target) {
        e.preventDefault();
        closeColors();
      }
    }, true);
    window.addEventListener("resize", () => { if (colors.target) closeColors(false); });
    // It is placed in the page, so it closes when the panel under it scrolls.
    $("settings-drawer").querySelector(".drawer-body").addEventListener("scroll", () => { if (colors.target) closeColors(false); });
  }

  function markColor(color) {
    for (const choice of colors.box.querySelectorAll(".color-presets button")) {
      choice.setAttribute("aria-pressed", String(choice.value === color));
    }
  }

  function openColors(button, name) {
    if (colors.target === button) return closeColors();
    if (colors.target) closeColors(false);
    colors.target = button;
    button.setAttribute("aria-expanded", "true");
    const box = colors.box;
    box.querySelector(".color-title").textContent = `Colour for ${nameOf(name)}`;
    box.setAttribute("aria-label", `Colour for ${nameOf(name)}`);
    colors.hex.value = button.value;
    markColor(button.value);
    box.hidden = false;

    // Under the square, or above it when there is no room below; never off the side of the page.
    const at = button.getBoundingClientRect();
    const pageWidth = document.documentElement.clientWidth;
    const left = Math.max(12, Math.min(at.left, pageWidth - box.offsetWidth - 12));
    const below = at.bottom + 8 + box.offsetHeight <= window.innerHeight || at.top - 8 - box.offsetHeight < 0;
    const top = below ? at.bottom + 8 : at.top - 8 - box.offsetHeight;
    box.style.left = `${left + window.scrollX}px`;
    box.style.top = `${top + window.scrollY}px`;
    (box.querySelector('[aria-pressed="true"]') ?? colors.hex).focus({ preventScroll: true });
  }

  function closeColors(returnFocus = true) {
    if (!colors.target) return;
    colors.box.hidden = true;
    colors.target.setAttribute("aria-expanded", "false");
    if (returnFocus) colors.target.focus();
    colors.target = null;
  }

  // ---------- the form ----------

  // What a gesture does, as one menu: the plain actions, then the living room's devices as a group
  // ("home:lamp" is "switch the lamp"). An action that needs words (a notification's message, a
  // web address) gets a field on a second line. Returns [the menu, the second line].
  function actionEditor(action) {
    const plain = ["none", "notify", "webhook"].map((value) => el("option", { value }, state.meta.action_types[value]));
    const room = el("optgroup", { label: state.meta.action_types.home },
      state.meta.home_devices.map((d) => el("option", { value: `home:${d.device}` },
        `Switch the ${d.name === d.name.toUpperCase() ? d.name : d.name.toLowerCase()}`)));
    const menu = el("select", { className: "action-type", "aria-label": "Action" }, [...plain, room]);
    menu.value = action.type === "home" ? `home:${action.device}` : action.type;
    const extra = el("div", { className: "action-extra" });
    const renderExtra = () => {
      if (menu.value === "notify") {
        extra.replaceChildren(el("input", { type: "text", className: "action-message", placeholder: "Message to show",
          value: action.message ?? "", maxLength: 200, "aria-label": "Notification message" }));
      } else if (menu.value === "webhook") {
        extra.replaceChildren(el("input", { type: "url", className: "action-url", placeholder: "https://…",
          value: action.url ?? "", "aria-label": "Web address" }));
      } else {
        extra.replaceChildren();
      }
    };
    menu.addEventListener("change", renderExtra);
    renderExtra();
    return [menu, extra];
  }

  // The action a row's menu and field describe, as config.json stores it.
  function readAction(row) {
    const choice = row.querySelector(".action-type").value;
    if (choice.startsWith("home:")) return { type: "home", device: choice.slice("home:".length) };
    if (choice === "notify") return { type: choice, message: row.querySelector(".action-message").value };
    if (choice === "webhook") return { type: choice, url: row.querySelector(".action-url").value };
    return { type: "none" };
  }

  function render() {
    const config = state.config;
    $("threshold").value = config.dtw_threshold;
    setSwatch($("unknown-color"), config.unknown_color);
    $("gesture-rows").replaceChildren(...Object.entries(config.gestures).map(([label, settings]) => {
      const remove = el("button", { type: "button", className: "remove-gesture", title: "Remove",
        "aria-label": `Remove ${nameOf(label)}` });
      remove.innerHTML = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor"'
        + ' stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.75 4.25h10.5M6.25 4.25V2.75h3.5v1.5'
        + 'M4.25 4.25l.6 9h6.3l.6-9M6.75 6.75v4M9.25 6.75v4"/></svg>';
      remove.addEventListener("click", () => {
        state.config = readForm();
        delete state.config.gestures[label];
        render();
        Shared.toast(`Removed ${nameOf(label)}. Its samples stay in the dataset. Press Save settings to apply.`);
      });
      const [menu, extra] = actionEditor(settings.action);
      const row = el("li", { className: "gesture-item" }, [
        swatchButton(settings.color, label, "gesture-color"),
        el("span", { className: "gesture-name" }, nameOf(label)),
        menu,
        remove,
        extra,
      ]);
      row.dataset.label = label;
      return row;
    }));
  }

  function readForm() {
    const gestures = {};
    for (const row of $("gesture-rows").children) {
      gestures[row.dataset.label] = { color: row.querySelector(".gesture-color").value, action: readAction(row) };
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
      Shared.toast("Use 1–16 letters, digits or _, starting with a letter (not UNKNOWN).", true);
      return;
    }
    state.config = readForm();
    if (name in state.config.gestures) {
      Shared.toast(`${nameOf(name)} is already a gesture.`, true);
      return;
    }
    state.config.gestures[name] = { color: NEW_GESTURE_COLOR, action: { type: "none" } };
    $("new-gesture").value = "";
    render();
    $("gesture-rows").lastElementChild.classList.add("new");
    Shared.toast(`Added ${nameOf(name)}. Press Save settings to keep it, then record some examples.`);
  }

  async function save() {
    try {
      state.config = await api("PUT", "/api/config", readForm());
      render();
      Shared.toast("Settings saved.");
      window.dispatchEvent(new CustomEvent("spellwand:config", { detail: state.config }));
    } catch (error) {
      Shared.toast(error.message, true);
    }
  }

  async function start() {
    [state.meta, state.config] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/config")]);
    buildColors();
    $("unknown-color").addEventListener("click", () => openColors($("unknown-color"), "UNKNOWN"));
    $("add-gesture").addEventListener("click", addGesture);
    $("new-gesture").addEventListener("keydown", (e) => { if (e.key === "Enter") addGesture(); });
    $("save-settings").addEventListener("click", save);
    render();
  }

  start().catch((error) => Shared.toast(`Settings couldn't load: ${error.message}`, true));
  return {};
})();
