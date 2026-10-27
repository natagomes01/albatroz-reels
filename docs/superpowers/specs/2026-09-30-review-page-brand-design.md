# Review page brand pass: design

Status: approved by the owner on 30/09/2026, with the theme switch added at review (section 3). Written in a brainstorming session with the owner; every choice below is an owner answer unless marked "our extension".
Roadmap: phase S6 (`_think/roadmap.md`). Branch for the build: `s6-review-brand`, from `main` after S5 is merged.
Source of truth for the brand: `~/dev/studio/brand/design-sys` (`README.md`, `SKILL.md`, `colors_and_type.css`, `assets/`, `ui_kits/`).
Parent specs: `docs/superpowers/specs/2026-09-28-shorts-pipeline-design.md` (section 7, the review page), `docs/superpowers/specs/2026-09-30-review-undo-and-choose-design.md` (S5: Undo and Redo buttons, ghost chips, the Suggestion/Mine chooser).

## 1. Goal

Restyle the review page (`src/shorts/review/static/`) with the Albatroz design system: its colors, fonts, spacing, radii and interface rules. The page must stay a fast work tool: the video, the word chips and the approve, reject and pending states must be easier to read than today, not harder.

Success: on the 10-minute sample job, in both light and dark system settings, the owner can tell at a glance which clips are approved, rejected or pending, which words are inside the cut, which are the owner's fixes, which are suggestions, which were removed (ghost chips), and which side of a chooser is active; and the page looks like an Albatroz product.

## 2. Non-goals

- Any change to `state.py`, the JSON contract, `review.json` or the API routes other than the one font route in section 6.3.
- Any change to page behavior in `app.js` (clicks, keys, prompts, what is sent). The theme switch of section 3 lives in its own file, `static/theme.js`.
- Changing button and marker text, including the unicode markers `▶` and `⌫` (section 5.3).
- Changing the video captions or renders (section 6.4).
- Kameron and GT Sectra Display. GT Sectra is ruled out by the owner; Kameron (the design system's stand-in for it) has no job on a work page.
- The design system's marketing patterns: hero, footer, session blocks, full-bleed imagery, shadows, Lucide icons.

## 3. Themes

Two themes, designed together: **light** (the brand default) and **dark**. The dark values are **our extension**: the design system defines no dark mode, so section 4 marks every dark value we chose.

**Theme switch** (owner request, 30/09/2026). A three-way switch in the header, right-aligned: `LIGHT`, `DARK`, `SYSTEM`, rendered as three ghost buttons side by side (section 5.3 style, the active one with a 2px `--border-strong` border and `aria-pressed="true"`). Default: `SYSTEM`.

- `SYSTEM` follows the Mac setting live (`prefers-color-scheme`), as before.
- `LIGHT` and `DARK` force a theme regardless of the Mac setting.
- Mechanism: `static/theme.js` sets `data-theme="light"` or `data-theme="dark"` on `<html>`, or removes the attribute for `SYSTEM`. The CSS selectors are in section 4.2.
- The choice is remembered in the browser's `localStorage` under `shorts.review.theme` (`light`, `dark` or `system`). It is a viewer convenience, so it stays out of `review.json` and the server. Every read and write is wrapped in `try`/`catch`; when storage fails or holds an unknown value, the page falls back to `SYSTEM`.
- `theme.js` loads in `<head>` without `defer`, before the stylesheets, and applies the stored choice at once, so a forced theme never flashes the other one on load. It wires the three buttons on `DOMContentLoaded`.
- The switch is plain buttons, so Tab and Enter work; no keyboard shortcut.

The stage band (the sticky video area) stays dark in both themes, because video is judged against a dark surround.

## 4. Tokens (`static/tokens.css`)

A trimmed copy of the design system's tokens plus our additions. Header comment: source path, the date it was copied, and the list of our extensions. `style.css` uses only the semantic names below and the spacing, radius, type and motion tokens; it holds no raw color value.

### 4.1 Brand primitives copied from `colors_and_type.css`

`--c-army #696858`, `--c-offwhite #F2EDE4`, `--c-charcoal #202020`, `--c-slate #5F6870`, `--c-paper #FCFCFC`, `--c-dark-4 #A8A8A8`, `--c-medium-2 #7A7A68`, `--c-medium-3 #989880`, `--c-accent-500 #F04500`, `--c-accent-400 #F07040`.

### 4.2 Semantic names

The light values sit on `:root`. The dark values are written twice, with the same content: once under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }` (SYSTEM on a dark Mac) and once under `:root[data-theme="dark"]` (forced DARK). `<meta name="color-scheme">` stays `light dark`, and `tokens.css` sets `color-scheme: light` under `:root[data-theme="light"]` and `color-scheme: dark` under `:root[data-theme="dark"]`, so native controls (the video bar, scrollbars, the `<details>` marker) follow a forced theme.

| Name | Light | Dark (our extension) |
|---|---|---|
| `--bg-page` | `#F2EDE4` off-white | `#202020` charcoal |
| `--bg-card` | `#FCFCFC` paper | `#2B2B28` |
| `--bg-stage` | `#202020` charcoal | `#141413` |
| `--fg-default` | `#202020` | `#F2EDE4` |
| `--fg-muted` | `#5F6870` slate | `#A8A8A8` |
| `--fg-on-stage` | `#F2EDE4` | `#F2EDE4` |
| `--border-quiet` | charcoal at 12% | off-white at 12% |
| `--border-strong` | `#202020` | `#F2EDE4` |
| `--accent` | `#F04500` | `#F04500` |
| `--accent-hover` | `#F07040` | `#F07040` |
| `--status-approved` | `#696858` army | `#989880` khaki |
| `--status-rejected` | `#9A3324` brick (our extension) | `#DD7A63` light brick (our extension) |
| `--tint-in-cut` | army at 14% | khaki at 10% |
| `--primary-bg` / `--primary-fg` / `--primary-hover` | army / off-white / `#7A7A68` | same |

