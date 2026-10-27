# Caption context pass: design

Status: draft for owner review (29/09/2026). Nothing is built yet.
Origin: first live run on the 10-minute sample (`260927-amostra-10min`), roadmap item "Caption context pass".
Parent spec: `docs/superpowers/specs/2026-09-28-shorts-pipeline-design.md` (sections 5, 6, 9, 11).

## 1. Goal

Whisper mishears quoted Hebrew, Greek and Aramaic words, scripture references and names, and it sometimes splits or joins words wrongly. Example from the sample: the Aramaic "lamá sabactâni" was transcribed as three words, `la massa bactamia.`. Today the owner fixes such words by hand, one slot at a time, on the review page.

This pass corrects them **automatically, before the owner opens the review page**, using the context of the whole transcript. The owner then only fixes what is still wrong. The pass never changes when a word is shown.

Success looks like this, on the 10-minute sample: after `shorts analyze`, the words of the approved clips already read "Eloí, Eloí, lamá sabactâni?" and "kaaru ... cavaram," without any manual edit; the review page shows them marked as automatic corrections; an owner fix on the same words wins over the automatic one; the rendered captions show the corrected text with the original timing.

## 2. Non-goals

- Line and screen breaks ("odd divisions" of how words are laid out on screen). That is the caption breaking rules in `captions.py` and a separate follow-up.
- Rewriting style, grammar or dialect. The speaker's register ("pra", "tá", "né") stays.
- Listening to the audio. The pass sees text and per-word confidence only.
- Changing what the scan, detail and review passes see (section 4.1).

## 3. Concepts

**Slot.** One entry of `words.json` (`Word(t, w, p)`), addressed by its raw index. A word is shown from its own `t` until the next slot's `t` (`captions.render_ass` computes it this way), so a slot has no stored end time.

**Automatic edit.** `{first, last, tokens, reason, kind, confidence}`: replace the raw slots `first..last` (inclusive) by the list of words `tokens` (1 to 12 strings). Stored per job.

**Manual fix.** The existing `decisions[clip].word_fixes` of `review.json`, keyed by raw slot index. This spec extends it in one way: the value `""` means "drop this slot" (its time is absorbed by the previous word).

**Effective words.** The word list that captions, tracking, silence cutting and the review page use: raw words, then manual fixes, then automatic edits, in the precedence of section 5.

## 4. Design

### 4.1 Where the pass runs, and why after the analysis

The pass runs as the last stage of `shorts analyze` and as its own command `shorts fixwords <job> [--all] [--force]`.

It runs **after** scan, detail and reviews, and those three passes keep reading the **raw** words. Reason: the detail pass quotes the first and last six words of each clip, and `boundaries.snap_segment` finds those quotes in the raw words. If the model saw corrected text, its quotes would no longer match and candidates would be dropped (Review Focus 1 of plan 2). Raw for analysis, corrected for display and captions.

### 4.2 Which text goes to the model

Chunks of 500 words with 100 words of overlap, cut at sentence ends (reuse `sentences()`). Each chunk is sent as lines `<index>|<word>|<confidence to 2 decimals>`. The model needs three layers of context to know that a passage is a scripture quotation in a Catholic class and which spelling is right. Findings on 30/09/2026 from the repo: today the channel glossary for `catholic-br` holds only six words (`Agostinho, deuterocanônicos, Denzinger, Magistério, Eucaristia, Septuaginta`), and the profile block (`ChannelProfile.as_prompt_block`, about 1.8 KB: ICP, audience, learned lessons) was written to score clips, not to spell words. Neither says what THIS video is about. So the pass adds two layers:

