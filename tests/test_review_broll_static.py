import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "shorts" / "review" / "static"


def js():
    return (STATIC / "broll.js").read_text(encoding="utf-8")


def test_broll_js_loads_after_app_js():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/static/app.js"') < html.index('src="/static/broll.js"')


def test_broll_js_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    subprocess.run([node, "--check", str(STATIC / "broll.js")], check=True)


def test_labels_are_exact():
    text = js()
    for label in ['"B-roll"', '"Suggesting B-roll…"', '"Suggest B-roll"', '"Suggest again"', '"Try again"',
                  '"Select words"', '"B-roll here"', '"Search"', '"Use my file"', '"Drop"', '"Credit"', '"Copy"',
                  '"suggested"', '"mine"', '"full screen"', '"split"', '"fill"', '"whole"', '"left to right"',
                  '"right to left"', '"top to bottom"', '"bottom to top"', '"still"', "`B-roll ${n}`"]:
        assert label in text, label


def test_routes_and_upload_headers():
    text = js()
    for needle in ["/api/broll", "/api/broll/candidates/", "/api/broll/suggest", "/api/broll/search",
                   "/api/broll/pick", "/api/broll/use-file", "/api/broll/files", "/api/broll/upload",
                   "/media/broll-thumb/", "/media/broll/", '"X-File-Name"', "encodeURIComponent(file.name)", "file.type",
                   "navigator.clipboard.writeText", "dragover", "drop", "pointerdown", "ArrowLeft"]:
        assert needle in text, needle


def test_app_js_calls_the_broll_hooks_only_when_present():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    for hook in ["brollSection", "brollWordClick", "brollMarked", "brollChip", "refreshBroll", "pollBroll"]:
        assert f'typeof {hook} === "function"' in app, hook
    assert "broll_dropped" in app and "its words left the clip" in app
    assert len(app.splitlines()) < 800


def test_moment_edits_send_the_whole_list_through_the_clip_queue():
    text = js()
    assert "queued(c, " in text and "edit: { broll:" in text and "applyReply(c, " in text


def test_a_carried_error_shows_in_every_state():
    # the server keeps `error` from an earlier task while the clip is queued or working again
    text = js()
    assert '(running && st.error)' in text and 'st.state === "failed"' in text
    assert 'st.error || "failed"' in text


def test_style_has_the_broll_classes_and_tokens_only():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for cls in [".broll", ".moment", ".bgrid", ".bpreview", ".bcaption", ".bspeaker", ".bsel", ".chip.broll",
                ".warn"]:
        assert cls in css, cls
    assert "var(--warn)" in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)


def test_tokens_define_warn_in_every_theme():
    css = (STATIC / "tokens.css").read_text(encoding="utf-8")
    assert "--c-amber: #8A5A00;" in css and "--c-amber-light: #E0A43A;" in css
    assert css.count("--warn: var(--c-amber-light);") == 2 and "--warn: var(--c-amber);" in css


def _run_node(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = (
        "const vm=require('vm'),fs=require('fs');const ctx=vm.createContext({});"
        f"vm.runInContext(fs.readFileSync({str(STATIC / 'broll.js')!r},'utf8'),ctx);"
        f"const r=vm.runInContext({body!r},ctx);console.log(JSON.stringify(r));"
    )
    out = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True).stdout
    import json
    return json.loads(out)


def test_arrow_nudges_accumulate_and_clamp():
    # three quick presses, each from the value the previous one produced
    r = _run_node("let f=[0.5,0.5];for(let i=0;i<3;i++)f=nudgeFocus(f,'ArrowRight');"
                  "[f,nudgeFocus([0.99,0.01],'ArrowRight'),nudgeFocus([0.01,0.01],'ArrowUp'),nudgeFocus([0.5,0.5],'a')]")
    assert r[0] == pytest.approx([0.56, 0.5])
    assert r[1] == [1, 0.01] and r[2] == [0.01, 0] and r[3] is None


def test_ended_clips_needs_a_running_clip_that_stopped():
    r = _run_node("endedClips({a:{state:'working'},b:{state:'queued'},c:{state:'idle'},d:{state:'working'}},"
                  "{a:{state:'idle'},b:{state:'failed'},c:{state:'idle'},d:{state:'working'},e:{state:'idle'}})")
    assert sorted(r) == ["a", "b"]


def test_section_signature_changes_with_state_moments_or_details():
    r = _run_node("[sectionSig({state:'idle'},[],{}) === sectionSig({state:'idle'},[],{}),"
                  "sectionSig({state:'idle'},[],{}) === sectionSig({state:'working'},[],{}),"
                  "sectionSig({state:'idle'},[1],{}) === sectionSig({state:'idle'},[],{})]")
    assert r == [True, False, False]


def test_polling_rearms_and_edits_do_not_redraw_the_page():
    text = js()
    tick = text[text.index("async function tickBroll"):text.index("async function loadDetails")]
    assert "finally" in tick and "catch (err)" in tick and "note(" in tick
    assert "reqSeq" in text and "document.activeElement" in text and "dragging" in text
    save = text[text.index("function saveList"):text.index("function afterEdit")]
    assert ", false);" in save and "render()" not in save


def test_every_function_broll_js_calls_by_name_is_defined():
    text = js()
    defined = set(re.findall(r"^(?:async )?function (\w+)", text, re.M))
    called = set(re.findall(r"(?<![.\w$])([a-z]\w*)\(", text)) & set(
        re.findall(r"\b(render\w*|redraw\w*|nudge\w*|save\w*|load\w*|poll\w*|tick\w*|after\w*|clamp\w*|"
                   r"fill\w*|broll\w*|ended\w*|section\w*|preview|pans\w*|select\w*|toggle\w*|add\w*|"
                   r"drop\w*|suggest\w*|search\w*|pick\w*|upload\w*|use\w*|copy\w*|moment\w*|candidate\w*)\(", text))
    external = {"render", "renderAll"}   # app.js
    assert not (called - defined - external), called - defined - external
