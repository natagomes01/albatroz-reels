# Review page: undo, redo and "suggestion or mine": design

Status: approved by the owner on 30/09/2026, with the answers in section 7 (question 3 was replaced by a confirmation step, section 4.4). Plan: `docs/superpowers/plans/2026-09-30-05-review-undo-and-choose.md`.
Origin: owner feedback after the S3 live run on the 10-minute sample (`260927-amostra-10min`), roadmap item "Review page undo and choose".
Parent specs: `docs/superpowers/specs/2026-09-29-caption-context-pass-design.md` (sections 5 and 7), `docs/superpowers/specs/2026-09-28-shorts-pipeline-design.md` (section 11, the review page).

## 1. Goal

Two things the owner could not do on the page:

1. **Undo.** After a misclick (a word fixed or removed, a cut edge moved, a sentence added or removed, a clip approved or rejected) there is no way back. The owner wants Command-Z, Ctrl+Z on Windows, and a visible button.
2. **Choose between the suggestion and the owner's edit.** When the owner fixes a word inside a range the model corrected, the owner's fix silently wins the whole range (caption spec section 5) and the automatic version is hidden. The owner wants to see both and pick which one goes to the final version, and to change their mind later.

Success looks like this: on clip `c6e1125`, the owner removes the word "sa", sees the word leave, presses Command-Z and gets it back, presses Shift+Command-Z and removes it again; on the range `Eloí, Eloí, lamá sabactâni?` the page shows the suggestion and the owner's version side by side and a click on either one changes which one is rendered.

## 2. Non-goals

- Undo across server restarts or across jobs (section 4.1).
- Undo of pipeline results: `candidates.json`, `corrections.json`, renders and the LLM passes are not part of the history.
- Editing the raw `words.json`. It stays untouched.
- A full edit-history viewer. Only undo and redo.
- Changing the automatic correction pass itself.

## 3. Concepts

**Decision entry.** `review.json` -> `decisions[<clip id>]`: `status`, `segments`, `word_fixes`, `title`, `hook`, and (new) `use_auto`. This is everything the owner can change on a clip, so it is the unit of undo.

**Step.** One successful call to `/api/edit` or `/api/decision` is one step. A range replace is already one call with several `word_fixes` keys, so it is one step.

**Suggestion.** An automatic edit from `analyze/corrections.json` (`first`, `last`, `tokens`).

**Mine.** The owner's `word_fixes` inside the same raw range `first..last`.

## 4. Design

### 4.1 Undo and redo

The server keeps, per job and per clip, an undo stack and a redo stack of **whole decision-entry snapshots** (deep copies, taken under the existing `_LOCK` before the write). Each stack holds at most 100 entries.

- Every `apply_edit` and `apply_decision` that changes the entry pushes the previous snapshot on the undo stack and clears the redo stack. A call that changes nothing (same values) pushes nothing.
- `POST /api/undo {id}` pops the undo stack, pushes the current entry on the redo stack, writes the popped snapshot to `review.json` (atomic write, as today) and returns the entry in the same shape as `/api/edit`. `POST /api/redo {id}` does the reverse. An empty stack returns `{"error": "nothing to undo"}` with status 409 and leaves the file alone.
- `load_state` adds, per clip, `undo` and `redo` (integer counts) so the page can enable or disable its buttons after a reload. The replies of `/api/edit`, `/api/decision`, `/api/undo` and `/api/redo` carry the same two counts for that clip, next to the whole decision entry.
- The stacks live in memory. Closing `shorts review` clears them; `review.json` already holds the last state. Reason: the history is a working aid, and a file of snapshots would be one more thing to keep consistent with the versioned `review.json`.
- Snapshots are whole entries, so undo also restores `segments`, which covers moving a cut start or end, adding time and removing time, and adding or removing a sentence.

### 4.2 Keys and buttons

Every cue names both keyboards, as in caption spec section 7, through the same `KEYS` helper in `app.js`.

| Action | Mac | Windows |
|---|---|---|
| Undo | Command (⌘)+Z | Ctrl+Z |
| Redo | Shift+Command (⌘)+Z | Ctrl+Y or Ctrl+Shift+Z |

