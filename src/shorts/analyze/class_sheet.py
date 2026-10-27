"""Class sheet: what the whole class is about, its references, terms and spellings, so that every
caption-fix chunk knows the context of the class (caption spec 4.2, video layer)."""
from __future__ import annotations

import hashlib
import json

from shorts import jobs
from shorts.analyze import schemas
from shorts.analyze.prompts import load_prompt
from shorts.analyze.textutil import text_of
from shorts.analyze.windows import build_chunks
from shorts.llm.base import LLMError

SHEET_CHUNK = 6000   # words per call: a 100-minute class (~16,000 words) is 3 calls
LIMITS = {"references": 40, "terms": 80, "variable_spellings": 40}
EMPTY_SHEET = {"topic": "", "references": [], "terms": [], "variable_spellings": []}


def _trim(sheet: dict) -> dict:
    return {"topic": str(sheet.get("topic", "")),
            **{k: list(sheet.get(k, []))[:n] for k, n in LIMITS.items()}}


def sheet_digest(sheet: dict) -> str:
    return hashlib.sha256(jobs.canonical(sheet).encode("utf-8")).hexdigest()


def sheet_block(sheet: dict) -> str:
    """The sheet as request text (the caption-fix request embeds it too)."""
    refs = "; ".join(sheet.get("references", [])) or "(none)"
    terms = "; ".join(f"{t['term']} ({t['language']})" for t in sheet.get("terms", [])) or "(none)"
    spell = "; ".join(f"{s['heard']} -> {s['spelling']}"
                      for s in sheet.get("variable_spellings", [])) or "(none)"
    return (f"Class topic: {sheet.get('topic') or '(unknown)'}\n"
            f"Scripture references: {refs}\n"
            f"Foreign terms and names: {terms}\n"
            f"Spellings that vary: {spell}\n")


def _user(channel_block: str, topic: str, sheet: dict, part: str, n: int, of: int) -> str:
    return (f"{channel_block}\n"
            f"# This video\nTopic from the owner: {topic or '(not given)'}\n\n"
            f"# Sheet so far\n{json.dumps(sheet, ensure_ascii=False)}\n\n"
            f"# Transcript part {n} of {of}\n{part}\n")


def run_class_sheet(words, sents, channel_block: str, topic: str, backend, cache=None, store=None,
                    log=None) -> dict:
    system, prompt_hash = load_prompt("class_sheet")
    sheet = _trim(EMPTY_SHEET)
    parts = build_chunks(sents, SHEET_CHUNK, 0)
    for n, part in enumerate(parts, 1):
        user = _user(channel_block, topic, sheet, text_of(words, part.first, part.last), n, len(parts))
        key = jobs.stage_key(jobs.LLM_CACHE_VERSION, stage="class_sheet", user=user,
                             prompt=prompt_hash, model=backend.model)
        data = cache(key) if cache else None
        if data is None:
            try:
                data = backend.complete(system, user, schemas.CLASS_SHEET)
            except LLMError as e:
                if e.kind != "schema":
                    raise               # usage limit / fatal: stop; the rerun resumes from cache
                if log:
                    log({"kind": "class_sheet_failed", "part": n, "error": str(e)[:300]})
                continue                # keep the sheet so far; nothing cached for this part
            if store:
                store(key, data)
        sheet = _trim(data)
    return sheet
