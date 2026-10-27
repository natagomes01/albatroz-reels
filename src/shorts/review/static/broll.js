"use strict";
// B-roll section of each approved clip's drawer (S8B spec 7). Loaded after app.js and uses its
// globals: S, $, api, queued, applyReply, decision, statusOf, showError, note, render, POLL_MS.

let B = null;               // /api/broll worker state; null = this page has no B-roll
const BD = {};              // clip id -> /api/broll/candidates/<id> reply (times, warnings, candidates)
const loadingBD = new Set();
const sections = {};        // clip id -> its section element, redrawn in place
let brollTimer = null;
let brollSelect = null;     // {clip, first, last} while the owner selects words for an own moment
let ownFiles = null;        // /api/broll/files, read once per page
const LAYOUTS = [["full", "full screen"], ["split", "split"]];
const FITS = [["cover", "fill"], ["whole", "whole"]];
const PANS = { ltr: "left to right", rtl: "right to left", ttb: "top to bottom", btt: "bottom to top", still: "still" };
const UPLOAD_ACCEPT = "image/jpeg,image/png,video/mp4,video/quicktime";

// ---- worker state and polling ----
const reqSeq = {};          // clip id -> latest details request number (older replies are ignored)
const sigs = {};            // clip id -> signature of what its section last drew
const deferred = new Set(); // clips whose section changed while the owner was working in it
const watch = {};           // clip id -> ticks left to look for a task that ended between two polls
const liveFocus = {};       // "clip|moment" -> framing focus the owner just set, ahead of the saved reply
const pendingSaves = {};    // "clip|moment" -> framing saves not yet answered
let dragging = false;
let tickFails = 0;

// pure helpers (run by tests/test_review_broll_static.py under node)
function nudgeFocus(base, key) {
  const step = { ArrowLeft: [-0.02, 0], ArrowRight: [0.02, 0], ArrowUp: [0, -0.02], ArrowDown: [0, 0.02] }[key];
  if (!step) return null;
  return [clamp01(base[0] + step[0]), clamp01(base[1] + step[1])];
}
function endedClips(before, after) {
  return Object.entries(after).filter(([id, s]) =>
    ["queued", "working"].includes(before[id]?.state) && ["idle", "failed"].includes(s.state)).map(([id]) => id);
}
function sectionSig(st, moments, details) { return JSON.stringify([st, moments, details]); }

async function refreshBroll() {
  try { B = await api("/api/broll"); } catch (err) { B = null; return; }   // no queue: no section
  if (S) render();
  if (brollBusy()) pollBroll();
}
function brollBusy() {
  return (!!B && Object.values(B.clips).some((s) => s.state === "queued" || s.state === "working")) ||
         Object.keys(watch).length > 0;
}
function pollBroll(id, delay = POLL_MS) {
  if (id) watch[id] = 3;
  clearTimeout(brollTimer);
  brollTimer = setTimeout(tickBroll, delay);
}
async function tickBroll() {
  let delay = POLL_MS;
  try {
    const before = B ? B.clips : {};
    B = await api("/api/broll");
    const refresh = new Set(endedClips(before, B.clips));
    for (const id of Object.keys(watch)) {
      refresh.add(id);
      const busy = ["queued", "working"].includes((B.clips[id] || {}).state);
      if (!busy && --watch[id] <= 0) delete watch[id];
      if (busy) delete watch[id];   // seen running: the ended-clips rule takes over
    }
    if (refresh.size) {   // a suggestion or a pick changed review.json: take those clips' entries
      const fresh = await api("/api/job");
      for (const id of refresh) {
        if (fresh.review.decisions[id]) S.review.decisions[id] = fresh.review.decisions[id];
        const c = S.candidates.find((x) => x.id === id);
        if (c) loadDetails(c);
      }
      syncRenders();         // drawer heads in place (the B-roll chip); no full redraw, so no focus loss
    }
    for (const id of Object.keys(sections)) redrawSection(id);
    tickFails = 0;
  } catch (err) {
    tickFails += 1;
    delay = POLL_MS * Math.min(1 + tickFails, 5);
    note(`B-roll status not read (${err.message || err}); trying again`);
  } finally {
    if (brollBusy() || tickFails) pollBroll(undefined, delay);
  }
}
async function loadDetails(c) {
  const mine = (reqSeq[c.id] = (reqSeq[c.id] || 0) + 1);
  loadingBD.add(c.id);
  let reply;
  try {
    reply = await api(`/api/broll/candidates/${c.id}`);
  } catch (err) {
    reply = { error: err.message };
  }
  if (mine !== reqSeq[c.id]) return;          // a newer request is on its way
  loadingBD.delete(c.id);
  BD[c.id] = reply;
  redrawSection(c.id);
}
// Redraw one clip's section. A poll tick (no force) skips it when nothing changed, and never rebuilds
// it while the owner has focus inside it or is dragging; it is redrawn when the focus leaves.
// An edit's reply (force) rebuilds it and puts the focus back on the same control.
function redrawSection(id, force = false) {
  const c = S.candidates.find((x) => x.id === id);
  const box = sections[id];
  if (!c || !box || !box.isConnected) return;
  const sig = sectionSig(B && B.clips[id], decision(c).broll, BD[id]);
  if (!force && sig === sigs[id]) return;
  if (!force && (dragging || box.contains(document.activeElement))) { deferred.add(id); return; }
  deferred.delete(id);
  const key = box.contains(document.activeElement) ? document.activeElement.dataset.bkey : null;
  sigs[id] = sig;
  fillBroll(box, c);
  if (key) {
    const again = box.querySelector(`[data-bkey="${key}"]`) || box.querySelector('[data-bkey$="|select"]');
    if (again) again.focus();
  }
}