Brick is the one color outside the brand palette, added by the owner for rejected clips. In dark, `#B8472F` (the first choice) failed contrast (2.69:1 on the card), so the dark brick is lighter; it stays apart from the orange accent because orange never appears on a status bar or label, and the rejected state always carries its `REJECTED` label.

### 4.3 Where orange is allowed

Only: the 7px top stripe, the keyboard focus ring, the score number, the cut-edge outline on words, and S5's highlight on the last-touched clip's Undo button. Never as a background, never on a status.

### 4.4 Other tokens

- Spacing: the brand's Fibonacci scale (`--space-xxs 8px`, `--space-xs 16px`, `--space-s 24px`, `--space-m 40px`, `--space-l 64px`) plus `--space-3xs: 4px` (our extension) for the inside of chips and badges. The larger brand steps are not used.
- Radii: `--r-none 0`, `--r-sm 2px`.
- Motion: `--ease-out cubic-bezier(0.22, 0.61, 0.36, 1)`, `--dur-fast 140ms`, `--dur-base 220ms`. All transitions are off under `prefers-reduced-motion: reduce`.
- Layers (our extension): `--z-stage: 10`, `--z-stripe: 100`.
- Font stacks: `--font-headline` (Anton), `--font-body` (Raleway), `--font-mono` (IBM Plex Mono), each with system fallbacks.

### 4.5 Contrast

