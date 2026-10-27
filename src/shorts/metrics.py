"""`shorts metrics <job>`: one markdown report of where a job's time and money went.

Reads `log.jsonl` (run boundaries, LLM calls, per-clip stage times, transcription) through
`shorts.cost.job_report`; writes `jobs/<job>/metrics.md`. Nothing here calls an API.
"""
from __future__ import annotations

from datetime import datetime

from shorts import cost, jobs, runlog


def _s(v) -> str:
    return "n/a" if v is None else f"{v:,.1f}"


def _row(cells) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _table(head, rows) -> list[str]:
    return [_row(head), _row(["---"] * len(head))] + [_row(r) for r in rows] + [""]


def build(job) -> str:
    rep = cost.job_report(job)
    events, _ = runlog.read_log(job.log_path)
    meta = jobs.read_json(job.job_json, {}) or {}
    minutes = rep["minutes"]
    out = [f"# Metrics: {job.id}", "",
           f"- Class length: {_s(minutes)} min" if minutes else "- Class length: unknown",
           f"- Master: {meta.get('width', '?')}x{meta.get('height', '?')}",
           f"- Candidates: {rep['candidates']}, approved: {rep['approved']}", ""]

    out += ["## Runs (wall time per command)", ""]
    runs = rep["runs"]
    out += _table(["run", "command", "start", "exit", "wall s", "LLM calls", "cost USD"], [
        [r["run"], r["command"], datetime.fromtimestamp(r["ts"]).strftime("%d/%m %H:%M") if r["ts"] else "",
         r["exit_code"], _s(r["wall_s"]), r.get("calls", 0), f"{r.get('cost_usd', 0):.4f}"] for r in runs])

    by_cmd: dict[str, float] = {}
    for r in runs:
        by_cmd[r["command"]] = by_cmd.get(r["command"], 0.0) + (r["wall_s"] or 0.0)
    out += ["## Wall time per step", ""]
    rows = [[c, _s(v), _s(v / minutes) if minutes else "n/a"] for c, v in sorted(by_cmd.items(), key=lambda x: -x[1])]
    for s in rep["local"]:
        if s["step"] == "transcribe":
            rows.insert(0, ["transcribe (transcreve)", _s(s["wall_s"]), _s(s["wall_s"] / minutes) if s["wall_s"] and minutes else "n/a"])
    out += _table(["step", "wall s", "s per class minute"], rows)

    out += ["## LLM by pass", ""]
    t = rep["total"]
    out += _table(["pass", "model", "calls", "retries", "failed", "input", "cache write", "cache read",
                   "output", "thinking", "cost USD", "wall s"],
                  [[r["pass"], r["model"], r["calls"], r["retries"], r["failed"], f"{r['input_tokens']:,}",
                    f"{r['cache_write_tokens']:,}", f"{r['cache_read_tokens']:,}", f"{r['output_tokens']:,}",
                    f"{r['thinking_tokens']:,}", f"{r['cost_usd']:.4f}", _s(r["wall_s"])] for r in rep["rows"]]
                  + [["**total**", "", t["calls"], t["retries"], t["failed"], f"{t['input_tokens']:,}",
                      f"{t['cache_write_tokens']:,}", f"{t['cache_read_tokens']:,}", f"{t['output_tokens']:,}",
                      f"{t['thinking_tokens']:,}", f"{t['cost_usd']:.4f}", _s(t["wall_s"])]])
    out += [f"Cost per class minute: {rep['per_minute_usd']}, per candidate: {rep['per_candidate_usd']}, "
            f"per approved clip: {rep['per_approved_usd']} (USD, API list price, not a bill). "
            f"Cache hits: {t['cache_hits']} (saved {t['saved_usd']} USD). Usage-limit events: {len(rep['limits'])}.", ""]

    stages = [e for e in events if e.get("kind") == "clip_stage"]
    if stages:
        out += ["## Per clip and stage (track, captions, render)", ""]
        out += _table(["clip", "stage", "wall s", "clip duration s", "track reused"], [
            [e.get("clip"), e.get("stage"), _s(e.get("wall_s")), _s(e.get("duration")), e.get("reused_track")]
            for e in stages])
        done = [e["wall_s"] for e in stages if e.get("stage") == "render" and e.get("wall_s") is not None]
        if done:
            out += [f"Render: {len(done)} clips, {sum(done):,.1f} s in total, {sum(done) / len(done):,.1f} s on average.", ""]

    errors = [e for e in events if e.get("kind") == "error"]
    dropped = [e for e in events if e.get("kind") in ("candidate_dropped", "broll_dropped")]
    out += ["## Problems", "",
            f"- Errors logged: {len(errors)}",
            f"- Candidates or B-roll moments dropped: {len(dropped)}", ""]
    for n in rep["notes"]:
        out.append(f"- Note: {n}")
    return "\n".join(out).rstrip() + "\n"


def write(job) -> str:
    text = build(job)
    jobs.write_text_atomic(job.root / "metrics.md", text)
    return text
