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

  function showStatus(status) {
    lastStatus = status;
    const connected = status.connected;
    $("link-dot").className = "dot" + (connected ? " connected" : "");
    $("link-text").textContent = !connected ? "No wand connected"
      : status.mode === "simulated" ? "Simulated wand connected" : "Wand connected";
    // The wand's own state shows only while a wand is connected (style.css hides OFFLINE).
    const chip = $("wand-state");
    chip.textContent = connected ? status.wand_state : "";
    chip.dataset.state = connected ? status.wand_state : "OFFLINE";
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
    $("wand-state").dataset.state = "OFFLINE";
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

  // ---------- the page tabs ----------
  // The page you are on is shaded and underlined (.tab-mark in style.css). When you switch
  // pages, the shade starts under the tab you came from and slides across to this one, so it
  // looks as if it moved from one tab to the other.

  function wireTabs() {
    const nav = document.querySelector(".pages");
    const mark = nav?.querySelector(".tab-mark");
    const current = nav?.querySelector('a[aria-current="page"]');
    if (!mark || !current) return;
    const KEY = "spellwand-tab-from";   // which tab was left, and when
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

    for (const tab of nav.querySelectorAll("a")) {
      tab.addEventListener("click", () => {
        try {
          sessionStorage.setItem(KEY, JSON.stringify({ from: current.getAttribute("href"), at: Date.now() }));
        } catch (error) { /* private window */ }
      });
    }
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
  return { showStatus, lostContact, toast };
})();