- The handler is on `document`, ignores the keystroke while a text field, the prompt or the title/hook inputs have focus (so typing keeps the browser's own text undo), and acts on the **clip the owner last touched**. The page highlights that card's Undo button so it is visible which clip is affected.
- Each card gets an Undo and a Redo button (labels `Undo` and `Redo`, tooltip with both key names, disabled when the count is 0). The hint line of the card lists both key pairs.
- After an undo or redo the page replaces the clip's local entry with the returned one and re-renders, exactly as after an edit.

### 4.3 Removed words stay visible

Today a word removed with a blank answer (`word_fixes[i] = ""`) leaves nothing on the page to click. Undo fixes the last step, but not an older one, so a removed slot is shown as a **ghost chip**: the raw word in a faint, struck-through style with a small `⌫` marker, placed where the word was. A click on a ghost chip restores it by erasing the owner's fix for that slot, as if the word had never been touched (owner decision, 30/09/2026): the page sends `{"word_fixes": {"<i>": null}}` and `null` removes the key. This is one step, so it is undoable too. Writing the raw word back instead would leave the slot marked as owner-edited forever, so a later automatic fix over it would be hidden behind a "Mine" that is only the raw word. The ghost never enters the captions, the render, the duration estimate or the preview text.

### 4.4 Suggestion or mine

For every automatic edit whose raw range `first..last` holds at least one owner fix, the page shows a **choice chip** in the caption text:

```
[ Suggestion: Eloí, Eloí, lamá sabactâni? ]  [ Mine: Eloí, Eloí, lamá sa sabactâni? ]
```

The active side has a solid outline; a click on the other side switches. The choice is stored in the decision entry:

```json
"use_auto": [1087]
```

`use_auto` is the list of `first` indices of automatic edits that the owner chose. Semantics:

- Not listed (the default, and what every existing `review.json` means): today's rule. The owner's fix wins, the suggestion is ignored for the whole range.
- Listed: the suggestion applies to the whole range and the owner's `word_fixes` inside it are **kept in the file but ignored**, so switching back to "Mine" restores them exactly.
- An entry in `use_auto` that matches no automatic edit (corrections regenerated, words replaced) is ignored.
- A range with no owner fix shows no chooser: the suggestion simply applies (caption spec section 5, unchanged).
- The choice is one step of the undo history.
- The page sends the choice through `/api/edit` as `{"use_auto": [<first>, ...]}`: the whole list, which replaces the stored one (an empty list removes the key). Each value is a non-negative integer.

**Confirmation before the owner's text replaces a suggestion** (owner answer to question 3). When the owner corrects words inside a range whose suggestion is currently applied (no owner fix there yet, or the owner chose "Suggestion"), the page asks, after the owner has typed the new text and before anything is saved: `Your text "<typed>" will replace the automatic fix "<tokens>". Do you really want to do this? (You can switch back to the suggestion later.)` Cancel saves nothing. OK saves the owner's text and selects "Mine" for that range in the same `/api/edit` call (`word_fixes` plus a `use_auto` list without that range's `first`), so it is one undo step. When "Mine" is already the active side, editing it asks nothing.

Code: `wordfix.effective_words(raw, auto_edits, manual, prefer_auto=frozenset())` and `wordfix.active_edits(n_raw, auto_edits, manual, prefer_auto=frozenset())` gain the optional argument. For an edit whose `first` is in `prefer_auto`, the "touches an owner slot" test is skipped and the manual fixes in `first..last` are dropped from the text list. Default keeps every current call and test valid. `stages._clip_inputs` passes `set(entry.get("use_auto", []))`; `wordfix.edits_digest` and the render key follow from `active_edits`, so switching the choice re-renders only that clip (caption spec section 8).

`load_state` needs no new field for this: owner fixes are per clip, so the page builds the "Mine" text from that clip's `word_fixes` (raw word where a slot has no fix, `""` slots left out), and `use_auto` arrives inside the clip's decision entry.

### 4.5 What the owner sees when a range has both

`slotView` today returns `flag: "fixed"` for any owner-fixed slot and hides the suggestion. It gains a third state for slots inside a chooser: `flag: "choice"`. The chooser replaces the individual word chips of that range, so the owner sees two alternatives, not interleaved words. A plain click on the inactive side switches to it; a click on the active side does nothing. Alt+click (Option (⌥)+click on a Mac) on either side opens the existing range prompt, prefilled with that side's text; saving writes the owner's text for the whole range (first slot gets the text, the others `""`) and selects "Mine", with the confirmation of section 4.4 when "Suggestion" was the active side. Cut edges cannot be set by clicking a chooser; the words around it still set them.

## 5. Stage keys and caching of renders

Nothing new beyond section 4.4: the effective words inside each clip's segments +/- 2 s already feed the render key (`stages._keys`), and `use_auto` changes those words. Undo restores an earlier entry, so the key returns to an earlier value and the earlier render is reused if it is still on disk.

## 6. Testing

- `tests/test_review_state.py`: a step pushes one snapshot; a no-op pushes none; undo then redo round-trips `status`, `segments`, `word_fixes`, `title`, `hook` and `use_auto`; a new edit clears redo; the 100-step cap drops the oldest; empty stacks give the 409 error and do not touch the file; two clips keep separate stacks.
- `tests/test_review_server.py`: `/api/undo` and `/api/redo` routes, wrong clip id, host check as for the other POSTs.
- `tests/test_wordfix.py`: `prefer_auto` makes the suggestion win over an owner fix in the range, leaves other owner fixes alone, ignores an index that starts no edit, and `effective_words` with the default argument is unchanged (the existing tests stay as they are).
- `tests/test_stages.py`: switching `use_auto` changes only that clip's render key.
- `tests/test_review_static.py`: needles for the key handler (both key pairs, the focus guard), the buttons, the ghost chip and the chooser; `node --check`.
- Live: the sample's `c6e1125` (remove "sa", undo, redo, choose Suggestion, choose Mine, reload the page and see the same state).

## 7. Owner answers (30/09/2026)

1. **Rapid nudges.** Each click is its own undo step; no merging.
2. **Undo after the page or the server restarts.** Not kept. The stacks live only in memory (section 4.1).
3. **Default when both exist.** Replaced by a confirmation: before the owner's text replaces a suggestion that is applied, the page asks "Do you really want to do this?"; on OK the owner's text wins ("Mine"), on Cancel nothing is saved (section 4.4). Existing decisions keep "Mine" as today.
4. **Which clip a key press acts on.** The last clip touched (section 4.2).
5. **Redo keys.** Shift+Command (⌘)+Z on a Mac, Ctrl+Y and Ctrl+Shift+Z on Windows.
