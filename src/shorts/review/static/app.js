"use strict";
// Review page (spec 7). Talks to /api/job, /api/decision, /api/edit, /api/renders; plays /media/master.

let S = null;            // state from /api/job
let playing = null;      // {spans: [[a,b],...], i}
let R = { clips: {}, queue: [] };   // render state from /api/renders (S7 spec 3)
let A = null;            // audio panel state from /api/audio (S8 audio spec 6); null = no panel
const player = document.getElementById("player");
const $ = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids) el.append(kid);
  return el;
};
const fmt = (s) => {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(x).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify(body) } : {});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function decision(c) { return (S.review.decisions[c.id] ||= {}); }
function spansOf(c) { return decision(c).segments || c.segments.map((s) => s.snapped); }
function statusOf(c) { return decision(c).status || "pending"; }
// ---- saves (review spec 4.1, 4.2) ----
// One clip's saves go out one at a time, in click order: each click is its own undo step, so
// rapid clicks are normal, and replies landing out of order would leave the card showing an older
// state than review.json. Each save reads the clip's entry when its turn comes.
const queues = {};
function queued(c, fn) {
  const next = (queues[c.id] || Promise.resolve()).then(fn, fn);
  queues[c.id] = next.catch(() => {});
  return next;
}
// Every save, undo and redo answers with the whole decision entry plus the clip's undo and redo
// counts; the local entry is replaced, never patched.
let lastClip = null;      // id of the clip whose last save succeeded: the undo and redo keys act on it
let justSaved = null;    // the clip saved last: its card flashes once on the next render (spec 5.2)
const histButtons = {};   // clip id -> {undo, redo} buttons of its card (filled by card())
function applyReply(c, res, redraw = true) {
  const { undo = 0, redo = 0, estimated_duration, broll_dropped, ...entry } = res;
  S.review.decisions[c.id] = entry;
  if (broll_dropped && broll_dropped.length) {
    note(`B-roll moment ${broll_dropped.join(", ")} dropped: its words left the clip`);
  }
  c.undo = undo;
  c.redo = redo;
  if (estimated_duration !== undefined) c.estimated_duration = estimated_duration;
  lastClip = c.id;
  if (redraw) {
    justSaved = c.id;
    render();
  } else {
    syncHistory();
    flashCard(c);        // title and hook saves keep the focus, so no redraw: replay the flash in place
  }
  refreshRenders();      // an edit can make the clip out of date (S7 spec 4.3)
}
function flashCard(c) {
  const el = histButtons[c.id]?.undo.closest(".card");
  if (!el) return;
  el.classList.remove("saved");
  void el.offsetWidth;   // restart the CSS animation
  el.classList.add("saved");
}
function syncHistory() {
  const byId = Object.fromEntries(S.candidates.map((c) => [c.id, c]));
  for (const [id, b] of Object.entries(histButtons)) {
    const c = byId[id];
    b.undo.disabled = !(c && c.undo);
    b.redo.disabled = !(c && c.redo);
    b.undo.classList.toggle("hot", id === lastClip);
  }
}
function stepHistory(c, action) {
  return queued(c, async () => {
    try {
      applyReply(c, await api(`/api/${action}`, { id: c.id }));
      note(`${action === "undo" ? "Undid" : "Redid"} one change to ${c.id}.`);   // says which key fired
    }
    catch (err) { showError(err); }     // 409 "nothing to undo": nothing was written
  });
}
// ---- words: raw, automatic caption fix (analyze/corrections.json) or the owner's fix ----
// Indices are RAW slot indices everywhere. An automatic fix covers a range of slots. When the owner
// has fixed or removed a slot of that range, the page shows a chooser (review spec 4.4, 4.5): the
// owner's words ("Mine", the default, caption spec 5) or the suggestion when its `first` is in the
// clip's use_auto list.
function useAuto(c) { return decision(c).use_auto || []; }
function hasMine(e, c) {
  const f = decision(c).word_fixes || {};
  for (let s = e.first; s <= e.last; s++) if (f[String(s)] !== undefined) return true;
  return false;
}
function autoOverridden(e, c) {
  return hasMine(e, c) && !useAuto(c).includes(e.first);
}
function slotView(i, c) {
  const a = S.auto_slots[String(i)];
  if (a && hasMine(S.auto_edits[a.edit], c)) return { text: null, flag: "choice", edit: a.edit };
  const f = (decision(c).word_fixes || {})[String(i)];
  if (f !== undefined) return { text: f, flag: f === "" ? "ghost" : "fixed", edit: null };
  if (a) return { text: a.text, flag: "auto", edit: a.edit };
  return { text: S.words[i][1], flag: "raw", edit: null };
}
function mineText(e, c) {         // the owner's words over the range; removed slots left out
  const f = decision(c).word_fixes || {};
  const out = [];
  for (let s = e.first; s <= e.last; s++) {
    const t = f[String(s)] ?? S.words[s][1];
    if (t !== "") out.push(t);
  }
  return out.join(" ");
}
function autoCount(c) {
  const spans = spansOf(c);
  return S.auto_edits.filter((e) => !autoOverridden(e, c) &&
    spans.some(([a, b]) => S.words[e.first][0] < b && S.words[e.last][0] >= a)).length;
}