1. **Channel layer (static, per channel).** `ChannelConfig.language`, `ChannelConfig.glossary` and a new optional file `profiles/<channel>/captions.md` ("caption notes"), loaded next to the profile. For `catholic-br` it states: Catholic tradition and canon (including the deuterocanonical books), the Portuguese spellings to use for books, names and Hebrew, Greek, Aramaic and Latin terms (for example `Eloí, Eloí, lamá sabactâni`, `Septuaginta`, `Deuteronômio`), and a starter list of recurring terms. The owner grows this file over time; the channel layer digest is part of the cache key. The starter file is written in this work (section 9).
2. **Video layer (dynamic, per job).** Two sources, merged into one short block:
   - an optional owner-supplied **topic line**, given at ingest (`shorts ingest ... --topic "textual criticism of the Old Testament, Septuagint vs Masoretic text"`) and stored as `topic` in `job.json`; `shorts fixwords --topic` overrides it for one run;
   - an automatic **class sheet**: a small first pass (`claude-haiku-4-5`, same backend mechanism, pass name `class_sheet`) reads the whole transcript in a few large chunks and returns the topic in one sentence, the scripture references it hears (book, chapter, verse when spoken), the foreign-language terms and names it hears, and the terms whose spelling varies. Stored as `analyze/class_sheet.json`, cached. Each caption-fix chunk receives this sheet, so a chunk in the middle of a Hebrew example knows the whole class is about the Septuagint.

Every chunk request therefore carries: instructions (section 6), channel layer, video layer, and the chunk's own words with indices. The previous and next chunk's last and first sentences are included as read-only context lines (not editable).

**Scripture rule.** A scripture quotation is context, not a target: the pass fixes what was misheard, but never rewrites the speaker's words to match a Bible translation. If the speaker paraphrases a verse, the paraphrase stays.

Default scope: only chunks that overlap a candidate segment extended by 60 s on each side (the context the detail pass already used). `--all` runs every chunk. Scope stays wide enough that when the owner moves a cut edge on the review page, the new words are already corrected.

### 4.3 What the model returns

A JSON list of edits (schema `CAPTION_FIX` in `analyze/schemas.py`), each `{first, last, tokens, kind, reason, confidence}` with `kind` in `foreign_term`, `proper_name`, `scripture`, `mishearing`, `split_or_joined_word`, `punctuation`. An empty list is a valid answer and the common one. The model returns only edits, never the whole text.

### 4.4 Code-side validation (the model is not trusted)

An edit is dropped, with a logged reason (`fixword_dropped`), when any of these holds:

