// What every page shares: the top bar (templates/_header.html: the page tabs, the wand's
// connection and state, the connect buttons), the simulated wand's bar (_sim.html) and the
// message box (toast). The page's own script passes it each status from app.py:
// Shared.showStatus(status). Everything is inside Shared, so the page scripts' own names
// ($, api, ...) do not clash.

const Shared = (() => {
  const $ = (id) => document.getElementById(id);
  let lastStatus = null;

  // ---------- messages ----------

  let toastTimer = null;
  function toast(text, isError = false) {
    const box = $("toast");
    box.textContent = text;
    box.className = "toast show" + (isError ? " error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (box.className = "toast"), isError ? 6000 : 3500);
  }

  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }

  // ---------- the connection ----------

  // The wand in one phrase, with a dot: hollow with no wand, green when ready, and while busy the
  // colour the wand's own light shows (blue casting, amber waiting). _header.html says the same.
  function describeWand(status) {
    if (!status.connected) return ["", "No wand connected"];
    const who = status.mode === "simulated" ? "Simulated wand" : "Wand";
    if (status.recording) return ["casting", `Recording ${gestureName(status.recording)}`];
    if (status.wand_state === "CASTING") return ["casting", `${who} casting`];
    if (status.wand_state === "INFLIGHT") return ["waiting", `${who} waiting for the Mac`];
    return ["ready", `${who} ready`];
  }

  function showStatus(status) {
    lastStatus = status;
    const connected = status.connected;
    const [dot, phrase] = describeWand(status);
    $("link-dot").className = dot ? `dot ${dot}` : "dot";
    $("link-text").textContent = phrase;
    $("connect-ble").hidden = connected;
    $("connect-sim").hidden = connected;
    $("disconnect").hidden = !connected;
    // The simulated wand's toolbar: there while it is connected, ready while it is idle. The
    // motion being cast stays lit until the wand is idle again.
    const simulated = status.mode === "simulated";
    $("sim-panel").hidden = !simulated;
    document.body.classList.toggle("has-sim", simulated);   // room under it at the page's end
    const idle = connected && status.wand_state === "IDLE" && !status.recording;
    for (const button of document.querySelectorAll("[data-motion]")) {
      button.disabled = !idle;
      if (idle) button.classList.remove("casting");
    }
  }

  function lostContact() {
    $("link-dot").className = "dot";
    $("link-text").textContent = "Lost contact with app.py. Is it still running?";
  }

  async function attempt(action) {
    try {
      await action();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function wireConnection() {
    $("connect-ble").addEventListener("click", () => attempt(async () => {
      $("connect-ble").disabled = true;
      $("link-dot").className = "dot searching";
      $("link-text").textContent = "Looking for the wand (up to 10 s)…";
      try {
        await post("/api/connect", { mode: "ble" });
      } finally {
        $("connect-ble").disabled = false;
        if (lastStatus) showStatus(lastStatus);
      }
    }));
    $("connect-sim").addEventListener("click", () => attempt(() => post("/api/connect", { mode: "simulated" })));
    $("disconnect").addEventListener("click", () => attempt(() => post("/api/disconnect")));
    for (const button of document.querySelectorAll("[data-motion]")) {
      button.addEventListener("click", () => attempt(async () => {
        button.classList.add("casting");
        try {
          await post("/api/simulate", { motion: button.dataset.motion });
        } catch (error) {
          button.classList.remove("casting");
          throw error;
        }
      }));
    }
  }

  // ---------- names ----------
  // A gesture's label is an identifier (CIRCLE, HORIZONTAL_LINE, UNKNOWN): it names files, goes to
  // the wand and is typed in settings. Where people read it, it is written as words.
  function gestureName(label) {
    if (!label) return label;
    const words = label.toLowerCase().replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  // ---------- the theme ----------
  // Light, dark, or the system's (the default). templates/_theme.html picks it before the page is
  // drawn; the switch changes it and remembers it. A page that draws its own colours (charts)
  // asks to be told: Shared.onThemeChange(redraw).

  const themeListeners = [];
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  let themeFade = null;

  function showThemeSetting() {
    const setting = document.documentElement.dataset.themeSetting;
    for (const button of document.querySelectorAll("[data-theme-choice]")) {
      button.setAttribute("aria-pressed", String(button.dataset.themeChoice === setting));
    }
  }

  function applyTheme(setting) {
    const root = document.documentElement;
    const theme = setting === "system" ? (systemDark.matches ? "dark" : "light") : setting;
    root.dataset.themeSetting = setting;
    showThemeSetting();
    if (root.dataset.theme === theme) return;
    root.classList.add("theme-fade");  // style.css lets the colours cross-fade while this is on
    clearTimeout(themeFade);
    themeFade = setTimeout(() => root.classList.remove("theme-fade"), 300);
    root.dataset.theme = theme;
    for (const listener of themeListeners) listener(theme);
  }

  function wireTheme() {
    for (const button of document.querySelectorAll("[data-theme-choice]")) {
      button.addEventListener("click", () => {
        const setting = button.dataset.themeChoice;
        try {
          if (setting === "system") localStorage.removeItem("spellwand-theme");
          else localStorage.setItem("spellwand-theme", setting);
        } catch (error) { /* private window */ }
        applyTheme(setting);
      });
    }
    systemDark.addEventListener("change", () => {
      if (document.documentElement.dataset.themeSetting === "system") applyTheme("system");
    });
    showThemeSetting();
  }

  // ---------- panels over the page: Dataset, Settings ----------
  // A panel opens from its button in the top bar and closes with its ×, Escape, or the same
  // button. It leaves the page usable behind it (the motion view stays in sight and can be
  // turned), so a press outside does not close it. One is open at a time. A button whose panel is
  // on another page goes there and opens it (the panel's id after # in the address).

  const openerOf = (drawer) => document.querySelector(`[data-drawer="${drawer.id}"]`);

  function openDrawer(drawer) {
    for (const other of document.querySelectorAll(".drawer:not([hidden])")) {
      if (other !== drawer) closeDrawer(other, false);
    }
    drawer.hidden = false;
    // The simulated wand's toolbar centres itself in the room the panel leaves (style.css).
    document.body.style.setProperty("--drawer-space", `${drawer.offsetWidth + 8}px`);
    openerOf(drawer)?.setAttribute("aria-expanded", "true");
    drawer.querySelector(".drawer-close").focus();
  }

  function closeDrawer(drawer, returnFocus = true) {
    if (drawer.hidden) return;
    drawer.hidden = true;
    document.body.style.removeProperty("--drawer-space");
    const opener = openerOf(drawer);
    opener?.setAttribute("aria-expanded", "false");
    if (returnFocus) opener?.focus();
  }

  function wireDrawers() {
    for (const opener of document.querySelectorAll("[data-drawer]")) {
      opener.addEventListener("click", () => {
        const drawer = $(opener.dataset.drawer);
        if (drawer) {
          if (drawer.hidden) openDrawer(drawer);
          else closeDrawer(drawer);
          return;
        }
        rememberTabLeft();   // the page tabs' shade slides across, as when a tab is pressed
        location.href = `${opener.dataset.drawerPage}#${opener.dataset.drawer}`;
      });
    }
    for (const button of document.querySelectorAll("[data-close-drawer]")) {
      button.addEventListener("click", () => closeDrawer(button.closest(".drawer")));
    }
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;   // the colour chooser goes first
      const open = document.querySelector(".drawer:not([hidden])");
      if (open) closeDrawer(open);
    });
    const asked = location.hash ? document.getElementById(location.hash.slice(1)) : null;
    if (asked?.classList.contains("drawer")) {
      history.replaceState(null, "", location.pathname);
      openDrawer(asked);
    }
  }

  // ---------- the page tabs ----------
  // The page you are on is shaded and underlined (.tab-mark in style.css). When you switch
  // pages, the shade starts under the tab you came from and slides across to this one, so it
  // looks as if it moved from one tab to the other.

  const TAB_KEY = "spellwand-tab-from";   // which tab was left, and when

  // Notes which page is being left, so the next page's shade can start under its tab.
  function rememberTabLeft() {
    const current = document.querySelector('.pages a[aria-current="page"]');
    if (!current) return;
    try {
      sessionStorage.setItem(TAB_KEY, JSON.stringify({ from: current.getAttribute("href"), at: Date.now() }));
    } catch (error) { /* private window */ }
  }

  function wireTabs() {
    const nav = document.querySelector(".pages");
    const mark = nav?.querySelector(".tab-mark");
    const current = nav?.querySelector('a[aria-current="page"]');
    if (!mark || !current) return;
    const KEY = TAB_KEY;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Puts the shade under `link`, at once (still) or sliding there.
    function placeUnder(link, still) {
      mark.classList.toggle("still", still);
      mark.style.width = `${link.offsetWidth}px`;
      mark.style.transform = `translateX(${link.offsetLeft}px)`;
      for (const tab of nav.querySelectorAll("a")) tab.classList.toggle("under-mark", tab === link);
      if (still) mark.getBoundingClientRect();  // apply it now, before any slide starts
    }

    // The tab this page was opened from, if the user switched here a moment ago.
    function tabCameFrom() {
      let left = null;
      try {
        left = JSON.parse(sessionStorage.getItem(KEY));
        sessionStorage.removeItem(KEY);
      } catch (error) { /* private window */ }
      if (!left || Date.now() - left.at > 3000) return null;
      const tab = nav.querySelector(`a[href="${left.from}"]`);
      return tab && tab !== current ? tab : null;
    }

    nav.classList.add("has-mark");
    const from = reduceMotion ? null : tabCameFrom();
    if (from) {
      placeUnder(from, true);
      placeUnder(current, false);
    } else {
      placeUnder(current, true);
    }

    for (const tab of nav.querySelectorAll("a")) tab.addEventListener("click", rememberTabLeft);
    // The tabs change width when the typeface finishes loading (this also runs at once if it has
    // already loaded, so it must not cut a slide short) or when the window is resized.
    document.fonts.ready.then(() => placeUnder(current, false));
    window.addEventListener("resize", () => placeUnder(current, true));
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) placeUnder(current, true);  // back from the browser's cache: no slide
    });
  }

  wireTabs();
  wireConnection();
  wireTheme();
  wireDrawers();
  return { showStatus, lostContact, toast, gestureName, onThemeChange: (listener) => themeListeners.push(listener) };
})();