// ---- shortcut names for both keyboards (caption spec 7): every cue on the page reads KEYS ----
// On a Mac the key is Option (⌥); the browser reports it as altKey. Clicking with Control held
// is a right-click on a Mac, so no cue ever names Control.
const IS_MAC = /mac|iphone|ipad/i.test(
  (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "");
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const KEYS = {
  start: "click",
  end: "Shift+click",
  fix: IS_MAC ? "Option (⌥)+click (Alt on Windows)" : "Alt+click (Option (⌥) on Mac)",
  undo: IS_MAC ? "Command (⌘)+Z (Ctrl+Z on Windows)" : "Ctrl+Z (Command (⌘)+Z on Mac)",
  redo: IS_MAC ? "Shift+Command (⌘)+Z (Ctrl+Y or Ctrl+Shift+Z on Windows)"
               : "Ctrl+Y or Ctrl+Shift+Z (Shift+Command (⌘)+Z on Mac)",
};

// ---- player: plays segments in order; the hop is checked every video frame ----
// `timeupdate` fires only every ~250 ms, so the preview would run past a segment end. The hop
// is driven by requestVideoFrameCallback (or a requestAnimationFrame loop) and fires slightly early.
const HOP_EARLY = 0.03;
let ticking = false;
let loopId = 0;         // a stale frame callback from an earlier play must not keep looping
let seekTarget = null;   // where our own hop or start seek is heading; any other seek is the user's
function stopPlaying() { playing = null; ticking = false; seekTarget = null; }
function seekTo(t) { seekTarget = t; player.currentTime = t; }
function hop() {
  if (!playing) return;
  const [, end] = playing.spans[playing.i];
  if (player.currentTime >= end - HOP_EARLY) {
    playing.i += 1;
    if (playing.i >= playing.spans.length) { player.pause(); stopPlaying(); return; }
    seekTo(playing.spans[playing.i][0]);
  }
}
function tick(id) {
  if (id !== loopId) return;
  if (!playing) { ticking = false; return; }
  hop();
  if (playing) schedule(); else ticking = false;
}
function schedule() {
  const id = loopId, cb = () => tick(id);
  if (typeof player.requestVideoFrameCallback === "function") player.requestVideoFrameCallback(cb);
  else requestAnimationFrame(cb);
}
function play(c) {
  playing = { spans: spansOf(c), i: 0 };
  seekTo(playing.spans[0][0]);
  const p = player.play();
  if (p && typeof p.catch === "function") p.catch(() => stopPlaying());
  loopId += 1; ticking = true; schedule();
  document.getElementById("now-playing").textContent = `${c.id} · ${c.title}`;
}
player.addEventListener("timeupdate", hop);   // backstop; the frame loop does the precise work
player.addEventListener("pause", stopPlaying);
player.addEventListener("ended", stopPlaying);
player.addEventListener("seeking", () => {
  if (playing && (seekTarget === null || Math.abs(player.currentTime - seekTarget) > 0.5)) stopPlaying();
});

// ---- word helpers ----
// A segment start sits 0.35 s BEFORE its first word, and an end is often clamped to the next
// word's start, so "the word at t" is the wrong question for edges. Starts use the first word at
// or after the start; ends use the last word before the end (review M10).
function wordIndexAt(t) {          // last word with time <= t (for display ranges)
  let lo = 0, hi = S.words.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (S.words[mid][0] <= t) lo = mid; else hi = mid - 1; }
  return lo;
}
function firstWordFrom(t) {        // lower bound: first word with time >= t
  let lo = 0, hi = S.words.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (S.words[mid][0] < t) lo = mid + 1; else hi = mid; }
  return Math.min(lo, S.words.length - 1);
}
function lastWordBefore(t) {       // last word with time < t
  let lo = 0, hi = S.words.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (S.words[mid][0] < t) lo = mid + 1; else hi = mid; }
  return Math.max(lo - 1, 0);
}
function wordEnd(i) {              // mirrors textutil.word_end: next start, at most +1.0 s
  if (i < 0) return 0;
  const next = S.words[i + 1];
  return next ? Math.min(S.words[i][0] + 1.0, next[0]) : S.words[i][0] + 0.5;
}
function padStart(i) { return Math.max(S.words[i][0] - 0.35, wordEnd(i - 1), 0); }
function padEnd(i) {
  const next = S.words[i + 1];
  return next ? Math.min(wordEnd(i) + 0.45, next[0]) : wordEnd(i) + 0.45;
}
function sentenceOf(i) { return S.sentences.findIndex(([a, b]) => a <= i && i <= b); }
const EDGE_EPS = 0.02;
function prevSentence(start) {
  // Mid-sentence: go to the start of THIS sentence; already at its start: go to the previous one.
  if (!S.sentences.length) return start;
  const n = sentenceOf(firstWordFrom(start));
  if (n < 0) return start;
  const here = padStart(S.sentences[n][0]);
  if (start > here + EDGE_EPS) return here;
  return padStart(S.sentences[Math.max(n - 1, 0)][0]);
}
function nextSentence(end) {
  if (!S.sentences.length) return end;
  const n = sentenceOf(lastWordBefore(end));
  if (n < 0) return end;
  const here = padEnd(S.sentences[n][1]);
  if (end < here - EDGE_EPS) return here;
  return padEnd(S.sentences[Math.min(n + 1, S.sentences.length - 1)][1]);
}