// ---- hooks called by app.js ----
function brollSection(c) {
  if (!B || statusOf(c) !== "approved") return "";
  const box = $("div", { class: "broll" });
  sections[c.id] = box;
  sigs[c.id] = sectionSig(B.clips[c.id], decision(c).broll, BD[c.id]);
  box.addEventListener("focusout", () => setTimeout(() => {
    if (deferred.has(c.id) && !dragging && !box.contains(document.activeElement)) redrawSection(c.id);
  }, 0));
  fillBroll(box, c);
  if (!BD[c.id] && !loadingBD.has(c.id)) loadDetails(c);
  return box;
}
function brollChip(c) {
  const n = (decision(c).broll || []).filter((m) => m.pick).length;
  return n ? $("span", { class: "chip broll" }, `B-roll ${n}`) : null;
}
function brollMarked(c, i) {
  if (!brollSelect || brollSelect.clip !== c.id || brollSelect.first === undefined) return false;
  const last = brollSelect.last ?? brollSelect.first;
  return i >= brollSelect.first && i <= last;
}
function brollWordClick(c, i) {
  if (!brollSelect || brollSelect.clip !== c.id) return false;
  const s = brollSelect;
  if (s.retime) {      // retiming one moment: the second click applies it
    if (s.first === undefined) { brollSelect = { ...s, first: i }; renderKeepFocus(); redrawSection(c.id, true); }
    else retimeMoment(c, s.retime, Math.min(s.first, i), Math.max(s.first, i));
    return true;
  }
  if (s.first === undefined || s.last !== undefined) brollSelect = { clip: c.id, first: i };
  else brollSelect = { clip: c.id, first: Math.min(s.first, i), last: Math.max(s.first, i) };
  renderKeepFocus();
  return true;
}

