from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "shorts" / "review" / "static"


def test_page_files_exist_and_link():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'src="/static/app.js"' in html and 'href="/static/style.css"' in html
    assert 'id="player"' in html and 'id="cards"' in html


def test_app_js_implements_every_control():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for needle in ["/api/job", "/api/decision", "/api/edit", "/media/master",
                   "timeupdate", "hook_id", "estimated_duration", "word_fixes",
                   "approved", "rejected", "nudge", "prevSentence", "nextSentence",
                   "controversy", "who_reacts", "clip_warnings", "out_of_order",
                   "firstWordFrom", "lastWordBefore", "wordEnd", "suggest_earlier_start",
                   "showError"]:
        assert needle in js, needle


def test_app_js_hops_per_frame_and_guards_sentences():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "requestVideoFrameCallback" in js and "requestAnimationFrame" in js
    assert "HOP_EARLY" in js and "S.sentences.length" in js


import shutil
import subprocess

import pytest


def test_app_js_shows_automatic_fixes_and_replaces_the_whole_range():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for needle in ["auto_edits", "auto_slots", "slotView", "autoOverridden", "fixRange",
                   "autoCount", "automatic caption fix", '"auto"', "e.original", "e.reason",
                   'fixes[s] = ""']:
        assert needle in js, needle


def test_blank_answer_removes_a_single_word():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    body = js[js.index("function fixWord("):js.index("// Replace a whole automatic fix")]
    assert "Leave it blank to remove the word" in body
    assert 'txt.trim() === ""' not in body.split("txt === now")[0]   # no combined cancel
    assert "word_fixes: { [i]: fix }" in body and "applyReply(c, res)" in body and "|| fix" not in body
    assert "leave the box blank to remove a word" in js


def test_shortcut_cues_name_both_keyboards_and_never_control():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Option (⌥)+click (Alt on Windows)" in js and "Alt+click (Option (⌥) on Mac)" in js
    assert "userAgentData" in js and "navigator.platform" in js and "Shift+click" in js
    assert "KEYS.fix" in js and "KEYS.end" in js and "KEYS.start" in js
    low = js.lower()
    for banned in ["control-click", "ctrl+click", "control+click", "ctrl-click"]:
        assert banned not in low, banned
    for old in ["alt+click: fix word", "alt+click to correct it"]:   # single-keyboard cues are gone
        assert old not in js, old


def test_style_has_the_automatic_fix_classes():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".words span.auto" in css and ".badge.auto" in css


def test_app_js_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    subprocess.run([node, "--check", str(STATIC / "app.js")], check=True)


def _body(js, head):
    start = js.index(head)
    return js[start:js.index("\n}\n", start)]


def test_undo_and_redo_keys_buttons_and_focus_guard():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for needle in ["/api/${action}", "stepHistory", "applyReply", "lastClip", "histButtons",
                   "syncHistory", 'addEventListener("keydown"', "ev.metaKey", "ev.ctrlKey",
                   "ev.shiftKey", 'k === "y"', 'k === "z"', "ev.preventDefault()", "ev.repeat",
                   "typing(document.activeElement)", "isContentEditable", '"TEXTAREA"', '"INPUT"',
                   "KEYS.undo", "KEYS.redo", '"Undo"', '"Redo"', "change a clip first",
                   '"undo"', '"redo"', 'classList.toggle("hot"']:
        assert needle in js, needle
    assert "Command (⌘)+Z (Ctrl+Z on Windows)" in js and "Ctrl+Z (Command (⌘)+Z on Mac)" in js
    assert "Shift+Command (⌘)+Z (Ctrl+Y or Ctrl+Shift+Z on Windows)" in js
    assert "Ctrl+Y or Ctrl+Shift+Z (Shift+Command (⌘)+Z on Mac)" in js
    keys = js[js.index('document.addEventListener("keydown"'):]      # the handler is not a function body
    assert keys.index("typing(document.activeElement)") < keys.index("ev.preventDefault()")
    assert keys.index("ev.preventDefault()") < keys.index("if (ev.repeat) return;")