// ---- edits ----
function note(msg) { document.getElementById("now-playing").textContent = msg; }
function showError(err) { note(`Not saved: ${err.message || err}`); }
// The new spans are computed when the save's turn comes, from the entry the previous save
// returned, so two quick "start +0.5" clicks move the edge twice (two steps).
function saveSegments(c, seg, change) {
  return queued(c, async () => {
    const spans = spansOf(c).map((s) => [...s]);
    change(spans);
    if (spans[seg][1] - spans[seg][0] < 1) return;
    try {
      applyReply(c, await api("/api/edit", { id: c.id, edit: { segments: spans } }));
    } catch (err) { showError(err); }   // e.g. 400 "segments overlap": nothing was written
  });
}
function nudge(c, seg, edge, delta) {
  saveSegments(c, seg, (spans) => { spans[seg][edge] = Math.max(0, spans[seg][edge] + delta); });
}
function setEdge(c, seg, edge, t) {
  saveSegments(c, seg, (spans) => { spans[seg][edge] = t; });
}
function setStatus(c, status) {
  return queued(c, async () => {
    try {
      applyReply(c, await api("/api/decision", { id: c.id, status }));
      if (status === "approved" && typeof pollBroll === "function") pollBroll(c.id);   // S8B spec 5.1
    } catch (err) { showError(err); }
  });
}
function fixWord(c, i) {
  const v = slotView(i, c);
  if (v.flag === "auto") return fixRange(c, S.auto_edits[v.edit]);
  const now = v.text;
  const txt = window.prompt(
    "Correct this word (its timing is kept). Leave it blank to remove the word:", now);
  if (txt === null || txt === now) return;
  const fix = txt.trim();               // "" drops the word: the previous word keeps its time
  return queued(c, async () => {
    try {
      const res = await api("/api/edit", { id: c.id, edit: { word_fixes: { [i]: fix } } });
      applyReply(c, res);
    } catch (err) { showError(err); }
  });
}
// Replace a whole automatic fix: the first slot gets the typed text, the other slots are dropped
// (""). An empty answer still means "cancel" here; a single word takes a blank answer as "remove".
// When the suggestion is what renders now, the owner confirms before their text replaces it, and
// the same save selects "Mine" for the range, so it is one undo step (review spec 4.4).
function fixRange(c, e, now = e.tokens.join(" ")) {
  const auto = e.tokens.join(" ");
  const txt = window.prompt(
    `Correct the automatic fix "${auto}" (transcribed as "${e.original}"). ` +
    "The whole range gets this text; its timing is kept:", now);
  if (txt === null || txt.trim() === "" || txt.trim() === now) return;
  const typed = txt.trim();
  if (!autoOverridden(e, c) && !window.confirm(
      `Your text "${typed}" will replace the automatic fix "${auto}". ` +
      "Do you really want to do this? (You can switch back to the suggestion later.)")) return;
  const fixes = { [e.first]: typed };
  for (let s = e.first + 1; s <= e.last; s++) fixes[s] = "";
  return queued(c, async () => {
    const use_auto = useAuto(c).filter((f) => f !== e.first);
    try {
      const res = await api("/api/edit", { id: c.id, edit: { word_fixes: fixes, use_auto } });
      applyReply(c, res);
    } catch (err) { showError(err); }
  });
}
// A word the owner removed stays visible, faint and struck through; a click brings it back by
// erasing the owner's fix for that slot (null), as if it was never touched, in one undoable step
// (review spec 4.3). Only the page draws it: the saved fix is still "", so it never reaches the
// captions, the render or the estimate.
function ghost(c, i, inside) {
  return $("span", {
    class: `ghost ${inside ? "in" : ""}`,
    title: `${fmt(S.words[i][0])} · removed word · click to bring it back`,
    onclick: () => restoreWord(c, i),
  }, S.words[i][1], " ", $("b", { class: "ghost-mark" }, "⌫"));
}
function restoreWord(c, i) {
  return queued(c, async () => {
    try {
      applyReply(c, await api("/api/edit", { id: c.id, edit: { word_fixes: { [i]: null } } }));
    } catch (err) { showError(err); }
  });
}
// Both versions of a corrected range, side by side; the outlined one is rendered. A click on the
// other side switches; KEYS.fix on either side edits the range starting from that side's text.
function chooser(c, e, inside, edge) {
  const auto = useAuto(c).includes(e.first);
  const side = (label, text, on, pickAuto) => $("span", {
    class: `choice ${on ? "on" : ""}`,
    title: `${on ? "this version is rendered" : "click to render this version"} · ` +
           `${KEYS.fix}: correct the whole range\nautomatic fix of "${e.original}": ${e.reason}`,
    onclick: (ev) => {
      if (ev.altKey) return fixRange(c, e, text);
      if (!on) chooseSide(c, e, pickAuto);
    },
  }, $("b", { class: "choice-label" }, label), text);
  return $("span", { class: `chooser ${inside ? "in" : ""} ${edge ? "edge" : ""}` },
    side("Suggestion", e.tokens.join(" "), auto, true), " ",
    side("Mine", mineText(e, c), !auto, false));
}
function chooseSide(c, e, pickAuto) {
  return queued(c, async () => {
    const rest = useAuto(c).filter((f) => f !== e.first);
    try {
      applyReply(c, await api("/api/edit", { id: c.id, edit: { use_auto: pickAuto ? [...rest, e.first] : rest } }));
    } catch (err) { showError(err); }
  });
}

