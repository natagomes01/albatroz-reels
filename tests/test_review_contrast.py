"""WCAG contrast of the review page tokens in both themes (spec 4.5). The pairs are the spec's
table; a failing pair names itself and its ratio."""
import re
from pathlib import Path

import pytest

TOKENS = Path(__file__).resolve().parents[1] / "src" / "shorts" / "review" / "static" / "tokens.css"
LIGHT = ":root"
DARK = ':root[data-theme="dark"]'
SYSTEM_DARK = ':root:not([data-theme="light"])'


def block(css: str, selector: str) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no block for {selector}"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))


def theme(name: str) -> dict[str, str]:
    css = TOKENS.read_text(encoding="utf-8")
    values = block(css, LIGHT)
    if name == "dark":
        values = {**values, **block(css, DARK)}
    return values


def rgba(values: dict[str, str], name: str) -> tuple[float, float, float, float]:
    v = values[name].strip()
    while v.startswith("var("):
        v = values[v[4:-1].strip()].strip()
    if v.startswith("#"):
        return int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16), 1.0
    m = re.fullmatch(r"rgb\((\d+) (\d+) (\d+) / (\d+)%\)", v)
    assert m, f"{name}: {v}"
    return int(m[1]), int(m[2]), int(m[3]), int(m[4]) / 100


def surface(values, bg: str):
    """RGB of a background: an opaque token, or "tint/base" (a see-through tint on a base)."""
    if "/" in bg:
        tint, base = bg.split("/")
        return over(values, tint, base)
    r, g, b, a = rgba(values, bg)
    assert a == 1.0, f"{bg} must be opaque"
    return r, g, b


def over(values, fg: str, bg: str):
    r, g, b, a = rgba(values, fg)
    return tuple(a * x + (1 - a) * y for x, y in zip((r, g, b), surface(values, bg)))


def lum(rgb) -> float:
    c = [x / 255 for x in rgb]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(values, fg: str, bg: str) -> float:
    a, b = lum(over(values, fg, bg)), lum(surface(values, bg))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


PAIRS = [   # (foreground, background, floor): spec 4.5
    ("--fg-default", "--bg-page", 4.5),
    ("--fg-default", "--bg-card", 4.5),
    ("--fg-muted", "--bg-page", 4.5),
    ("--fg-muted", "--bg-card", 4.5),
    ("--status-approved", "--bg-card", 4.5),
    ("--status-rejected", "--bg-card", 4.5),
    ("--warn", "--bg-card", 4.5),
    ("--warn", "--bg-page", 4.5),
    ("--accent", "--bg-card", 3.0),
    ("--fg-on-stage", "--bg-stage", 4.5),
    ("--primary-fg", "--primary-bg", 4.5),
    ("--fg-default", "--tint-in-cut/--bg-card", 4.5),
    ("--fg-muted", "--tint-in-cut/--bg-card", 4.5),
    ("--accent", "--tint-in-cut/--bg-card", 3.0),
]


@pytest.mark.parametrize("name", ["light", "dark"])
@pytest.mark.parametrize("fg,bg,floor", PAIRS)
def test_contrast(name, fg, bg, floor):
    r = ratio(theme(name), fg, bg)
    assert r >= floor, f"{name}: {fg} on {bg} is {r:.2f}:1, needs {floor}:1"


def test_known_ratios_match_the_spec():
    assert round(ratio(theme("light"), "--fg-muted", "--bg-page"), 2) == 4.87
    assert round(ratio(theme("dark"), "--status-rejected", "--bg-card"), 2) == 4.76
    assert round(ratio(theme("dark"), "--accent", "--tint-in-cut/--bg-card"), 2) == 3.22


def test_dark_values_are_identical_under_both_selectors():
    css = TOKENS.read_text(encoding="utf-8")
    forced, system = block(css, DARK), block(css, SYSTEM_DARK)
    assert forced == system and len(forced) >= 10
    assert set(forced) <= set(block(css, LIGHT))       # dark overrides names the light block defines


def test_light_choice_excludes_the_system_dark_block():
    css = TOKENS.read_text(encoding="utf-8")
    media = css[css.index("@media (prefers-color-scheme: dark)"):]
    assert media.index(SYSTEM_DARK) < media.index("}")          # the only rule inside the media block
    assert ':root[data-theme="light"] { color-scheme: light; }' in css
    dark = css[css.index(DARK):]
    assert "color-scheme: dark;" in dark[:dark.index("}")]