def test_every_save_replaces_the_local_entry_with_the_reply():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for head in ["function saveSegments(", "function setStatus(", "function fixWord(",
                 "function fixRange(", "function stepHistory("]:
        assert "applyReply(c, " in _body(js, head), head
    assert js.count("applyReply(c, res, false)") == 2          # title and hook keep the focus
    reply = _body(js, "function applyReply")
    assert "S.review.decisions[c.id] = entry" in reply and "lastClip = c.id" in reply


def test_saves_of_a_clip_are_queued_in_click_order():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    q = _body(js, "function queued(")
    assert "queues[c.id]" in q and ".then(fn, fn)" in q
    for head in ["function saveSegments(", "function setStatus(", "function fixWord(",
                 "function fixRange(", "function stepHistory("]:
        assert "queued(c, async () =>" in _body(js, head), head
    assert js.count("queued(c, () => api(") == 2             # title and hook
    seg = _body(js, "function saveSegments(")
    assert seg.index("queued(c, async () =>") < seg.index("spansOf(c)")   # spans read at its turn
    for old in ["async function saveSegments", "async function setStatus", "async function fixWord",
                "async function fixRange", "async function stepHistory"]:
        assert old not in js, old


def test_style_marks_the_last_clip_and_disabled_buttons():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "button.undo.hot" in css and "button:disabled" in css


def test_removed_words_show_as_ghost_chips_that_restore():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for needle in ['flag: f === "" ? "ghost" : "fixed"', "function ghost", "function restoreWord(",
                   "⌫", "click to bring it back", "word_fixes: { [i]: null }"]:
        assert needle in js, needle
    restore = _body(js, "function restoreWord(")
    assert "queued(c, async () =>" in restore and "S.words[i][1] }" not in restore   # erase, never rewrite
    block = _body(js, "function wordsBlock")
    assert block.index('v.flag === "ghost"') < block.index('v.text === ""')
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".words span.ghost" in css and "line-through" in css


def test_choice_between_suggestion_and_mine():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for needle in ["function useAuto", "function hasMine", "function mineText", "function chooser",
                   "function chooseSide(", 'flag: "choice"', "use_auto", '"Suggestion"', '"Mine"',
                   "drawn", "window.confirm", "Do you really want to do this?",
                   "(You can switch back to the suggestion later.)"]:
        assert needle in js, needle
    over = _body(js, "function autoOverridden")
    assert over.count("\n") == 1                                             # its own two lines only
    assert "hasMine(e, c)" in over and "useAuto(c).includes(e.first)" in over
    assert "queued(c, async () =>" in _body(js, "function chooseSide(")
    fix = _body(js, "function fixRange(")
    assert "!autoOverridden(e, c) && !window.confirm(" in fix
    assert fix.index("window.confirm") < fix.index('api("/api/edit"')          # ask before saving
    assert "word_fixes: fixes, use_auto" in fix                               # one call, one step
    assert "useAuto(c).filter((f) => f !== e.first)" in fix
    assert fix.index("queued(c, async () =>") < fix.index("useAuto(c).filter")   # read at its turn
    block = _body(js, "function wordsBlock")
    assert block.index('v.flag === "choice"') < block.index('v.flag === "ghost"')
    assert "function wordText" not in js
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".words span.choice" in css and ".words span.choice.on" in css


def test_a_reload_takes_the_last_clip_from_the_server():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "lastClip = S.last_clip || null" in js


REPO = Path(__file__).resolve().parents[1]
FONTS = REPO / "assets" / "fonts"


def test_bundled_fonts_and_licences():
    for name in ["Anton-Regular.ttf", "Raleway-Variable.ttf", "IBMPlexMono-Regular.ttf",
                 "OFL.txt", "OFL-Raleway.txt", "OFL-IBMPlexMono.txt"]:
        path = FONTS / name
        assert path.is_file(), name
        assert path.stat().st_size < 5 * 1024 * 1024, name
    for name in ["Raleway-Variable.ttf", "IBMPlexMono-Regular.ttf"]:
        assert (FONTS / name).read_bytes()[:4] == b"\x00\x01\x00\x00", name   # TrueType magic
    for name in ["OFL-Raleway.txt", "OFL-IBMPlexMono.txt"]:
        assert "SIL OPEN FONT LICENSE" in (FONTS / name).read_text(encoding="utf-8").upper(), name