// ---- drawers (S7 spec 4.1): open drawers are remembered per job, in this browser only ----
let openIds = new Set();
const openKey = () => `shorts.review.open.${S.job}`;
function loadOpen() {
  try {
    const ids = JSON.parse(localStorage.getItem(openKey()) || "[]");
    openIds = new Set(Array.isArray(ids) ? ids : []);
  } catch (e) {
    openIds = new Set();                 // private window, blocked storage or junk: all closed
  }
}
function saveOpen() {
  try { localStorage.setItem(openKey(), JSON.stringify([...openIds])); } catch (e) { /* storage off */ }
}
function toggleDrawer(c, el, toggle) {
  const open = !openIds.has(c.id);
  if (open) openIds.add(c.id); else openIds.delete(c.id);
  saveOpen();
  el.classList.toggle("open", open);
  toggle.setAttribute("aria-expanded", String(open));
  toggle.querySelector(".caret").textContent = open ? "▾" : "▸";
}

// ---- audio strength (S8 audio spec 6): one class strength chosen by ear, a per-clip override ----
const GATE_TIP = "Choose the audio strength first";
const excerptPlayer = new Audio();
let audioOpen = false;     // "change" reopens the four rows after a choice
let audioTimer = null;
const levelLabel = (v) => (v === 0 ? "off" : String(v));
function gateOpen() { return !A || !A.enabled || A.chosen !== null; }
async function refreshAudio() {
  clearTimeout(audioTimer);
  try {
    A = await api("/api/audio");
    if (A.enabled && A.excerpt === "missing") A = await api("/api/audio/prepare", {});
  } catch (err) {
    const msg = err.message || String(err);
    // renders are running (409): wait and ask again, not an error for the owner
    if (A) Object.assign(A, msg.includes("renders are running")
      ? { excerpt: "preparing", error: null } : { excerpt: "failed", error: msg });
  }
  drawAudio();
  syncRenders();
  if (A && A.excerpt === "preparing") audioTimer = setTimeout(refreshAudio, POLL_MS);
}
function playExcerpt(level) {
  player.pause();
  stopPlaying();
  excerptPlayer.src = `/media/excerpt/${level}.m4a`;
  excerptPlayer.play().catch((err) => { if (!err || err.name !== "AbortError") showError(err); });
}
player.addEventListener("play", () => excerptPlayer.pause());
function chooseStrength(level) {
  excerptPlayer.pause();
  api("/api/audio", { dereverb: level }).then((res) => {
    A = res;
    audioOpen = false;
    drawAudio();
    render();             // the per-clip selects show the new "class (N)"
    refreshRenders();     // every clip that follows the class is now out of date
  }).catch(showError);
}
function retryExcerpt() {
  api("/api/audio/prepare", {}).then((res) => { A = res; drawAudio(); refreshAudio(); }).catch(showError);
}
// "off" needs no excerpt and no UVR: it stays choosable while the excerpt is missing or failed
function offRow() {
  return $("div", { class: "audio-row" }, $("span", { class: "audio-level" }, levelLabel(0)),
    $("button", { type: "button", onclick: () => chooseStrength(0) }, "Choose"));
}
function drawAudio() {
  const box = document.getElementById("audio");
  if (!A || !A.enabled) { box.hidden = true; return; }
  box.hidden = false;
  if (A.chosen !== null && !audioOpen) {
    box.replaceChildren($("div", { class: "audio-line" }, `Audio: dereverb ${levelLabel(A.chosen)} · `,
      $("button", { type: "button", class: "link", onclick: () => { audioOpen = true; drawAudio(); } }, "change")));
    return;
  }
  const kids = [$("div", { class: "audio-title" }, "Audio strength for this class: listen, then choose")];
  if (A.excerpt === "preparing" || A.excerpt === "missing") {
    kids.push($("div", { class: "hint" }, "Preparing audio…"), offRow());
  } else if (A.excerpt === "failed") {
    kids.push($("div", { class: "audio-error" }, A.error || "failed"),
              $("button", { type: "button", onclick: retryExcerpt }, "Try again"), offRow());
  } else {
    for (const lv of A.levels) {
      kids.push($("div", { class: `audio-row ${A.chosen === lv ? "chosen" : ""}` },
        $("span", { class: "audio-level" }, levelLabel(lv)),
        $("button", { type: "button", onclick: () => playExcerpt(lv) }, "▶ play"),
        $("button", { type: "button", onclick: () => chooseStrength(lv) }, "Choose")));
    }
  }
  box.replaceChildren(...kids);
}
function audioSelect(c) {
  if (!A || !A.enabled) return "";
  const cur = decision(c).dereverb;
  const sel = $("select", { class: "audio-select", "aria-label": "Audio strength of this clip" });
  sel.append($("option", { value: "" }, A.chosen === null ? "class (not chosen)" : `class (${levelLabel(A.chosen)})`));
  for (const lv of A.levels) sel.append($("option", { value: String(lv) }, levelLabel(lv)));
  sel.value = cur === undefined || cur === null ? "" : String(cur);
  sel.addEventListener("change", () => queued(c, async () => {
    try {
      applyReply(c, await api("/api/edit", { id: c.id, edit: { dereverb: sel.value === "" ? null : Number(sel.value) } }));
    } catch (err) { showError(err); }
  }));
  return $("label", { class: "row hint" }, "Audio: ", sel);
}
function audioChip(c) {
  const v = decision(c).dereverb;
  if (!A || !A.enabled || v === undefined || v === null || v === A.chosen) return null;
  return $("span", { class: "chip audio" }, `audio ${levelLabel(v)}`);
}

