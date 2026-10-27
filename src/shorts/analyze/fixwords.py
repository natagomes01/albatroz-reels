"""Caption-fix pass (caption spec 4): chunk requests, scope, validation and corrections.json.

The pass reads the RAW words, like scan, detail and the reviews, and never modifies words.json.
The corrected words exist only as wordfix.effective_words(...), for the review page, captions and
renders.
"""
from __future__ import annotations

import math
from pathlib import Path

from shorts import jobs
from shorts.analyze import schemas
from shorts.analyze.class_sheet import run_class_sheet, sheet_block, sheet_digest
from shorts.analyze.llmcache import cache_fns
from shorts.analyze.profile import caption_channel_block, load_caption_notes, text_digest
from shorts.analyze.prompts import load_prompt
from shorts.analyze.textutil import text_of, word_end
from shorts.analyze.windows import Chunk, build_chunks
from shorts.ingest import clean_topic
from shorts.llm.base import LLMError, get_backend
from shorts.llm.context import llm_context
from shorts.review.state import clean_word
from shorts.wordfix import CORRECTIONS_VERSION, Edit
from shorts.words import Sentence, Word, load_words, sentences

SCOPE_PAD = 60.0      # default scope: candidate segments +/- 60 s (the detail pass context)
CONTEXT_WORDS = 60    # at most this many read-only words on each side of a chunk


def chunk_lines(words: list[Word], chunk: Chunk) -> str:
    return "\n".join(f"{i}|{words[i].w}|{words[i].p:.2f}" for i in range(chunk.first, chunk.last + 1))


def _sentence_at(sents: list[Sentence], i: int) -> Sentence | None:
    return next((s for s in sents if s.first <= i <= s.last), None)


def neighbor_context(words: list[Word], sents: list[Sentence], chunk: Chunk) -> tuple[str, str]:
    """The sentence just before and just after the chunk (read-only), capped at 60 words."""
    before = after = ""
    if chunk.first > 0:
        s = _sentence_at(sents, chunk.first - 1)
        a = max(s.first if s else 0, chunk.first - CONTEXT_WORDS)
        before = text_of(words, a, chunk.first - 1)
    if chunk.last + 1 < len(words):
        s = _sentence_at(sents, chunk.last + 1)
        b = min(s.last if s else len(words) - 1, chunk.last + CONTEXT_WORDS)
        after = text_of(words, chunk.last + 1, b)
    return before, after


def build_request(words, sents, chunk: Chunk, channel_block: str, topic: str, sheet_text: str) -> str:
    before, after = neighbor_context(words, sents, chunk)
    return (f"{channel_block}\n"
            f"# This video\nTopic from the owner: {topic or '(not given)'}\n{sheet_text}\n"
            f"# Context before (read-only, never edit)\n{before or '(start of the class)'}\n\n"
            f"# Chunk: index|word|confidence. Edit only indices {chunk.first} to {chunk.last}.\n"
            f"{chunk_lines(words, chunk)}\n\n"
            f"# Context after (read-only, never edit)\n{after or '(end of the class)'}\n")


def chunk_span(words: list[Word], chunk: Chunk) -> tuple[float, float]:
    return words[chunk.first].t, word_end(words, chunk.last)


def select_chunks(chunks: list[Chunk], words: list[Word], spans: list[tuple[float, float]],
                  all_chunks: bool = False, pad: float = SCOPE_PAD) -> list[Chunk]:
    if all_chunks:
        return list(chunks)
    out = []
    for ch in chunks:
        a, b = chunk_span(words, ch)
        if any(a < end + pad and b > start - pad for start, end in spans):
            out.append(ch)
    return out


def chunk_key(lines: str, context: str, prompt_hash: str, model: str, glossary_digest: str,
              notes_digest: str, sheet_digest: str, topic: str) -> str:
    return jobs.stage_key(jobs.LLM_CACHE_VERSION, stage="wordfix", lines=lines, context=context,
                          prompt=prompt_hash, model=model, glossary=glossary_digest,
                          notes=notes_digest, sheet=sheet_digest, topic=topic)


MAX_SLOTS = 12
MAX_TOKENS = 12
MAX_TOKEN_CHARS = 40
MIN_CONFIDENCE = 0.6
MAX_EDITED_SHARE = 0.15


class ChunkRejected(Exception):
    """The model edited too much of one chunk: it rewrote the text instead of fixing words."""


def _is_int(v) -> bool:
    return type(v) is int          # bool is a subclass of int; JSON true is not an index