- indices out of range, `first > last`, or more than 12 slots;
- `tokens` empty, more than 12 tokens, a token empty or longer than 40 characters, or containing ASS override characters (`{`, `}`, `\`) after `clean_word`;
- overlaps another accepted edit (the one with the higher confidence wins);
- `confidence` below 0.6;
- an edit that changes nothing.

The whole pass is aborted for a chunk, with a readable error and nothing stored, when more than 15% of the chunk's slots are edited (a sign the model rewrote the text). Overlapping chunks: an edit found twice with the same range and tokens counts once; conflicting edits are resolved by confidence.

### 4.5 Timing rule for edits (merge and split)

An edit replaces `n = last - first + 1` slots by `k = len(tokens)` tokens. Let `t(s)` be the start of slot `s`, and `end` the start of slot `last + 1` (or the clip end when it is the last slot).

1. Token `m` (0-based) is **anchored** to slot `s(m) = first + floor(m * n / k)`.
2. A token anchored alone to a slot starts at `t(s(m))`.
3. Several tokens anchored to the same slot (a split, `k > n`) share that slot's duration `d`. Their weight is their number of characters; token starts are `t(s) + d * (characters before it / total characters)`.
4. A slot that no token is anchored to (a merge, `k < n`) simply disappears: its time is absorbed by the previous token, which lasts until the next token's start.
5. The confidence `p` of a token is the `p` of its anchor slot.

Worked example, from the sample. Raw slots: `1089 la` (393.43), `1090 massa` (393.89), `1091 bactamia.` (394.07), next slot `1092 Meu` (395.71). Edit: `first=1089, last=1091, tokens=["lamá", "sabactâni?"]`, so `n=3, k=2`. Token 0 anchors to slot 1089 (`floor(0)=0`), token 1 to slot 1090 (`floor(1.5)=1`). Result: `lamá` from 393.43, `sabactâni?` from 393.89 until 395.71. Slot 1091 has no token: its time is absorbed. No word is shown earlier or later than before.

Split example: one slot `quandoquer` (t=10.0, next slot at 10.5), edit tokens `["quando", "quer"]`: `n=1, k=2`, both anchor to the slot, weights 6 and 4, so `quando` starts at 10.0 and `quer` at 10.3.

### 4.6 Storage

- `jobs/<job>/analyze/corrections.json`: `{version, model, prompt_hash, glossary_digest, chunks: [{key, first_word, last_word}], edits: [...]}`. Written atomically. Not versioned in Git (only `review.json` is).
- Per-chunk cache in `analyze/cache/wordfix/<key>.json`, same mechanism as scan/detail/reviews. Key = hash of (chunk lines, prompt hash, model, glossary digest, caption-notes digest, class-sheet digest, topic line, `jobs.LLM_CACHE_VERSION`). The class sheet has its own cache entry `analyze/cache/class_sheet/<key>.json` and file `analyze/class_sheet.json`. A usage limit stops the stage; the rerun reuses every finished chunk.
- `words.json` is never modified.

## 5. Effective words and precedence

New pure module `src/shorts/wordfix.py`:

```
effective_words(raw: list[Word], auto_edits: list[Edit], manual: dict[str, str]) -> list[Word]
```

Order of application:

1. Copy the raw words.
2. Apply the manual fixes to their raw slots (text replaced; `""` marks the slot dropped).
3. **Precedence:** an automatic edit whose range contains any slot touched by a manual fix is ignored entirely. The owner's word wins, and the raw words of that range (with the manual fixes) are used.
4. Apply the remaining automatic edits with the timing rule of 4.5.
5. Remove dropped slots. The time of a dropped slot is absorbed by the previous kept word. A dropped slot at the very start of a clip just starts the clip at the next kept word.

`stages.apply_word_fixes` is replaced by a call to this function. Everything downstream (`clip.produce`, silence detection, `captions.build_screens`, `render_ass`) receives a plain `list[Word]` and does not change.

Indices used by `apply_edit` / `word_fixes` stay **raw indices**. This keeps existing `review.json` files valid.

## 6. What the model may and may not change (prompt rules)

May fix: foreign-language words and quotations (Hebrew, Greek, Aramaic, Latin), biblical and church names, scripture references, obvious mishearings supported by the surrounding sentences, words wrongly split or joined, missing accents on proper names, sentence-final punctuation that is clearly wrong.

Must not: paraphrase, reorder, add or remove content, correct grammar or register, "improve" style, touch a word it is not sure about, or change a number word to digits or the reverse. When unsure it returns no edit. Low-confidence input words (`p < 0.5`) are hints, not permission.

The prompt instructions are written in English; the tokens and reasons are in the channel language.

## 7. Review page

- `review/state.load_state` returns, per raw slot, the display text and a flag: `raw`, `auto` (part of an accepted automatic edit) or `fixed` (manual), plus the raw range of the automatic edit the slot belongs to. Dropped slots come with empty display text and are not rendered.
- `app.js` keeps its raw-index grid. Automatic corrections get their own style (`.auto`), distinct from `.fixed`; hovering shows the original transcript text of the range and the model's reason.
- Alt+click on a corrected word replaces the whole range: the first slot gets the typed text, the other slots of the range get `""`. On a plain word it behaves as today.
- `state.apply_edit` accepts `""` as a word-fix value (drop the slot) but the UI never sends `""` for a single plain slot, so an empty prompt still means "cancel".
- A small badge on each card counts the automatic corrections inside its segments ("3 automatic caption fixes").
- **Shortcut labels for both platforms.** The page currently names only `alt+click` (Windows wording) in its hover text and hint line (`app.js:209`, `app.js:255`); on a Mac the key is Option (⌥). Every shortcut cue on the page shows both, in one small helper so the wording lives in one place: `click`, `Shift+click`, `Alt/Option (⌥)+click`. The helper detects the platform (`navigator.platform` / `userAgentData`) and shows the local key first, the other in parentheses (on a Mac: "Option (⌥)+click (Alt on Windows)"). No cue may name a key that does not exist on the owner's keyboard; Control-click on a Mac is a right-click and is never used.

## 8. Stage keys and caching of renders

The render and track stage keys already include the manual `word_fixes`. Add the digest of the automatic edits that intersect the clip's segments (extended by 2 s), so a changed correction re-renders exactly the clips it touches and no others. `jobs.RENDER_VERSION` is bumped when this ships.

## 9. Configuration and CLI

- `config.toml`: new `[backends.caption_fix]`, default `backend = "claude-cli"`, `model = "claude-sonnet-5"` (the plan-2 default for the review tier), and `[backends.class_sheet]`, default `claude-cli` with `claude-haiku-4-5`. `config.load_config` and `get_backend` accept the two new pass names.
- `profiles/catholic-br/captions.md`: the starter channel caption notes (section 4.2), English instructions with Portuguese spellings. Loaded by a new `load_caption_notes(channel, repo_root)` next to `load_profile`; a missing file is allowed (empty notes).
- `shorts ingest ... [--topic TEXT]`: optional one-line topic, stored in `job.json`.
- `shorts analyze <job>`: runs the pass last; its summary line gains `N caption fixes (M dropped)`.
- `shorts fixwords <job> [--all] [--force]`: reruns only this stage. `--force` ignores the chunk cache. It never touches `candidates.json`, and it is allowed when `review.json` already holds decisions (it does not change the candidate list).
- Errors: a usage limit prints the same readable message as `analyze` and the rerun resumes from cache. An unexpected reply shape is dropped chunk by chunk with `fixword_dropped` events. The pass never blocks the analysis: if it fails, `analyze` still writes `candidates.json`, prints a warning, and the review page shows raw words.

## 10. Cost and time (estimates from the code, to be measured)

The 10-minute sample has 1,587 words, so 4 chunks and 4 calls on `claude-sonnet-5`. A 100-minute class is about 16,000 words, about 32 chunks in `--all` mode, about a third of that in the default scope. The class sheet adds 1 to 3 cheap `claude-haiku-4-5` calls (whole transcript in a few large chunks). Output is small (only edits and a short sheet). `log.jsonl` records tokens per call, as for the other passes; the first live run replaces these estimates.

## 11. Testing

- `tests/test_wordfix.py` (pure): the two worked examples of 4.5 with exact expected times; merge with `k < n` for several `n`, `k`; split; manual fix precedence over an overlapping automatic edit; `""` drops a slot and absorbs its time; dropped slot at clip start; no edit changes any word's time except through the rule; the effective list stays sorted by time.
- `tests/test_wordfix_pass.py`: scripted LLM stub (same pattern as `test_analyze_run`): validation drops each bad edit kind with its logged reason; 15% guard aborts a chunk; overlap between chunks dedupes; cache reuse after a usage limit (rerun makes only the missing calls); empty answer is fine; scope selection picks only chunks near candidates and `--all` picks all.
- Integration: `run_analyze` with the stub writes `corrections.json`; `load_state` marks `auto`; `run_clip_stage` renders captions from the corrected words; a manual fix on a corrected range wins; a failing pass leaves `candidates.json` intact.
- `tests/test_class_sheet.py`: scripted stub; the sheet is cached, its digest changes the fix-chunk cache key; `--topic` overrides the ingest topic; a missing `captions.md` gives empty notes; the request text of a fix chunk contains channel notes, topic, sheet and neighbor context lines (assert on the recorded request).
- Extend the static page test for the new class names, the range replace call and the shortcut helper (both `Option (⌥)` and `Alt` wording present, no `Control-click`); `node --check` on `app.js`.
- Live acceptance (runbook step, owner present): rerun on `260927-amostra-10min`; expect the Aramaic phrase corrected, the `Eloi` accents, and no edits in the clip words that were already right.

## 12. Open questions

None blocking. To decide during implementation review: whether the badge should also list the edits on hover, and whether `--all` should become the default once real costs are known.