// ---- render state and queue (S7 spec 3, 4) ----
// The server works each clip's render state out from the files on disk, so it survives a restart;
// queued, rendering and failed come from its queue. While anything is queued or rendering the page
// asks again every 2 s and updates the drawer heads in place: a full redraw would take the focus
// away from a title being typed.
const POLL_MS = 2000;
const NEEDS_RENDER = ["not_rendered", "out_of_date", "failed"];
let pollTimer = null;
const heads = {};          // clip id -> {title, status, slot} of its drawer head (filled by card())
function stateOf(c) { return R.clips[c.id] || { state: "not_rendered", version: null, approved: false, file: false }; }
function stateLabel(r) {
  const v = `v${r.version ?? "?"}`;
  return {
    not_rendered: "not rendered", rendered: `rendered ${v}`, out_of_date: `out of date (${v})`,
    queued: "queued", rendering: "rendering…", failed: "failed",
  }[r.state] || r.state;
}
function busy() { return Object.values(R.clips).some((r) => r.state === "queued" || r.state === "rendering"); }
function needsRender(c) { return statusOf(c) === "approved" && NEEDS_RENDER.includes(stateOf(c).state); }
async function refreshRenders() {
  clearTimeout(pollTimer);
  try {
    R = await api("/api/renders");
  } catch (err) {
    note(`Render state not read: ${err.message || err}`);   // the drawers keep their last state
  }
  syncRenders();
  if (busy()) pollTimer = setTimeout(refreshRenders, POLL_MS);
}
function queueReply(res) {     // the reply already holds the state: only schedule the next poll
  R = res;
  syncRenders();
  clearTimeout(pollTimer);
  if (busy()) pollTimer = setTimeout(refreshRenders, POLL_MS);
}
function queueClip(c) { return api("/api/render", { id: c.id }).then(queueReply).catch(showError); }
function queueAllClips() { return api("/api/render-all", {}).then(queueReply).catch(showError); }
function stateSlot(c) {
  const r = stateOf(c);
  const kids = [];
  const chip = audioChip(c);
  if (chip) kids.push(chip);
  const bchip = typeof brollChip === "function" ? brollChip(c) : null;
  if (bchip) kids.push(bchip);
  kids.push($("span", { class: `chip render ${r.state}`, title: r.error || "" }, stateLabel(r)));
  if (statusOf(c) === "approved" && NEEDS_RENDER.includes(r.state)) {
    const attrs = { class: "render", onclick: () => queueClip(c) };
    if (!gateOpen()) Object.assign(attrs, { disabled: "", title: GATE_TIP });
    kids.push($("button", attrs, "render"));
  }
  if (r.file) {
    kids.push($("a", { class: "watch", href: `/renders/${c.id}.mp4`, target: "_blank", rel: "noopener" }, "▶ watch"));
  }
  return kids;
}
function syncRenders() {
  const byId = Object.fromEntries(S.candidates.map((c) => [c.id, c]));
  for (const [id, h] of Object.entries(heads)) {
    const c = byId[id];
    if (!c) continue;
    h.title.textContent = decision(c).title ?? c.title;
    h.status.textContent = statusOf(c);
    h.status.className = `chip review ${statusOf(c)}`;
    h.slot.replaceChildren(...stateSlot(c));
  }
  syncSummary();
}
function syncSummary() {
  const approved = S.candidates.filter((c) => statusOf(c) === "approved").length;
  const rendered = S.candidates.filter((c) => stateOf(c).state === "rendered").length;
  const n = S.candidates.filter(needsRender).length;      // queued and rendering are not counted
  document.getElementById("summary").textContent = S.candidates.length
    ? `${S.candidates.length} candidates · ${approved} approved · ${rendered} rendered · channel ${S.channel} · ${S.format}`
    : "No candidates: no window reached the scan threshold.";
  const all = document.getElementById("render-all");
  all.textContent = `render all (${n})`;
  all.disabled = n === 0 || !gateOpen();
  all.title = gateOpen() ? "" : GATE_TIP;
}

