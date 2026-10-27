"""Pass 2: turn each selected window into candidates (spec 6.3)."""
from __future__ import annotations

from shorts import jobs
from shorts.analyze import schemas
from shorts.analyze.boundaries import SnapError, snap_candidate
from shorts.analyze.candidates import Candidate, total
from shorts.analyze.prompts import load_prompt
from shorts.analyze.textutil import fmt_ts, text_of, words_in
from shorts.timeline import Span

CONTEXT = 60.0


def _span_text(words, span: Span) -> str:
    rng = words_in(words, span)
    return text_of(words, *rng) if rng else ""


def detail_user(target, selected, windows_by_id, words, profile, companions: int = 3) -> str:
    before = _span_text(words, Span(max(target.start - CONTEXT, 0.0), target.start))
    after = _span_text(words, Span(target.end, target.end + CONTEXT))
    lines = [profile.as_prompt_block(),
             f"\n# Target window {target.label()}\n",
             f"Context before ({fmt_ts(max(target.start - CONTEXT, 0))}-{fmt_ts(target.start)}):\n{before}\n",
             f"<<<TARGET {target.id}>>>\n{target.text}\n<<<END TARGET>>>\n",
             f"Context after:\n{after}\n",
             "\n# Other strong windows of this class (one line each)\n"]
    others = [s for s in selected if s.id != target.id]
    for s in others:
        w = windows_by_id[s.id]
        lines.append(f"{w.label()} score {s.score}: {s.reason}")
    lines.append("\n# Companion windows (full text; you may take a segment from these)\n")
    for s in sorted(others, key=lambda s: s.score, reverse=True)[:companions]:
        w = windows_by_id[s.id]
        lines.append(f"Companion window {w.label()}\n{w.text}\n")
    return "\n".join(lines)


def run_detail(selected, windows, words, sents, profile, backend, weights, duration: float,
               cache=None, store=None, log=None) -> list[Candidate]:
    system, prompt_hash = load_prompt("detail")
    by_id = {w.id: w for w in windows}
    out: list[Candidate] = []
    for s in selected:
        target = by_id[s.id]
        user = detail_user(target, selected, by_id, words, profile)
        key = jobs.stage_key(jobs.LLM_CACHE_VERSION, stage="detail", user=user, prompt=prompt_hash,
                             model=backend.model)
        data = cache(key) if cache else None
        if data is None:
            data = backend.complete(system, user, schemas.DETAIL)
            if store:
                store(key, data)
        for n, raw in enumerate(data["candidates"], 1):
            try:
                snapped = snap_candidate(raw, words, sents, by_id, duration)
            except SnapError as e:
                if log:
                    log({"kind": "candidate_dropped", "window": s.id, "reason": str(e),
                         "title": raw.get("title")})
                continue
            c = Candidate(id=f"{s.id}-{n}", window_id=s.id, segments=snapped.segments, title=raw["title"],
                          hook=raw["hook"], scores=raw["scores"],
                          controversy=raw["controversy"]["level"],
                          controversy_why=raw["controversy"]["why"],
                          who_reacts=raw["who_reacts"], emphasis=list(raw["emphasis"]),
                          hook_id=f"{s.id}:{raw['hook_id']}", out_of_order=raw["out_of_order"],
                          too_long=snapped.too_long, too_short=snapped.too_short,
                          llm_hook_id=f"{s.id}:{raw['hook_id']}")
            c.total = total(c, weights)
            out.append(c)
    return out