def _drop(raw, reason: str, chunk: Chunk) -> dict:
    d = raw if isinstance(raw, dict) else {}
    return {"kind": "fixword_dropped", "reason": reason, "chunk": chunk.id,
            "first": d.get("first"), "last": d.get("last"), "tokens": d.get("tokens")}


def check_edit(raw, words: list[Word], chunk: Chunk) -> tuple[Edit | None, str | None]:
    """(edit, None) when the edit is acceptable, else (None, reason) (caption spec 4.4)."""
    if not isinstance(raw, dict):
        return None, "shape"
    first, last = raw.get("first"), raw.get("last")
    if not (_is_int(first) and _is_int(last)) or first > last or first < chunk.first or last > chunk.last:
        return None, "range"
    if last - first + 1 > MAX_SLOTS:
        return None, "too_many_slots"
    toks = raw.get("tokens")
    if not isinstance(toks, list) or not 1 <= len(toks) <= MAX_TOKENS:
        return None, "tokens"
    for tok in toks:
        if (not isinstance(tok, str) or not tok or len(tok) > MAX_TOKEN_CHARS
                or " " in tok or clean_word(tok) != tok):
            return None, "tokens"       # clean_word strips ASS { } \\ and newlines: any change = unsafe
    try:
        conf = float(raw.get("confidence"))
    except (TypeError, ValueError):
        return None, "low_confidence"
    if not math.isfinite(conf) or conf < MIN_CONFIDENCE:
        return None, "low_confidence"
    if toks == [w.w for w in words[first:last + 1]]:
        return None, "no_change"
    return Edit(first, last, tuple(toks), str(raw.get("kind", "mishearing")),
                str(raw.get("reason", ""))[:200], conf), None


def _edited_share(raw_edits: list, chunk: Chunk) -> tuple[int, int]:
    slots: set[int] = set()
    for r in raw_edits:
        if isinstance(r, dict) and _is_int(r.get("first")) and _is_int(r.get("last")):
            slots.update(range(max(r["first"], chunk.first), min(r["last"], chunk.last) + 1))
    return len(slots), chunk.last - chunk.first + 1


def check_chunk(data, words: list[Word], chunk: Chunk) -> tuple[list[Edit], list[dict]]:
    raw_edits = data.get("edits", []) if isinstance(data, dict) else []
    edited, total = _edited_share(raw_edits, chunk)
    if edited / total > MAX_EDITED_SHARE:
        raise ChunkRejected(
            f"the model edited {edited} of {total} words in words {chunk.first}-{chunk.last} "
            f"(more than {MAX_EDITED_SHARE:.0%}), a sign it rewrote the text; nothing from this "
            f"chunk was kept")
    edits, drops = [], []
    for raw in raw_edits:
        edit, reason = check_edit(raw, words, chunk)
        if edit is None:
            drops.append(_drop(raw, reason, chunk))
        else:
            edits.append(edit)
    return edits, drops


def resolve(edits: list[Edit]) -> tuple[list[Edit], list[dict]]:
    """Across overlapping chunks: an identical edit counts once; overlapping edits keep the one
    with the higher confidence (earlier first on a tie)."""
    best: dict[tuple, Edit] = {}
    for e in edits:
        k = (e.first, e.last, e.tokens)
        if k not in best or e.confidence > best[k].confidence:
            best[k] = e
    kept: list[Edit] = []
    drops: list[dict] = []
    for e in sorted(best.values(), key=lambda e: (-e.confidence, e.first, e.last)):
        if any(e.first <= k.last and k.first <= e.last for k in kept):
            drops.append({"kind": "fixword_dropped", "reason": "overlap", "first": e.first,
                          "last": e.last, "tokens": list(e.tokens)})
            continue
        kept.append(e)
    return sorted(kept, key=lambda e: e.first), drops


def write_corrections(job, edits: list[Edit], **meta) -> None:
    jobs.write_json_atomic(job.corrections_json, {
        "version": CORRECTIONS_VERSION, **meta, "words_hash": jobs.file_hash(job.words_json),
        "edits": [e.to_dict() for e in edits]})


CHUNK_WORDS = 500
CHUNK_OVERLAP = 100
PASSES = ("class_sheet", "caption_fix")


def scope_spans(job) -> list[tuple[float, float]]:
    """Candidate segments plus segments edited on the review page, so a moved cut edge is covered."""
    data = jobs.read_json(job.candidates_json)
    if data is None:
        raise FileNotFoundError(
            f"{job.candidates_json} is missing: run `shorts analyze {job.id}` first, or "
            f"`shorts fixwords {job.id} --all` to correct the whole class")
    spans = [s["snapped"] for c in data.get("candidates", []) for s in c.get("segments", [])]
    decisions = (jobs.read_json(job.review_json, {}) or {}).get("decisions", {})
    spans += [seg for d in decisions.values() for seg in (d.get("segments") or [])]
    return [(float(a), float(b)) for a, b in spans]