Checked with the WCAG formula (the plan's `tests/test_review_contrast.py` run against the planned `tokens.css`; all pass):

| Pair | Light | Dark | Needed |
|---|---|---|---|
| default text on page / on card | 13.97 / 15.88 | 13.97 / 12.18 | 4.5 |
| muted text on page / on card | 4.87 / 5.53 | 6.85 / 5.97 | 4.5 |
| approved label on card | 5.50 | 4.83 | 4.5 |
| rejected label on card | 7.12 | 4.76 | 4.5 |
| score (orange, 40px) on card | 3.68 | 3.76 | 3.0 |
| text on the stage | 13.97 | 15.81 | 4.5 |
| off-white on the Approve button | 4.84 | 4.84 | 4.5 |
| default text on the in-cut tint | 13.19 | 10.43 | 4.5 |
| muted text on the in-cut tint (rejected cards) | 4.60 | 5.12 | 4.5 |
| orange edge outline on the in-cut tint | 3.06 | 3.22 | 3.0 |

`tests/test_review_contrast.py` (section 8) keeps these pairs honest.

## 5. Components (`static/style.css`)

The brand rules (square corners, caps labels, lines instead of boxes, scarce orange) at work-tool density.

### 5.1 Page frame

- 7px orange stripe, `position: fixed` at the top, `z-index: var(--z-stripe)`. The body gets `padding-top: 7px` and the stage `top: 7px`, so nothing slides under the stripe.
- Header: the theme switch (section 3) on the right; on the left, the albatross symbol (`static/albatroz-symbol.svg` drawn through a CSS `mask` on a `<span class="brand-mark">`, because an SVG loaded as an image cannot take `currentColor`; colored `--status-approved`, army in light, khaki in dark; 28px high, width from the file's 624 by 159 ratio), the job title in Anton caps 32px, and the summary under it as a caps label (Raleway Bold 12px, tracking 0.12em, `--fg-muted`). Side padding `--space-s`.
- Content column: `max-width: 1200px`, centered.
- Body: Raleway 400, 16px, line height 1.5, `font-variant-numeric: lining-nums tabular-nums` (Raleway defaults to old-style figures, which make scores and times jump between cards).

### 5.2 Stage and cards

- **Stage:** full-width sticky band on `--bg-stage`, `z-index: var(--z-stage)`. Video 480px wide (45vw max), square corners. The "now playing" text is `--fg-on-stage`.
- **Card:** `--bg-card`, radius 0, 1px `--border-quiet`, 6px left bar, inner gap `--space-xs`, `--space-s` between cards.
- **Status:**
  - pending: bar in `--border-quiet`, no label;
  - approved: bar in `--status-approved`, label `APPROVED` top right (caps 12px, same color);
  - rejected: bar in `--status-rejected`, label `REJECTED`, and the card content switches to `--fg-muted` with the score no longer orange. Owner asked for a 55% opacity dim; the contrast check showed muted text falls to 2.31:1 at that opacity, so the dim is done with the muted text color instead, which reads as dimmed and stays at 4.87:1 or better.
  - The label is a new `<span class="status">` in the card's top row, written by `app.js` (text only, no behavior), set in caps by CSS.
  - Save feedback: `render()` rebuilds every card after each save, so a CSS transition cannot fire. Instead, `app.js` marks the card it just saved with the class `saved` for that one render, and CSS plays a `--dur-base` animation on its left bar (from `--accent` to the status color). Any save shows it, not only a status change; a title or hook save, which keeps the focus and does not redraw, replays the flash on the live card. Off under reduced motion.
- **Group** (clips from the same stretch): a 1px `--border-strong` top rule with the group label as a caps eyebrow. Replaces the dashed rounded box.
- **Score:** Anton 40px, `--accent`. **Score bars:** 4px tall, square, `--fg-muted` on a `--border-quiet` track. The bar width stays the inline style `app.js` already writes (it is data).
- **Reasoning text (`.why`):** `--fg-muted`, `max-width: 75ch`.
- **Title and hook inputs:** Raleway 16px on `--bg-page`, 1px `--border-quiet`, radius `--r-sm`.
- **Dropped candidates:** `<details>` with an Anton 24px caps header; its cards use the rejected treatment without the brick bar.

### 5.3 Buttons, badges and marks

- **Buttons:** Raleway Bold 12px caps, tracking 0.08em, padding 8px by 16px, `min-height: 32px`, at least 8px between neighbors, radius 0.
  - Approve, the one primary: `--primary-bg` fill, `--primary-fg` text, hover `--primary-hover`.
  - Reject: ghost with a 2px `--status-rejected` border.
  - Everything else (play, sentence and edge nudges, Undo, Redo): ghost with a 1px `--border-quiet` border, hover `opacity: 0.7`.
  - Press: `transform: scale(0.98)` over `--dur-fast`. Disabled: `opacity: 0.4`, `cursor: not-allowed`.
- **Badges:** caps 11px, padding `--space-3xs` by 8px, radius `--r-sm`. warn: slate outline; bad: brick outline; auto: slate outline.
- **Mono:** Plex Mono 13px for timecodes, durations, clip ids and the key-hint line.
- **Unicode markers:** `▶` and `⌫` stay (owner decision), a documented exception to the design system's "no unicode as icon" rule.
- **Focus:** `:focus-visible` only: 2px `--accent` outline, offset 4px A mouse click leaves no ring. Word chips are mouse-only (as in S5), so the ring shows on buttons, inputs and the theme switch.

### 5.4 Word chips and S5's elements

Chip base: Raleway 16px, padding 2px by 4px, `min-height: 24px` hit area, radius `--r-sm`, line height 2 on the text block so the lines do not move. Every state differs by more than hue.

| State | Look |
|---|---|
| outside the cut | `--fg-muted`, no background |
| inside the cut (`.in`) | `--fg-default` on `--tint-in-cut` |
| cut edge (`.edge`, the first and last word inside each cut) | 1px `--accent` outline |
| owner fix (`.fixed`) | Bold 700 with a 2px `--status-approved` underline |
| suggestion applied (`.auto`) | 400 with a 1px dotted `--fg-muted` underline; `AUTO` badge in slate outline |
| segment separator | S5's `[…]` in Plex Mono, `--fg-muted` |
| ghost chip (S5) | raw word in `--fg-muted`, line-through, opacity 0.6, `⌫` in Plex Mono 11px (`<b class="ghost-mark">`); full opacity on hover |
| chooser (S5) | two boxes side by side, each headed by a 10px caps label (`SUGGESTION`, `MINE`; `app.js` wraps the label in `<b class="choice-label">` in place of today's `Suggestion: ` prefix); active: 2px solid `--border-strong`, `--fg-default`; inactive: 1px dashed `--border-quiet`, `--fg-muted`. No orange |
| last-touched clip (S5) | its Undo button gets a 2px `--accent` border |

## 6. Files

### 6.1 New

- `assets/fonts/Raleway-Variable.ttf` (from `ofl/raleway/Raleway[wght].ttf`; Google Fonts now ships Raleway only as a variable font, so one file serves 400 and 700) and `assets/fonts/IBMPlexMono-Regular.ttf` (from `ofl/ibmplexmono/`), both from the `google/fonts` GitHub repository at commit `9710da1eacb3be272583c3224dcb70f9da6eadbb` (30/09/2026).
- `assets/fonts/OFL-Raleway.txt`, `assets/fonts/OFL-IBMPlexMono.txt` (Anton's `OFL.txt` keeps its name).
- `src/shorts/review/static/tokens.css` (section 4), with `@font-face` rules for Anton, Raleway (`font-weight: 100 900`, the variable file) and Plex Mono 400, `src: url("/fonts/<file>.ttf")`, `font-display: swap`.
- `src/shorts/review/static/albatroz-symbol.svg`: copy of the design system's `assets/albatroz-symbol.svg`.
- `src/shorts/review/static/theme.js`: the theme switch of section 3 (about 40 lines, no dependencies).

About 450 KB in total; each file is under the 5 MB pre-commit limit.

### 6.2 Changed

- `static/style.css`: rewritten on the tokens (section 5).
- `static/index.html`: links `tokens.css` then `style.css`; `<meta name="color-scheme" content="light dark">`; `<link rel="preload" href="/fonts/Raleway-Variable.ttf" as="font" type="font/ttf" crossorigin>`; `<script src="/static/theme.js"></script>` in `<head>` before the stylesheets; the stripe element; the symbol and the theme switch in the header. Every element id `app.js` uses stays.
- `static/app.js`: markup only: the `<span class="status">` label and the one-render `saved` class (section 5.2); the `edge` class on the first and last word inside each cut, the chooser's `choice-label` and the ghost chip's `ghost-mark` (section 5.4). S5 no longer sets any edge class, so S6 adds it back for the outline of section 5.4. No change to what is sent or when.

### 6.3 Server exception

`server.py` gains `GET /fonts/<name>` (and `HEAD`), served from `REPO_ROOT/assets/fonts/` with the same "resolved path must stay inside the folder" guard as `/static/`, for `.ttf` files only; anything else is 404. `_TYPES` gains `.ttf: font/ttf` and `.svg: image/svg+xml`. The host check applies as on every other route. Nothing else in the server, `state.py` or the JSON contract changes.

### 6.4 Renders are unaffected

The captions point libass at `assets/fonts/` (`render.py`, `fontsdir`) and ask for Anton by name, so the extra TTFs do not change which font is used, and the render key does not include that folder. The plan checks this once: render one sample clip before and after adding the fonts and compare the file hashes.

## 7. Page never reaches the network

No `@import`, no Google Fonts, no CDN. Every file comes from the local server, so the page works offline and sends nothing out.

## 8. Testing

- `tests/test_review_static.py`:
  - `tokens.css` defines every semantic name of section 4.2 in the light block, and the dark blocks override only names the light block defines (names with one value for both themes, such as `--accent`, are not repeated);
  - `style.css` has no `#hex`, `rgb(` or `hsl(` value;
  - nothing under `static/` contains `http`, `fonts.googleapis` or `@import`;
  - `GT Sectra` and `Kameron` appear nowhere under `static/`;
  - the S5 needles still match, and `node --check` passes on `app.js` and `theme.js`;
  - `tokens.css` has the dark block under both selectors of section 4.2, with the same names and values;
  - `theme.js` uses the `shorts.review.theme` key, wraps storage in `try`, and `index.html` loads it in `<head>` before `tokens.css`.
- `tests/test_review_contrast.py` (new): parses the hex values in `tokens.css` (resolving `var()` and the percentage mixes of section 4.2) and asserts every pair of section 4.5 in both themes, failing with the pair and the ratio.
- `tests/test_review_server.py`:
  - `/fonts/Anton-Regular.ttf` returns 200 and `font/ttf`;
  - `/fonts/../config.toml`, `/fonts/OFL.txt` and a missing font return 404;
  - `/static/albatroz-symbol.svg` returns `image/svg+xml`;
  - the host check rejects a foreign `Host` on `/fonts/`.
- Repo check: the two new TTFs and their two licence files exist and each is under 5 MB.
- Live, with the owner: `shorts review` on the 10-minute sample job. The build session clicks through `LIGHT`, `DARK` and `SYSTEM` (and reloads to confirm the choice is kept) and takes Playwright screenshots in light and dark (whole page; an approved and a rejected card; clip `c6e1125` with a ghost chip and a chooser) into the job's scratch folder; the owner reviews them and uses the page once before the merge. The render hash check of section 6.4 is part of this step.

## 9. Owner answers (30/09/2026)

1. **Theme:** both. Light by default, dark following the system setting.
2. **Approved and rejected:** brand colors plus a text label; rejected gets a brick-red left bar (army for approved).
3. **Fonts:** bundled in `assets/fonts/` with their licences, served by a new `/fonts/` route (the one server exception).
4. **Font roles:** Anton for the title, score and section headers; Raleway 400 and 700 for everything else; Plex Mono 400 for timecodes, ids and key hints; no Kameron.
5. **Tokens:** a trimmed copy in `static/tokens.css`, semantic names only in `style.css`.
6. **Unicode markers:** keep `▶` and `⌫`.
7. **UI/UX Pro Max additions:** accepted all eight (tabular lining figures, `:focus-visible`, 24px chip and 32px button targets, the 4px half step, 1200px and 75ch widths, the status transition, the stripe offset and layer scale, `font-display: swap` with one preload and the 0.4 disabled state).
8. **Theme switch:** a `LIGHT` / `DARK` / `SYSTEM` switch in the header, remembered in the browser, default `SYSTEM` (added at spec review).