def test_brand_mark_is_the_design_system_symbol():
    svg = (STATIC / "albatroz-symbol.svg").read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<svg") and 'viewBox="0 0 624.318 159.365"' in svg


SEMANTIC = ["--bg-page", "--bg-card", "--bg-stage", "--fg-default", "--fg-muted", "--fg-on-stage",
            "--border-quiet", "--border-strong", "--accent", "--accent-hover", "--status-approved",
            "--status-rejected", "--tint-in-cut", "--primary-bg", "--primary-fg", "--primary-hover"]


def test_tokens_define_every_semantic_name_and_load_local_fonts():
    css = (STATIC / "tokens.css").read_text(encoding="utf-8")
    root = css[:css.index("@media")]
    for name in SEMANTIC:
        assert f"{name}:" in root, name
    for font in ["/fonts/Anton-Regular.ttf", "/fonts/Raleway-Variable.ttf", "/fonts/IBMPlexMono-Regular.ttf"]:
        assert f'url("{font}")' in css, font
    assert css.count("font-display: swap") == 3 and "font-weight: 100 900" in css
    assert "~/dev/studio/brand/design-sys/colors_and_type.css" in css      # provenance comment


def test_page_head_loads_theme_first_then_tokens_then_style():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    head = html[:html.index("</head>")]
    order = [head.index('src="/static/theme.js"'), head.index('href="/static/tokens.css"'),
             head.index('href="/static/style.css"')]
    assert order == sorted(order)
    assert '<script src="/static/theme.js"></script>' in head          # no defer, no async
    assert '<meta name="color-scheme" content="light dark">' in head
    assert 'rel="preload" href="/fonts/Raleway-Variable.ttf" as="font" type="font/ttf" crossorigin' in head
    for needle in ['class="top-stripe"', 'class="brand-mark"', 'id="theme"', 'role="group"',
                   'data-theme="light"', 'data-theme="dark"', 'data-theme="system"']:
        assert needle in html, needle
    for id_ in ["title", "summary", "stage", "player", "now-playing", "cards", "dropped", "dropped-cards"]:
        assert f'id="{id_}"' in html, id_


def test_theme_js_applies_before_css_and_falls_back():
    js = (STATIC / "theme.js").read_text(encoding="utf-8")
    for needle in ['"shorts.review.theme"', '["light", "dark", "system"]', "localStorage.getItem",
                   "localStorage.setItem", 'removeAttribute("data-theme")', 'setAttribute("data-theme"',
                   '"aria-pressed"', "DOMContentLoaded", 'return "system"']:
        assert needle in js, needle
    assert js.count("try {") == 2 and js.count("catch") == 2           # read and write both guarded
    assert "fetch(" not in js and "/api/" not in js                    # a viewer convenience only
    body = js[js.index("function read()"):js.index("function apply(")]
    assert "CHOICES.includes(v) ? v : \"system\"" in body               # junk falls back to system


def test_theme_js_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    subprocess.run([node, "--check", str(STATIC / "theme.js")], check=True)


import re


def test_style_uses_tokens_only():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "raw hex color in style.css"
    for bad in ["rgb(", "rgba(", "hsl("]:
        assert bad not in css, bad
    assert "var(--" in css


def test_static_never_reaches_the_network_or_banned_fonts():
    for path in STATIC.iterdir():
        if path.suffix not in {".css", ".js", ".html"}:
            continue
        text = path.read_text(encoding="utf-8")
        for bad in ["http://", "https://", "@import", "fonts.googleapis"]:
            assert bad not in text, f"{path.name}: {bad}"
        for bad in ["GT Sectra", "Kameron"]:
            assert bad not in text, f"{path.name}: {bad}"