// ---- the section ----
function fillBroll(box, c) {
  const st = (B && B.clips[c.id]) || { state: "idle" };
  const d = BD[c.id] || {};
  const moments = decision(c).broll || [];
  const head = $("div", { class: "row broll-head" }, $("strong", {}, "B-roll"));
  const running = st.state === "queued" || st.state === "working";
  if (running) {
    head.append($("span", { class: "hint" }, st.task === "suggest" ? "Suggesting B-roll…" : "Working…"));
  }
  // the server keeps the error of an earlier task while the clip is queued or working again
  if (st.state === "failed" || (running && st.error)) head.append($("span", { class: "warn" }, st.error || "failed"));
  if (!running) {
    if (st.state === "failed") head.append($("button", { onclick: () => suggestBroll(c) }, "Try again"));
    head.append($("span", { class: "hint" }, `${moments.length} moment${moments.length === 1 ? "" : "s"}`),
                $("button", { onclick: () => suggestBroll(c) }, d.result ? "Suggest again" : "Suggest B-roll"));
  }
  const selecting = !!brollSelect && brollSelect.clip === c.id && !brollSelect.retime;
  head.append($("button", { class: selecting ? "on" : "", "aria-pressed": String(selecting),
                            "data-bkey": `${c.id}|select`, onclick: () => toggleSelect(c) }, "Select words"));
  if (selecting && brollSelect.last !== undefined) {
    head.append($("button", { onclick: () => addOwnMoment(c) }, "B-roll here"));
  }
  box.replaceChildren(head);
  if (d.error) box.append($("div", { class: "warn" }, d.error));
  for (const m of moments) box.append(momentRow(c, m, d));
  if (d.credits) {
    box.append($("div", { class: "row" }, $("span", { class: "hint" }, "Credit"),
                 $("code", { class: "credit" }, d.credits),
                 $("button", { onclick: () => copyText(d.credits) }, "Copy")));
  }
  const errs = (d.result && d.result.errors) || [];
  if (errs.length) box.append($("div", { class: "warn" }, errs.join(" · ")));
}
function momentRow(c, m, d) {
  const range = d.ranges && d.ranges[m.id];
  const words = S.words.slice(m.first, m.last + 1).map((w) => w[1]).join(" ");
  const row = $("div", { class: "moment" });
  row.addEventListener("dragover", (ev) => ev.preventDefault());
  row.addEventListener("drop", (ev) => {
    ev.preventDefault();
    const file = ev.dataTransfer.files[0];
    if (file) uploadFile(c, m, file);
  });
  row.append($("div", { class: "row" },
    $("span", { class: `chip ${m.origin === "owner" ? "mine" : "suggested"}` }, m.origin === "owner" ? "mine" : "suggested"),
    $("span", { class: "hint" }, range ? `${range[0].toFixed(1)}–${range[1].toFixed(1)} s` : ""),
    $("span", { class: "bwords" }, `“${words}”`),
    selectFor(c, m, "layout", LAYOUTS, "Layout"),
    selectFor(c, m, "fit", FITS, "Fit"),
    selectFor(c, m, "pan", pansFor(m), "Motion"),
    $("button", { "data-bkey": `${c.id}|${m.id}|drop`, onclick: () => dropMoment(c, m) }, "Drop")));
  row.append(retimeRow(c, m));
  if (m.note) row.append($("div", { class: "hint" }, m.note));
  for (const p of (d.problems && d.problems[m.id]) || []) row.append($("div", { class: "warn" }, p));
  if (m.pick) {
    const what = m.pick.source === "own" ? m.pick.file : `${m.pick.source} · ${m.pick.title}`;
    row.append($("div", { class: "hint", "data-bkey": `${c.id}|${m.id}|chosen` }, `Chosen: ${what}`));
  }
  row.append($("div", { class: "row" }, preview(c, m), candidateGrid(c, m, d)));
  row.append(searchRow(c, m));
  return row;
}
function retimeRow(c, m) {   // start and end by clicking words in the text above: first word, then last
  const on = !!brollSelect && brollSelect.clip === c.id && brollSelect.retime === m.id;
  const row = $("div", { class: "row" }, $("span", { class: "hint" }, "Timing"),
    $("button", { class: on ? "on" : "", "aria-pressed": String(on), "data-bkey": `${c.id}|${m.id}|retime`,
                  onclick: () => toggleRetime(c, m) }, "Change words"));
  if (on) {
    row.append($("span", { class: "hint" }, brollSelect.first === undefined
      ? "Click the first word in the text above" : "Now click the last word"));
  }
  return row;
}
function toggleRetime(c, m) {
  const on = brollSelect && brollSelect.clip === c.id && brollSelect.retime === m.id;
  brollSelect = on ? null : { clip: c.id, retime: m.id };
  renderKeepFocus();
  redrawSection(c.id, true);
}
function retimeMoment(c, id, first, last) {
  brollSelect = null;
  renderKeepFocus();
  return saveList(c, (list) => list.map((x) => (x.id === id ? { ...x, first, last } : x)));
}
function pansFor(m) {
  const p = m.pick;
  if (!p || p.kind === "video" || m.fit === "whole") return [["still", PANS.still]];
  const [tw, th] = m.layout === "full" ? [1080, 1920] : [1080, 960];
  const keys = p.w / p.h > tw / th ? ["ltr", "rtl", "still"] : ["ttb", "btt", "still"];
  return keys.map((k) => [k, PANS[k]]);
}
function selectFor(c, m, key, options, label) {
  const sel = $("select", { "aria-label": `${label} of this B-roll moment`, "data-bkey": `${c.id}|${m.id}|${key}` });
  for (const [value, text] of options) sel.append($("option", { value }, text));
  sel.value = m[key];
  sel.addEventListener("change", () => {
    const patch = { [key]: sel.value };
    if (key !== "pan") patch.pan = "still";          // a new layout or fit may change the pan axis
    saveMoment(c, m.id, patch);
  });
  return sel;
}
function candidateGrid(c, m, d) {
  const grid = $("div", { class: "bgrid" });
  const cands = (d.result && d.result.candidates && d.result.candidates[m.id]) || [];
  for (const cand of cands) {
    const chosen = !!m.pick && m.pick.source === cand.source && m.pick.id === cand.id;
    const cap = `${cand.source} · ${cand.license}` + (cand.kind === "video" ? ` · ${Math.round(cand.duration)} s` : "");
    grid.append($("button", { class: `tile ${chosen ? "on" : ""}`, "aria-pressed": String(chosen), title: cand.title,
                              "data-bkey": `${c.id}|${m.id}|tile|${cand.key}`, onclick: () => pickCandidate(c, m, cand) },
      $("img", { src: `/media/broll-thumb/${cand.key}.jpg`, alt: cand.title, loading: "lazy" }),
      $("span", { class: "hint" }, cap)));
  }
  return grid;
}
function searchRow(c, m) {
  const input = $("input", { class: "bterms", "data-bkey": `${c.id}|${m.id}|terms`, value: (m.terms || []).join(", "), "aria-label": "Search terms" });
  const file = $("input", { type: "file", accept: UPLOAD_ACCEPT, class: "bfile", "data-bkey": `${c.id}|${m.id}|file`, "aria-label": "Use my file" });
  file.addEventListener("change", () => { if (file.files[0]) uploadFile(c, m, file.files[0]); });
  const list = $("select", { "data-bkey": `${c.id}|${m.id}|files`, "aria-label": "Files already in the B-roll folder" }, $("option", { value: "" }, "Use my file"));
  list.addEventListener("focus", () => fillFiles(list), { once: true });
  list.addEventListener("change", () => { if (list.value) useFile(c, m, list.value); });
  return $("div", { class: "row" }, input,
    $("button", { "data-bkey": `${c.id}|${m.id}|search`, onclick: () => searchMoment(c, m, input.value) }, "Search"),
    $("label", { class: "hint" }, "Use my file", file), list);
}
async function fillFiles(list) {
  try {
    ownFiles = ownFiles || (await api("/api/broll/files")).files;
    for (const f of ownFiles) list.append($("option", { value: f.name }, f.name));
  } catch (err) { showError(err); }
}