def run_fixwords(job, app, channel, repo_root: Path, backends: dict | None = None,
                 all_chunks: bool = False, force: bool = False, topic: str | None = None) -> dict:
    """Class sheet, then caption-fix chunks near the candidates (all with --all); writes
    analyze/class_sheet.json and analyze/corrections.json. Never touches words.json,
    candidates.json or review.json (caption spec 4, 9)."""
    log = lambda event: jobs.log_event(job, **event)  # noqa: E731
    words = load_words(job.words_json)
    sents = sentences(words)
    meta = jobs.read_json(job.job_json, {}) or {}
    topic = clean_topic(meta.get("topic", "") if topic is None else topic)
    chunks = build_chunks(sents, CHUNK_WORDS, CHUNK_OVERLAP)
    selected = select_chunks(chunks, words, [] if all_chunks else scope_spans(job), all_chunks)
    notes = load_caption_notes(channel, repo_root)
    block = caption_channel_block(channel, notes)
    system, prompt_hash = load_prompt("caption_fix")
    glossary_digest, notes_digest = text_digest(channel.glossary), text_digest(notes)
    summary = {"edits": 0, "dropped": 0, "chunks": len(selected), "total_chunks": len(chunks),
               "rejected": 0}
    if not selected:
        write_corrections(job, [], model=None, prompt_hash=prompt_hash,
                          glossary_digest=glossary_digest, notes_digest=notes_digest,
                          sheet_digest=None, topic=topic, chunks=[], dropped=0, rejected_chunks=[])
        return summary

    backends = dict(backends or {})
    for p in PASSES:
        if p not in backends:
            backends[p] = get_backend(p, app, log=lambda ev, p=p: log({**ev, "pass": p}))
    get, put = cache_fns(job, "class_sheet", backends["class_sheet"])
    with llm_context(pass_name="class_sheet"):
        sheet = run_class_sheet(words, sents, block, topic, backends["class_sheet"],
                                cache=None if force else get, store=put, log=log)
    s_digest = sheet_digest(sheet)
    jobs.write_json_atomic(job.class_sheet_json, {
        "version": 1, "model": backends["class_sheet"].model,
        "prompt_hash": load_prompt("class_sheet")[1], "topic": topic, "digest": s_digest,
        "sheet": sheet})

    fixer = backends["caption_fix"]
    get, put = cache_fns(job, "wordfix", fixer)
    sheet_text = sheet_block(sheet)
    found: list[Edit] = []
    rows: list[dict] = []
    rejected: list[int] = []
    dropped = 0
    for ch in selected:
        before, after = neighbor_context(words, sents, ch)
        key = chunk_key(chunk_lines(words, ch), f"{before}\n{after}", prompt_hash, fixer.model,
                        glossary_digest, notes_digest, s_digest, topic)
        with llm_context(pass_name="caption_fix"):      # names the call and the cache hit alike
            data = None if force else get(key)
        fresh = data is None
        if fresh:
            try:
                with llm_context(pass_name="caption_fix"):
                    data = fixer.complete(system, build_request(words, sents, ch, block, topic,
                                                                sheet_text), schemas.CAPTION_FIX)
            except LLMError as e:
                if e.kind != "schema":
                    raise               # usage limit / fatal: stop; the rerun resumes from cache
                log({"kind": "fixword_dropped", "reason": "reply_shape", "chunk": ch.id,
                     "error": str(e)[:300]})
                dropped += 1
                continue
        try:
            edits, drops = check_chunk(data, words, ch)
        except ChunkRejected as e:
            rejected.append(ch.id)
            log({"kind": "fixword_chunk_rejected", "chunk": ch.id, "error": str(e)})
            continue                    # nothing stored: the rerun asks again
        if fresh:
            put(key, data)
        for d in drops:
            log(d)
        dropped += len(drops)
        found += edits
        rows.append({"key": key, "first_word": ch.first, "last_word": ch.last})
    edits, overlap = resolve(found)
    for d in overlap:
        log(d)
    dropped += len(overlap)
    write_corrections(job, edits, model=fixer.model, prompt_hash=prompt_hash,
                      glossary_digest=glossary_digest, notes_digest=notes_digest,
                      sheet_digest=s_digest, topic=topic, chunks=rows, dropped=dropped,
                      rejected_chunks=rejected)
    summary.update(edits=len(edits), dropped=dropped, rejected=len(rejected))
    return summary
