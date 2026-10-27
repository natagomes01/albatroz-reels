"use strict";
// Theme switch (S6 spec, section 3): LIGHT, DARK or SYSTEM, remembered in this browser only.
// Loaded in <head> before the stylesheets, so a forced theme is set before the first paint.
// It never talks to the server: the choice is a viewer convenience, not part of review.json.
(() => {
  const KEY = "shorts.review.theme";
  const CHOICES = ["light", "dark", "system"];
  const root = document.documentElement;

  function read() {
    try {
      const v = localStorage.getItem(KEY);
      return CHOICES.includes(v) ? v : "system";
    } catch (e) {
      return "system";                 // storage blocked (private window): follow the Mac
    }
  }
  function apply(choice) {
    if (choice === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", choice);
    for (const b of document.querySelectorAll("#theme button")) {
      b.setAttribute("aria-pressed", String(b.dataset.theme === choice));
    }
  }
  function choose(choice) {
    try {
      localStorage.setItem(KEY, choice);
    } catch (e) {
      // not remembered, but still applied to this page
    }
    apply(choice);
    setOpen(false);
  }
  function setOpen(open) {
    const menu = document.getElementById("theme");
    const toggle = document.getElementById("theme-toggle");
    if (!menu || !toggle) return;
    menu.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  }

  apply(read());
  document.addEventListener("DOMContentLoaded", () => {
    for (const b of document.querySelectorAll("#theme button")) {
      b.addEventListener("click", () => choose(b.dataset.theme));
    }
    apply(read());                     // the buttons exist now: mark the active one
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.addEventListener("click", () => setOpen(document.getElementById("theme").hidden));
      document.addEventListener("click", (e) => {
        if (!e.target.closest("#theme-menu")) setOpen(false);
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { setOpen(false); toggle.focus(); }
      });
    }
  });
})();