// ---- framing preview (spec 7.3) ----
function preview(c, m) {
  const pct = (v) => `${Math.round(v * 100)}%`;
  const mkey = `${c.id}|${m.id}`;
  const focusNow = () => liveFocus[mkey] || m.focus;
  const f0 = focusNow();
  const frame = $("div", { class: `bpreview ${m.layout}`, tabindex: "0", role: "slider", "data-bkey": `${mkey}|frame`,
                           "aria-label": "B-roll framing: drag, or use the arrow keys",
                           "aria-valuetext": `${pct(f0[0])} across, ${pct(f0[1])} down` });
  const img = $("div", { class: "bimage" });
  const show = (f) => {
    img.style.backgroundPosition = `${pct(f[0])} ${pct(f[1])}`;
    frame.setAttribute("aria-valuetext", `${pct(f[0])} across, ${pct(f[1])} down`);
  };
  if (m.pick) {
    const src = m.pick.kind === "video" ? `/media/broll-thumb/${m.pick.source}-${m.pick.id}.jpg`
                                        : `/media/broll/${m.pick.file}`;
    img.style.backgroundImage = `url("${src}")`;
    img.style.backgroundSize = m.fit === "whole" ? "contain" : "cover";
    img.style.backgroundPosition = `${pct(f0[0])} ${pct(f0[1])}`;
  }
  frame.append(img, $("div", { class: "bspeaker" }), $("div", { class: "bcaption" }));
  let drag = null;
  frame.addEventListener("pointerdown", (ev) => {
    const f = focusNow();
    drag = { x: ev.clientX, y: ev.clientY, fx: f[0], fy: f[1] };
    dragging = true;
    frame.setPointerCapture(ev.pointerId);
  });
  frame.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const r = frame.getBoundingClientRect();
    drag.now = [clamp01(drag.fx - (ev.clientX - drag.x) / r.width), clamp01(drag.fy - (ev.clientY - drag.y) / r.height)];
    show(drag.now);
  });
  const endDrag = () => {
    dragging = false;
    if (drag && drag.now) saveFocus(c, m, drag.now);
    drag = null;
  };
  frame.addEventListener("pointerup", endDrag);
  frame.addEventListener("pointercancel", endDrag);
  frame.addEventListener("keydown", (ev) => {
    const next = nudgeFocus(focusNow(), ev.key);
    if (!next) return;
    ev.preventDefault();
    show(next);                       // at once, so a second press adds to this one
    saveFocus(c, m, next);
  });
  return frame;
}
function saveFocus(c, m, focus) {
  const k = `${c.id}|${m.id}`;
  liveFocus[k] = focus;
  pendingSaves[k] = (pendingSaves[k] || 0) + 1;
  return saveMoment(c, m.id, { focus }).finally(() => {
    if (--pendingSaves[k] <= 0) { delete pendingSaves[k]; delete liveFocus[k]; }
  });
}
function renderKeepFocus() {   // the words block must redraw (selection marks): keep the focused B-roll control
  const key = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.bkey : null;
  render();
  if (key) { const again = document.querySelector(`[data-bkey="${key}"]`); if (again) again.focus(); }
}
function clamp01(v) { return Math.round(Math.min(Math.max(v, 0), 1) * 1000) / 1000; }

