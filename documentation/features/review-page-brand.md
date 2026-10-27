# Review page brand pass (S6): technical reference

> Phase: S6 | Branch: `s6-review-brand` (merged into `main` on 30/09/2026) | Tests: `tests/test_review_contrast.py`, `tests/test_review_static.py`, `tests/test_review_server.py`, `tests/test_fonts_dir.py` | Lesson: [`_think/lessons/03-marca-na-pagina-de-revisao.md`](../../_think/lessons/03-marca-na-pagina-de-revisao.md)
> Reader: dev, auditor. Style: reference. Concepts (design token, WCAG contrast, system vs forced theme, variable font, path traversal) are in [`_think/lessons/_conceitos.md`](../../_think/lessons/_conceitos.md).

## Scope

The review page (`shorts review <job>`) now uses the Albatroz design system: tokens, Anton, Raleway and IBM Plex Mono, square editorial components, and a light and a dark theme with a `LIGHT` / `DARK` / `SYSTEM` switch. Style only: `state.py`, the JSON contract, `review.json` and the API did not change. Spec: `docs/superpowers/specs/2026-09-30-review-page-brand-design.md`. How to use the page: [`shorts-cli.md`, section `review`](shorts-cli.md#review).

## Files

| File | Role |
|---|---|
| `src/shorts/review/static/tokens.css` | Every color, font, spacing, radius, motion, z-index and layout value. Light on `:root`; dark under `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])` (system) and `:root[data-theme="dark"]` (forced). Header comment names the source and date. |
| `src/shorts/review/static/style.css` | Layout and components, written against token names only (no `#hex`, `rgb(`, `hsl(`). |
| `src/shorts/review/static/theme.js` | Theme switch. Loaded in `<head>` before the stylesheets, without `defer`, so the theme applies before the first paint. |
| `src/shorts/review/static/index.html` | Head order: `theme.js`, Raleway preload, `tokens.css`, `style.css`. Body: `.top-stripe`, `header > .brand` with `.brand-mark`, `#theme` group, then the S2 ids (`title`, `summary`, `stage`, `player`, `now-playing`, `cards`, `dropped`, `dropped-cards`). |
| `src/shorts/review/static/albatroz-symbol.svg` | Brand mark, byte-identical to `~/dev/studio/brand/design-sys/assets/albatroz-symbol.svg`; drawn as a CSS mask in `--status-approved`. |
| `assets/fonts/Raleway-Variable.ttf`, `IBMPlexMono-Regular.ttf`, `OFL-Raleway.txt`, `OFL-IBMPlexMono.txt` | From `google/fonts` at commit `9710da1eacb3be272583c3224dcb70f9da6eadbb` (312352 and 135580 bytes). Same folder as the caption font Anton. |
| `src/shorts/review/server.py` | `FONTS` (`server.py:22`), `_TYPES` gains `.svg` and `.ttf` (`server.py:24`), `_static(..., root, only)` (`server.py:85`), route `/fonts/` (`server.py:143-144`). |

## Invariants

- **No network.** Nothing under `static/` holds `http://`, `https://`, `@import` or `fonts.googleapis` (`test_static_never_reaches_the_network_or_banned_fonts`). The SVG's `xmlns` namespace is a string, not a request, and `.svg` is outside that scan.
- **No banned fonts.** No `GT Sectra`, no `Kameron` under `static/`.
- **Tokens only.** `style.css` holds no raw color (`test_style_uses_tokens_only`).
- **Dark blocks stay identical.** The system-dark and forced-dark blocks define the same custom properties with the same values (`test_dark_values_are_identical_under_both_selectors`).
- **Contrast floors.** 4.5:1 for text, 3:1 for the score, the cut-edge outline and status bars, in both themes, for every pair of spec 4.5 (`test_contrast`, 24 cases). Pinned ratios: light muted on page 4.87, dark rejected on card 4.76, dark accent on in-cut tint 3.22 (`test_known_ratios_match_the_spec`).
- **Orange is scarce.** `--accent` only on the 7px top stripe, the `:focus-visible` ring, the score, the cut-edge outline (word or chooser), the last-touched clip's Undo border, and the start of the saved flash.
- **Captions unchanged by the new fonts.** libass loads every file in `assets/fonts/`; the same caption frame renders with the same md5 with only Anton and with the whole folder (`test_new_fonts_do_not_change_caption_rendering`, skips without ffmpeg-full).
- **Markup only in `app.js`.** The `api(` count stays 11; no key handler or save queue changed.
- **Theme lives in the browser.** `localStorage["shorts.review.theme"]` = `light` | `dark` | `system`. Junk or a storage error means `system`. Never sent to the server, never in `review.json`.

## The `/fonts/` route

`GET` and `HEAD /fonts/<name>` call `_static(name, root=FONTS, only=".ttf")`: the path is resolved first, then it must sit inside `assets/fonts/`, be a file and end in `.ttf`; anything else is 404. The Host check runs before any routing (403 for a foreign `Host`). Content type `font/ttf`. The suffix check is case-sensitive (`X.TTF` is 404).

## Page names added in `app.js`

| Name | Where | What |
|---|---|---|
| `justSaved` | `app.js:48` | Id of the clip saved last. Set in `applyReply` only when a redraw follows; cleared in a `finally` in `render()` (`app.js:467`), which wraps `renderAll()` (`app.js:474`). |
| `flashCard(c)` | `app.js:65` | Replays the saved flash on the live card for title and hook saves, which keep focus and do not redraw. |
| class `status` | `card()` | `APPROVED` / `REJECTED` label (empty for pending), uppercased by CSS. |
| class `saved` | `card()`, `flashCard` | One-render `@keyframes saved` from the orange accent. |
| class `edge` | `wordsBlock` (`app.js:390`), `chooser()` (`app.js:322`) | First and last shown slot inside each cut. The neighbour scan steps over ghost chips and merged empty slots and counts choosers as shown; a chooser is judged on the outer neighbours of its whole range. |
| `<b class="choice-label">` | `chooser()` | `SUGGESTION` / `MINE` heading of each chooser side. |
| `<b class="ghost-mark">` | `ghost()` (`app.js:306`) | The ⌫ of a removed word, in Plex Mono 11px. |

## Visual states

| State | Look |
|---|---|
| Approved card | Left bar `--status-approved` (army), label `APPROVED`. |
| Rejected card | Left bar `--status-rejected` (brick), label `REJECTED`, text in `--fg-muted` (no opacity, which measured 2.31:1). |
| Dropped candidate | Rejected look with the neutral `--border-quiet` bar whatever its status. |
| Word inside the cut | `--fg-default` on `--tint-in-cut`; a chooser inside the cut tints its boxes. |
| Cut edge | 1px `--accent` outline on the word or chooser. |
| Owner fix | Bold, 2px `--status-approved` underline. |
| Automatic fix | Dotted 1px `--fg-muted` underline, `AUTO` badge. |
| Removed word (ghost) | `--fg-muted`, line-through, `opacity: 0.6` (2.48:1 light, 3.12:1 dark; spec value, accepted by the owner), full opacity on hover, ⌫ mark. |
| Chooser | Active side: solid `--border-strong` 2px (1px border plus 1px inset shadow); inactive: dashed `--border-quiet`. |
| Hot Undo | 2px `--accent` border on the last clip changed. |
| Keyboard focus | 2px `--accent` `:focus-visible` ring; a mouse click shows none. |

## How to debug

- **Page shows system fonts**: check `/fonts/Raleway-Variable.ttf` answers 200 (`curl -I http://127.0.0.1:8765/fonts/Raleway-Variable.ttf`). The route resolves `FONTS` with `parents[3]`, which is right for the source checkout only; a wheel install would 404 and fall back.
- **Theme does not stick**: in the browser console, `localStorage.getItem("shorts.review.theme")`; a private window may block storage (the page then follows the Mac).
- **Forced theme ignored**: `document.documentElement.getAttribute("data-theme")` must be `light` or `dark`; `SYSTEM` removes it.
- **A color looks wrong in one theme only**: compare the two dark blocks in `tokens.css`; `test_dark_values_are_identical_under_both_selectors` fails if they drifted.
- **Captions changed font after adding a file to `assets/fonts/`**: run `uv run pytest tests/test_fonts_dir.py`.
- **Console shows a `favicon.ico` 404**: expected, the page has no favicon route.

## Tests

`uv run pytest tests/test_review_contrast.py tests/test_review_static.py tests/test_review_server.py tests/test_fonts_dir.py` (87 tests at merge). `test_review_static.py` also runs `node --check` on `theme.js` and `app.js` and two node tests of the edge computation on the real `wordsBlock` code (skipped without node).

## Key decisions

ADR [0003](../decisions/0003-review-page-brand-assets-local.md) (local tokens and bundled fonts) and the lesson's "Decisões e alternativas". Build record with every ruling: `_think/sdd-runs/2026-09-30-S6/ledger.md`. Deferred minors: `_think/roadmap.md`, "Backlog (deferred from the S6 reviews...)".

## Dependencies and what comes next

Builds on S5 (undo, redo, ghost chips, chooser). Nothing depends on it. If the brand changes in the studio design system, copy the values into `tokens.css` again and update its header date; the contrast test will say whether the new values still pass.
