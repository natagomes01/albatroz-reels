# ADR-0003: Review page brand assets are local copies, fonts share assets/fonts

- **Status:** accepted
- **Date:** 30/09/26

## Context
Phase S6 put the review page in the Albatroz design system. The source of truth is the studio repo (`~/dev/studio/brand/design-sys/`: `colors_and_type.css`, fonts, the symbol SVG). The page is served by `shorts review` on `127.0.0.1` only and must work offline. The captions already load fonts from `assets/fonts/` through libass `fontsdir`, and libass reads every font file in that folder.

## Decision
- Copy the brand values into `src/shorts/review/static/tokens.css` (header comment names the source file and the copy date) and copy the symbol SVG byte for byte. `style.css` uses token names only.
- Bundle Raleway (variable) and IBM Plex Mono 400 in `assets/fonts/` next to Anton, from `google/fonts` at a pinned commit, with their OFL licences, and serve them through a read-only route `GET /fonts/<name>.ttf` (only `.ttf`, path resolved and confined to the folder).
- Keep the theme choice in the browser (`localStorage["shorts.review.theme"]`), never in `review.json`.

## Consequences
- The page has no network dependency and no dependency on the studio folder existing on the Mac; a test forbids `http`, `@import` and `fonts.googleapis` under `static/`.
- A brand change in the studio does not reach the page until someone copies it again; the contrast test then checks the new values.
- The caption renderer sees two more fonts. `tests/test_fonts_dir.py` renders the same caption frame with only Anton and with the whole folder and requires the same md5.
- The server gains one more static route; its guard is tested against `..`, encoded dots, non-font files and foreign hosts.

## Alternatives considered
- **Read the tokens from the studio repo at runtime:** breaks when the folder moves or is absent, and couples two repos.
- **Load fonts from Google Fonts:** needs the network and sends requests off the machine.
- **A separate folder for page fonts:** avoids the libass question but splits fonts and licences in two places; the md5 test covers the risk instead.
- **Store the theme in `review.json`:** mixes a viewer preference with versioned clip decisions that feed the render.