// ---- saves ----
function saveMoment(c, id, patch) {
  return saveList(c, (list) => list.map((x) => (x.id === id ? { ...x, ...patch } : x)));
}
function dropMoment(c, m) { return saveList(c, (list) => list.filter((x) => x.id !== m.id)); }
function saveList(c, change) {
  // the whole list goes out through the clip's save queue, read when its turn comes (S5)
  return queued(c, async () => {
    try {
      applyReply(c, await api("/api/edit", { id: c.id, edit: { broll: change(decision(c).broll || []) } }), false);
      afterEdit(c);
    } catch (err) { showError(err); }
  });
}
function afterEdit(c) {   // a B-roll edit never redraws the page: the chip in place, this clip's section in place
  syncRenders();
  redrawSection(c.id, true);
  loadDetails(c);
}
function toggleSelect(c) {
  brollSelect = brollSelect && brollSelect.clip === c.id ? null : { clip: c.id };
  renderKeepFocus();
}
function addOwnMoment(c) {
  const { first, last } = brollSelect;
  brollSelect = null;
  renderKeepFocus();     // the word marks go
  return saveList(c, (list) => {
    const n = Math.max(0, ...list.map((x) => (/^o\d+$/.test(x.id) ? Number(x.id.slice(1)) : 0))) + 1;
    return [...list, { id: `o${n}`, origin: "owner", first, last, layout: "full", fit: "cover", pan: "still",
                       focus: [0.5, 0.5], terms: [], note: "", pick: null }];
  });
}
function suggestBroll(c) {
  return api("/api/broll/suggest", { id: c.id }).then((st) => { B = st; redrawSection(c.id, true); pollBroll(c.id); })
    .catch(showError);
}
function searchMoment(c, m, text) {
  const terms = text.split(",").map((t) => t.trim()).filter(Boolean).slice(0, 3);
  if (!terms.length) return showError(new Error("type a search term first"));
  return api("/api/broll/search", { id: c.id, moment: m.id, terms })
    .then((st) => { B = st; redrawSection(c.id, true); pollBroll(c.id); }).catch(showError);
}
function pickCandidate(c, m, cand) {
  return api("/api/broll/pick", { id: c.id, moment: m.id, candidate: cand.key })
    .then((st) => { B = st; redrawSection(c.id, true); pollBroll(c.id); }).catch(showError);
}
async function uploadFile(c, m, file) {
  try {
    const r = await fetch("/api/broll/upload", { method: "POST", body: file,
                                                 headers: { "Content-Type": file.type, "X-File-Name": encodeURIComponent(file.name) } });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || r.statusText);
    ownFiles = null;
    await useFile(c, m, data.name);
  } catch (err) { showError(err); }
}
function useFile(c, m, name) {
  return queued(c, async () => {
    try {
      applyReply(c, await api("/api/broll/use-file", { id: c.id, moment: m.id, name }), false);
      afterEdit(c);
    } catch (err) { showError(err); }
  });
}
function copyText(text) {
  navigator.clipboard.writeText(text).then(() => note("Credit copied"), showError);
}
