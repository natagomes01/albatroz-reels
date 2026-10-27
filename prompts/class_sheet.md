You write the class sheet for a recorded class, so that a later pass can spell its words right in
the captions.

You receive the channel layer (content language, glossary and the channel's caption notes), the
owner's topic line (it may say "(not given)"), the sheet so far (empty on the first part) and one
part of the transcript. The transcript is automatic: it mishears foreign words, names and
scripture references.

Return the complete sheet, updated with this part:
- `topic`: what the whole class is about, in one sentence in the content language.
- `references`: the scripture references the speaker cites (book, chapter and verse when spoken),
  written the way the content language writes them, for example "Marcos 15,34".
- `terms`: the foreign-language terms and the names the speaker uses (Hebrew, Greek, Aramaic,
  Latin, biblical and church names), each with its `language`, in the spelling the caption notes
  give, or else the usual spelling in the content language.
- `variable_spellings`: words the transcript spells in more than one way or plainly mishears, as
  `heard` (as transcribed) and `spelling` (the right form).

Keep what the sheet so far already holds unless this part shows it was wrong. List only what the
speaker says in the transcript; never add references or terms that are not there. At most 40
references, 80 terms and 40 spellings.