def test_style_has_the_brand_components():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for needle in [".top-stripe", "position: fixed", "var(--z-stripe)", "top: var(--stripe-h)",
                   "padding-top: var(--stripe-h)", ".brand-mark", "mask:", "-webkit-mask:",
                   "lining-nums tabular-nums", ":focus-visible", "min-height: 24px",
                   "min-height: 32px", "max-width: var(--content-max)", "max-width: 75ch",
                   "@keyframes saved", ".card.saved", "prefers-reduced-motion",
                   "#theme button[aria-pressed=\"true\"]", "font-family: var(--font-headline)",
                   "var(--font-mono)", ".words span.edge", ".choice-label", ".ghost-mark",
                   "cursor: not-allowed", "opacity: 0.4", "scale(0.98)"]:
        assert needle in css, needle
    # S5 selectors keep their names
    for needle in [".words span.auto", ".badge.auto", "button.undo.hot", "button:disabled",
                   ".words span.ghost", "line-through", ".words span.choice", ".words span.choice.on"]:
        assert needle in css, needle


def test_rejected_cards_dim_by_color_not_opacity():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    rule = css[css.index(".card.rejected {"):]
    rule = rule[:rule.index("}")]
    assert "opacity" not in rule and "color: var(--fg-muted)" in rule
    assert "border-left-color: var(--status-rejected)" in rule


def test_app_js_markup_for_status_saved_edge_and_labels():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    card_ = _body(js, "function card(")
    assert '$("span", { class: "status" }, statusOf(c) === "pending" ? "" : statusOf(c))' in card_
    assert '${c.id === justSaved ? "saved" : ""}' in card_
    reply = _body(js, "function applyReply")
    assert "justSaved = c.id" in reply and reply.index("if (redraw) {") < reply.index("justSaved = c.id")
    assert "flashCard(c)" in reply and 'el.classList.add("saved")' in _body(js, "function flashCard")
    assert "justSaved = null" in _body(js, "function render")
    assert '$("b", { class: "choice-label" }, label)' in _body(js, "function chooser")
    assert '$("b", { class: "ghost-mark" }, "⌫")' in _body(js, "function ghost")
    block = _body(js, "function wordsBlock")
    assert "const edge = inside && (!insideAt(i - 1) || !insideAt(i + 1));" in block
    assert '${edge ? "edge" : ""}' in block
    # S6 added no server call; S7 added three: /api/renders, /api/render, /api/render-all;
    # S8 added six: /api/audio x3 (refresh, choose, init), /api/audio/prepare x2, /api/edit for the select
    assert js.count("api(") == 20


def test_chooser_inside_the_cut_keeps_its_tint_and_edge_outline():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".words span.chooser.in .choice { background: var(--tint-in-cut); }" in css
    assert ".words span.chooser.edge { outline: 1px solid var(--accent); outline-offset: -1px; }" in css
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function chooser(c, e, inside, edge)" in js
    assert '`chooser ${inside ? "in" : ""} ${edge ? "edge" : ""}`' in _body(js, "function chooser")
    assert "chooser(c, ce, inside, chooserEdge)" in _body(js, "function wordsBlock")


def test_render_clears_just_saved_in_a_finally():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    body = _body(js, "function render")
    assert "finally" in body and body.index("finally") < body.index("justSaved = null")


def test_dropped_cards_keep_the_neutral_bar():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "#dropped .card { border-left-color: var(--border-quiet); }" in css
    assert css.index("#dropped .card { border-left-color") > css.index(".card.rejected {")


_EDGE_HARNESS = """
const S = { words: Array.from({length: 12}, (_, i) => [i, "w" + i]), auto_edits: [%s] };
const views = %s;
const calls = [];
const $ = (tag, attrs = {}, ...kids) => ({ tag, attrs, append(...x) { calls.push(...x); } });
const spansOf = () => [[3, 8]];
const wordIndexAt = (t) => t;
const slotView = (i) => views[i] || { text: S.words[i][1], flag: "raw", edit: null };
const chooser = (c, e, inside, edge) => ({ chooser: true, first: e.first, inside, edge });
const ghost = () => ({ ghost: true });
const fmt = String, KEYS = {}, padStart = (i) => i, padEnd = (i) => i;
const setEdge = () => {}, fixWord = () => {};
%s
wordsBlock({});
const out = {};
for (const x of calls) {
  if (x.chooser) out["chooser" + x.first] = !!x.edge;
  else if (x.tag === "span" && x.attrs.title) out[x.attrs.title.split(" ")[0]] = /edge/.test(x.attrs.class);
}
console.log(JSON.stringify(out));
"""