// ---- rendering ----
function bars(c) {
  const box = $("div", { class: "bars" });
  for (const k of ["hook", "value", "conversation", "emotion"]) {
    const d = c.scores[k] || { score: 0, why: "" };
    const bar = $("div", { class: "bar" }, $("span", { style: `width:${d.score * 10}%` }));
    box.append($("div", {}, `${k} ${d.score}`), $("div", {}, bar, $("div", { class: "why" }, d.why)));
  }
  return box;
}
function badges(c) {
  const row = $("div", { class: "row" });
  const lvl = ["consensus", "disputed", "inflammatory"][c.controversy] || "?";
  row.append($("span", { class: `badge ${c.controversy === 2 ? "bad" : ""}` }, `controversy ${c.controversy}: ${lvl}`));
  row.append($("span", { class: "badge" }, `verdict: ${c.verdict}`));
  for (const w of [...(c.warnings || []), ...(c.clip_warnings || []), ...S.warnings]) {
    row.append($("span", { class: "badge warn" }, w));
  }
  if (c.out_of_order && !(c.warnings || []).includes("out_of_order")) row.append($("span", { class: "badge warn" }, "out_of_order"));
  if (c.blind && c.blind.suggest_earlier_start) {
    row.append($("span", { class: "badge warn", title: c.blind.why || "" },
                 "suggest_earlier_start: the blind review thinks it opens mid-thought; try start ◀ sentence"));
  }
  const n = autoCount(c);
  if (n) row.append($("span", { class: "badge auto" }, `${n} automatic caption fix${n === 1 ? "" : "es"}`));
  return row;
}
function wordsBlock(c) {
  const spans = spansOf(c);
  const box = $("div", { class: "words" });
  spans.forEach(([a, b], seg) => {
    if (seg > 0) box.append($("span", { class: "seg-sep" }, "[…]"));
    const from = Math.max(wordIndexAt(a) - 8, 0), to = Math.min(wordIndexAt(b) + 8, S.words.length - 1);
    const drawn = new Set();                  // automatic fixes already drawn as a chooser
    for (let i = from; i <= to; i++) {
      const t = S.words[i][0];
      const inside = t >= a && t < b;
      const shown = (k) => { const w = slotView(k, c); return w.flag === "choice" || (w.flag !== "ghost" && w.text !== ""); };
      const insideAt = (k) => {
        for (const step = k < i ? -1 : 1; k >= 0 && k < S.words.length; k += step) {
          if (shown(k)) return S.words[k][0] >= a && S.words[k][0] < b;
        }
        return false;
      };
      const edge = inside && (!insideAt(i - 1) || !insideAt(i + 1));
      const v = slotView(i, c);
      if (v.flag === "choice") {
        if (!drawn.has(v.edit)) {
          drawn.add(v.edit);
          const ce = S.auto_edits[v.edit];       // the outline spans the whole range: judge its two outer neighbours
          const chooserEdge = inside && (!insideAt(ce.first - 1) || !insideAt(ce.last + 1));
          box.append(chooser(c, ce, inside, chooserEdge), " ");
        }
        continue;
      }
      if (v.flag === "ghost") { box.append(ghost(c, i, inside), " "); continue; }
      if (v.text === "") continue;          // a slot merged by an automatic fix: nothing to show
      const e = v.flag === "auto" ? S.auto_edits[v.edit] : null;
      const tip = `${fmt(t)} · ${KEYS.start}: set start · ${KEYS.end}: set end · ${KEYS.fix}: ` +
        (e ? `replace the whole automatic fix\nautomatic fix of "${e.original}": ${e.reason}` : "fix word");
      const el = $("span", {
        class: `${inside ? "in" : ""} ${edge ? "edge" : ""} ${v.flag === "raw" ? "" : v.flag}` +
               `${typeof brollMarked === "function" && brollMarked(c, i) ? " bsel" : ""}`,
        title: tip,
        onclick: (ev) => {
          if (typeof brollWordClick === "function" && brollWordClick(c, i)) return;   // S8B: own moment
          if (ev.altKey) return fixWord(c, i);
          if (ev.shiftKey) return setEdge(c, seg, 1, padEnd(i));
          return setEdge(c, seg, 0, padStart(i));    // never reaches into the previous word
        },
      }, v.text);
      box.append(el, " ");
    }
  });
  return box;
}
function segControls(c) {
  const box = $("div", { class: "row" });
  spansOf(c).forEach(([a, b], seg) => {
    box.append(
      $("span", { class: "hint" }, `seg ${seg + 1}: ${fmt(a)}–${fmt(b)}`),
      $("button", { onclick: () => nudge(c, seg, 0, -0.5) }, "start −0.5"),
      $("button", { onclick: () => nudge(c, seg, 0, +0.5) }, "start +0.5"),
      $("button", { onclick: () => setEdge(c, seg, 0, prevSentence(a)) }, "start ◀ sentence"),
      $("button", { onclick: () => nudge(c, seg, 1, -0.5) }, "end −0.5"),
      $("button", { onclick: () => nudge(c, seg, 1, +0.5) }, "end +0.5"),
      $("button", { onclick: () => setEdge(c, seg, 1, nextSentence(b)) }, "end ▶ sentence"),
    );
  });
  return box;
}
function card(c) {
  const d = decision(c);
  const open = openIds.has(c.id);
  const el = $("div", { class: `card ${statusOf(c)} ${open ? "open" : ""} ${c.id === justSaved ? "saved" : ""}` });
  const title = $("input", { class: "title", value: d.title ?? c.title });
  title.addEventListener("change", () => queued(c, () => api("/api/edit", { id: c.id, edit: { title: title.value } })
    .then((res) => applyReply(c, res, false)).catch(showError)));
  const hook = $("input", { class: "hook", value: d.hook ?? c.hook });
  hook.addEventListener("change", () => queued(c, () => api("/api/edit", { id: c.id, edit: { hook: hook.value } })
    .then((res) => applyReply(c, res, false)).catch(showError)));
  const undoBtn = $("button", { class: "undo", title: `Undo the last change to this clip (${KEYS.undo})`,
                                onclick: () => stepHistory(c, "undo") }, "Undo");
  const redoBtn = $("button", { class: "redo", title: `Redo (${KEYS.redo})`,
                                onclick: () => stepHistory(c, "redo") }, "Redo");
  histButtons[c.id] = { undo: undoBtn, redo: redoBtn };
  // Drawer head (S7 spec 4.1): the toggle is its own button, so render and watch never nest in it.
  const headTitle = $("span", { class: "drawer-title" }, d.title ?? c.title);
  const toggle = $("button", { class: "drawer-toggle", "aria-expanded": String(open) },
    $("span", { class: "caret", "aria-hidden": "true" }, open ? "▾" : "▸"),
    $("span", { class: "drawer-id" }, c.id), headTitle);
  toggle.addEventListener("click", () => toggleDrawer(c, el, toggle));
  const headStatus = $("span", { class: `chip review ${statusOf(c)}` }, statusOf(c));
  const slot = $("span", { class: "render-slot" }, ...stateSlot(c));
  heads[c.id] = { title: headTitle, status: headStatus, slot };
  const body = $("div", { class: "drawer-body" },
    $("div", { class: "row" },
      $("div", { class: "total" }, String(c.total)),
      $("button", { onclick: () => play(c) }, "▶ play"),
      $("span", { class: "hint" }, `${c.id} · ~${c.estimated_duration}s after silence cut`),
      $("button", { class: "approve", onclick: () => setStatus(c, "approved") }, "approve"),
      $("button", { class: "reject", onclick: () => setStatus(c, "rejected") }, "reject"),
      undoBtn, redoBtn,
      $("span", { class: "status" }, statusOf(c) === "pending" ? "" : statusOf(c))),
    title, hook, badges(c),
    $("div", { class: "why" }, `who reacts: ${c.who_reacts || "—"}`),
    bars(c), wordsBlock(c), segControls(c), audioSelect(c), typeof brollSection === "function" ? brollSection(c) : "",
    $("div", { class: "hint" },
      `${cap(KEYS.start)} a word to start there · ${KEYS.end} to end there · ${KEYS.fix} to correct it ` +
      "(an automatic fix is replaced as a whole; leave the box blank to remove a word). " +
      `${cap(KEYS.undo)} undoes and ${KEYS.redo} redoes the last change of the clip with the outlined Undo.`));
  el.append($("div", { class: "drawer-head" }, toggle, headStatus, slot), body);
  return el;
}
function render() {
  try {
    renderAll();
  } finally {
    justSaved = null;    // the flash plays once, on the render that follows the save
  }
}
function renderAll() {
  const cards = document.getElementById("cards");
  const dropped = document.getElementById("dropped-cards");
  cards.replaceChildren();
  dropped.replaceChildren();
  for (const id of Object.keys(histButtons)) delete histButtons[id];
  for (const id of Object.keys(heads)) delete heads[id];
  const byId = Object.fromEntries(S.candidates.map((c) => [c.id, c]));
  const seen = new Set();
  const groups = Object.entries(S.groups).map(([gid, ids]) => ({ gid, cs: ids.map((i) => byId[i]).filter(Boolean) }));
  groups.sort((a, b) => (b.cs[0]?.total ?? 0) - (a.cs[0]?.total ?? 0));
  for (const g of groups) {
    const live = g.cs.filter((c) => c.verdict !== "drop");
    g.cs.filter((c) => c.verdict === "drop").forEach((c) => { dropped.append(card(c)); seen.add(c.id); });
    if (!live.length) continue;
    if (live.length === 1) cards.append(card(live[0]));
    else {
      const box = $("div", { class: "group" }, $("div", { class: "label" }, `variations of hook ${g.gid} (hook_id)`));
      live.forEach((c) => box.append(card(c)));
      cards.append(box);
    }
    live.forEach((c) => seen.add(c.id));
  }
  S.candidates.filter((c) => !seen.has(c.id)).forEach((c) => cards.append(card(c)));
  syncSummary();
  syncHistory();
}