def _run_edges(edits, views):
    import json

    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    src = _EDGE_HARNESS % (edits, views, "function " + _body(js, "function wordsBlock")[len("function "):] + "\n}")
    done = subprocess.run([node, "-e", src], check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(done.stdout)


def test_edge_outline_lands_on_a_chooser_that_opens_the_cut():
    out = _run_edges(
        "{first: 3, last: 4}",
        '{3: {flag: "choice", edit: 0}, 4: {flag: "choice", edit: 0}, 6: {flag: "ghost", text: ""}}')
    assert out["chooser3"] is True       # the chooser opens the cut
    assert out["5"] is False             # word 5 no longer borrows the outline
    assert out["7"] is True              # the last shown word before the cut ends


def test_edge_outline_lands_on_a_chooser_that_closes_the_cut():
    out = _run_edges(
        "{first: 6, last: 7}",
        '{6: {flag: "choice", edit: 0}, 7: {flag: "choice", edit: 0}}')
    assert out["chooser6"] is True       # next shown slot (8) is outside the cut
    assert out["5"] is False


def test_drawers_render_state_and_queue_controls():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    # _body(js, "function render") must keep finding render() itself (naming rule above)
    assert not re.search(r"function render(?!\(\)|All\(\))", js)
    for needle in ['"/api/renders"', '"/api/render"', '"/api/render-all"', "`/renders/${c.id}.mp4`",
                   '"aria-expanded"', "shorts.review.open.", "POLL_MS = 2000", '"not rendered"',
                   "`rendered ${v}`", "`out of date (${v})`", '"rendering…"', '"queued"', '"failed"',
                   '"▶ watch"', "`render all (${n})`", 'rel: "noopener"', 'target: "_blank"',
                   "r.error"]:
        assert needle in js, needle
    load = _body(js, "function loadOpen")
    assert "localStorage" in load and "catch" in load
    assert "catch" in _body(js, "function saveOpen")
    sync = _body(js, "function syncRenders")
    assert "render()" not in sync and "renderAll()" not in sync      # polling never steals the focus
    refresh = _body(js, "async function refreshRenders")
    assert "if (busy())" in refresh and "catch" in refresh and "setTimeout(refreshRenders, POLL_MS)" in refresh
    assert "refreshRenders()" in _body(js, "function applyReply")
    slot = _body(js, "function stateSlot")
    assert 'statusOf(c) === "approved"' in slot and "NEEDS_RENDER.includes(r.state)" in slot
    assert "if (r.file)" in slot
    card_ = _body(js, "function card(")
    assert "heads[c.id] = " in card_ and "toggleDrawer(c, el, toggle)" in card_
    assert "openIds.has(c.id)" in card_
    assert "delete heads[id]" in _body(js, "function renderAll")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<button type="button" id="render-all" disabled>render all (0)</button>' in html
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".card:not(.open) > .drawer-body { display: none; }" in css
    assert ".drawer-toggle .drawer-title" in css and "text-overflow: ellipsis" in css


def test_render_chips_use_only_tested_color_pairs():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    block = css[css.index("/* ---- drawers and render state"):css.index("/* ---- dropped candidates")]
    colors = set(re.findall(r"(?<![-\w])color: var\((--[\w-]+)\)", block))
    borders = set(re.findall(r"border-color: var\((--[\w-]+)\)", block))
    tested = {"--fg-default", "--fg-muted", "--status-approved", "--status-rejected"}
    assert colors and colors <= tested, colors
    assert borders <= tested | {"--border-quiet"}, borders


def test_render_labels():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    import json
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    src = _body(js, "function stateLabel") + "\n}\n" + """
console.log(JSON.stringify([
  stateLabel({state: "not_rendered", version: null}),
  stateLabel({state: "rendered", version: "4"}),
  stateLabel({state: "out_of_date", version: "3"}),
  stateLabel({state: "out_of_date", version: null}),
  stateLabel({state: "queued"}), stateLabel({state: "rendering"}), stateLabel({state: "failed"}),
]));"""
    done = subprocess.run([node, "-e", src], check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(done.stdout) == ["not rendered", "rendered v4", "out of date (v3)",
                                       "out of date (v?)", "queued", "rendering…", "failed"]


def test_open_drawers_survive_junk_storage():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    import json
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    funcs = "\n".join(_body(js, h) + "\n}\n" for h in ("function loadOpen", "function saveOpen"))
    src = """
let openIds = new Set();
const S = { job: "j" };
const openKey = () => `shorts.review.open.${S.job}`;
const out = [];
let store = {};
globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
""" + funcs + """
loadOpen(); out.push([...openIds]);
store["shorts.review.open.j"] = '["c1","c2"]'; loadOpen(); out.push([...openIds]);
store["shorts.review.open.j"] = '{"x": 1}'; loadOpen(); out.push([...openIds]);
store["shorts.review.open.j"] = 'not json'; loadOpen(); out.push([...openIds]);
globalThis.localStorage = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
loadOpen(); out.push([...openIds]); saveOpen();
console.log(JSON.stringify(out));"""
    done = subprocess.run([node, "-e", src], check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(done.stdout) == [[], ["c1", "c2"], [], [], []]


def test_theme_picker_is_a_corner_icon_that_opens_a_menu():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for needle in ['id="theme-toggle"', 'aria-label="Theme"', 'aria-expanded="false"', 'id="theme" role="group"', " hidden>"]:
        assert needle in html, needle
    js = (STATIC / "theme.js").read_text(encoding="utf-8")
    for needle in ['"theme-toggle"', "menu.hidden = !open", '"Escape"', 'closest("#theme-menu")']:
        assert needle in js, needle
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "#theme[hidden] { display: none; }" in css and "position: absolute" in css


def test_audio_panel_markup_and_labels():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<section id="audio" hidden' in html
    assert html.index('id="audio"') < html.index('id="stage"')
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for needle in ['"/api/audio"', '"/api/audio/prepare"', "/media/excerpt/", "Audio: dereverb ",
                   "Preparing audio…", "Try again", '"Choose"', "▶ play", "class (",
                   "Choose the audio strength first", "audio-select", "chip audio",
                   'dereverb: sel.value === "" ? null : Number(sel.value)']:
        assert needle in js, needle


def test_render_buttons_wait_for_the_strength():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "gateOpen()" in js
    slot = js[js.index("function stateSlot"):js.index("function syncRenders")]
    assert "gateOpen()" in slot and "GATE_TIP" in slot
    summary = js[js.index("function syncSummary"):js.index("// ---- rendering ----")]
    assert "!gateOpen()" in summary


def test_excerpt_and_master_never_play_together():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    play = js[js.index("function playExcerpt"):]
    assert "player.pause()" in play[:400]
    assert 'player.addEventListener("play", () => excerptPlayer.pause())' in js
    assert "AbortError" in play[:600]                       # an interrupted play() is not an error
    choose = js[js.index("function chooseStrength"):]
    assert choose.index("excerptPlayer.pause()") < choose.index("api(")   # stop the sound on choosing


def test_audio_draw_function_keeps_the_render_naming_rule():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function drawAudio()" in js and "function renderAudio" not in js


def test_audio_styles_use_tokens():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for needle in ["#audio", ".audio-row", ".audio-row.chosen", ".chip.audio", ".audio-error"]:
        assert needle in css, needle


def test_off_can_be_chosen_while_the_excerpt_is_missing_or_failed():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    draw = js[js.index("function drawAudio"):js.index("function audioSelect")]
    assert "offRow()" in draw and draw.count("offRow()") >= 2      # failed and preparing states
    row = js[js.index("function offRow"):js.index("function drawAudio")]
    assert "chooseStrength(0)" in row and "▶ play" not in row