// ---- undo and redo keys (review spec 4.2): they act on the clip changed last. While a text box
// has focus the browser's own text undo runs instead. A held key repeats: only the first press counts.
function typing(el) {
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}
document.addEventListener("keydown", (ev) => {
  if (!S || typing(document.activeElement)) return;
  const mod = IS_MAC ? ev.metaKey : ev.ctrlKey;
  if (!mod || ev.altKey) return;
  const k = ev.key.toLowerCase();
  const action = k === "z" ? (ev.shiftKey ? "redo" : "undo") : (k === "y" && !IS_MAC ? "redo" : null);
  if (!action) return;
  ev.preventDefault();
  if (ev.repeat) return;
  const c = S.candidates.find((x) => x.id === lastClip);
  if (!c) return note(`Nothing to ${action} yet: change a clip first.`);
  stepHistory(c, action);
});

document.getElementById("render-all").addEventListener("click", queueAllClips);

(async () => {
  S = await api("/api/job");
  S.review.decisions ||= {};
  S.auto_edits ||= [];
  S.auto_slots ||= {};
  lastClip = S.last_clip || null;     // the server remembers it, so a reload keeps the keys working
  document.getElementById("title").textContent = `Shorts review · ${S.job}`;
  loadOpen();
  try { A = await api("/api/audio"); } catch (err) { A = null; }   // a page without the panel (no app config)
  drawAudio();
  render();
  refreshRenders();
  refreshAudio();
  if (typeof refreshBroll === "function") refreshBroll();
})().catch((e) => { document.getElementById("summary").textContent = `Error: ${e.message}`; });
