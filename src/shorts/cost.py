"""`shorts cost`: what the LLM calls of a job, a run or every job cost (S4 spec 3, "Report").

Reads only `log.jsonl`, `job.json`, `candidates.json` and `review.json`. Costs are API list-price
estimates (`claude -p` reports `cost_basis: "list"`), never a bill. Logs written before S4 are
reported with the fields they have, plus a note; nothing here raises on a missing field.
"""
from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

from shorts import jobs, runlog

UNKNOWN_PASS = "(unknown)"
PASS_ORDER = ("scan", "detail", "review", "review_blind", "review_faithful", "class_sheet",
              "caption_fix", "broll", UNKNOWN_PASS)
LOCAL_COMMANDS = ("track", "captions", "render")
TOKEN_COLUMNS = (("input_tokens", "input_tokens"),
                 ("cache_write_tokens", "cache_creation_input_tokens"),
                 ("cache_read_tokens", "cache_read_input_tokens"),
                 ("output_tokens", "output_tokens"),
                 ("thinking_tokens", "thinking_tokens"))


def _pass_by_model(job) -> dict[str, str]:
    """For `llm` events without a pass (logs from before S4): the pass that used the model, from
    candidates.json provenance, when exactly one pass used it."""
    data = jobs.read_json(job.candidates_json, {}) or {}
    by_model: dict[str, list[str]] = {}
    for pass_name, cfg in (data.get("llm") or {}).items():
        by_model.setdefault((cfg or {}).get("model"), []).append(pass_name)
    return {m: ps[0] for m, ps in by_model.items() if m and len(ps) == 1}


def _new_row(pass_name: str, model: str) -> dict:
    row = {"pass": pass_name, "model": model, "calls": 0, "retries": 0, "failed": 0,
           "no_cost": 0, "cost_usd": 0.0, "share": 0.0, "wall_s": None}
    row.update({name: 0 for name, _ in TOKEN_COLUMNS})
    return row


def _order(row: dict) -> tuple:
    p = row["pass"]
    return (PASS_ORDER.index(p) if p in PASS_ORDER else len(PASS_ORDER) - 1, p, row["model"])


def _runs(events: list[dict]) -> dict[str, dict]:
    runs: dict[str, dict] = {}
    for e in events:
        if e.get("kind") == "run_start" and e.get("run"):
            runs[e["run"]] = {"run": e["run"], "command": e.get("command"), "ts": e.get("ts"),
                              "exit_code": None, "wall_s": None}
    for e in events:
        if e.get("kind") == "run_end" and e.get("run") in runs:
            runs[e["run"]].update(exit_code=e.get("exit_code"), wall_s=e.get("wall_s"))
    for run_id, r in runs.items():
        t = runlog.run_totals(events, run_id)
        r.update(calls=t["calls"], cost_usd=round(t["cost_usd"], 6),
                 saved_usd=round(t["saved_usd"], 6))
    return runs


def _per(total: float, n) -> float | None:
    return round(total / n, 6) if n else None


def job_report(job, run: str | None = None) -> dict:
    """Everything `shorts cost <job> [--run ID]` shows, as plain data (also the --json output)."""
    events, bad = runlog.read_log(job.log_path)
    runs = _runs(events)
    if run is not None and run not in runs:
        raise LookupError(f"no run {run} in {job.log_path} (run ids are listed by "
                          f"`shorts cost {job.id}`)")

    def picked(e):
        return run is None or e.get("run") == run

    calls = [e for e in events if e.get("kind") == "llm" and picked(e)]
    hits = [e for e in events if e.get("kind") == "llm_cache_hit" and picked(e)]
    guess = _pass_by_model(job)
    rows: dict[tuple, dict] = {}
    inferred = 0
    for e in calls:
        pass_name = e.get("pass")
        if not pass_name:
            pass_name = guess.get(e.get("model"))
            if pass_name:
                inferred += 1
            else:
                pass_name = UNKNOWN_PASS
        model = e.get("model") or "?"
        r = rows.setdefault((pass_name, model), _new_row(pass_name, model))
        r["calls"] += 1
        r["retries"] += 1 if (e.get("attempt") or 1) > 1 else 0
        r["failed"] += 0 if e.get("ok", True) else 1
        for name, field in TOKEN_COLUMNS:
            r[name] += e.get(field) or 0
        if e.get("cost_usd") is None:
            r["no_cost"] += 1
        r["cost_usd"] += e.get("cost_usd") or 0.0
        ms = e.get("wall_ms", e.get("duration_ms"))
        if ms is not None:                       # logs from before S4 have no time per call
            r["wall_s"] = (r["wall_s"] or 0.0) + ms / 1000
    ordered = sorted(rows.values(), key=_order)
    total_cost = sum(r["cost_usd"] for r in ordered)
    for r in ordered:
        r["cost_usd"] = round(r["cost_usd"], 6)
        r["wall_s"] = None if r["wall_s"] is None else round(r["wall_s"], 3)
        r["share"] = round(r["cost_usd"] / total_cost, 4) if total_cost else 0.0
    total = {k: sum(r[k] for r in ordered)
             for k in ("calls", "retries", "failed", "no_cost", *(n for n, _ in TOKEN_COLUMNS))}
    total.update(cost_usd=round(total_cost, 6),
                 wall_s=(round(sum(r["wall_s"] for r in ordered if r["wall_s"] is not None), 3)
                         if any(r["wall_s"] is not None for r in ordered) else None),
                 cache_hits=len(hits),
                 saved_usd=round(sum(e.get("saved_usd") or 0.0 for e in hits), 6),
                 cost_basis=sorted({e["cost_basis"] for e in calls if e.get("cost_basis")}))

    meta = jobs.read_json(job.job_json, {}) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{job.job_json.name} is not a JSON object: {job.job_json}")
    duration = meta.get("duration")
    minutes = _minutes(duration)
    cands = jobs.read_json(job.candidates_json)
    n_cands = len(cands.get("candidates") or []) if isinstance(cands, dict) else None
    review = jobs.read_json(job.review_json, {}) or {}
    decisions = (review.get("decisions") if isinstance(review, dict) else None) or {}
    n_approved = sum(1 for d in decisions.values() if (d or {}).get("status") == "approved")

    local = []
    transcribe = [e for e in events if e.get("kind") == "transcreve"] if run is None else []
    timed = [e["wall_s"] for e in transcribe if e.get("wall_s") is not None]
    if transcribe:
        local.append({"step": "transcribe", "runs": len(transcribe),
                      "wall_s": round(sum(timed), 3) if timed else None})
    for command in LOCAL_COMMANDS:
        done = [r for r in runs.values() if r["command"] == command and (run is None or
                                                                        r["run"] == run)]
        if done:
            local.append({"step": command, "runs": len(done),
                          "wall_s": round(sum(r["wall_s"] or 0.0 for r in done), 3)})

    limits = [{"ts": e.get("ts"), "pass": e.get("pass"), "model": e.get("model"),
               "error": str(e.get("error") or "")[:120]}
              for e in calls if e.get("error_kind") == "limit"]

    notes = []
    old = sum(1 for e in calls if "attempt" not in e)
    if old:
        notes.append(f"{old} of {len(calls)} calls were logged before S4: their token columns "
                     f"miss cache reads and writes (cost_usd is complete) and they have no run "
                     f"id.")
    if inferred:
        notes.append(f"pass inferred from the model (candidates.json) for {inferred} calls.")
    if total["no_cost"]:
        notes.append(f"{total['no_cost']} calls have no cost (failed before reporting one, or "
                     f"no pricing.toml price for the model).")
    if bad:
        notes.append(f"{bad} unreadable lines in log.jsonl were skipped.")
    if transcribe and len(timed) < len(transcribe):
        notes.append("transcription time was not logged before S4.")
    if not minutes:
        notes.append("job.json has no duration: no cost per class minute.")

    return {"job": job.id, "run": run, "minutes": minutes,
            "rows": ordered, "total": total,
            "per_minute_usd": _per(total_cost, minutes),
            "candidates": n_cands, "per_candidate_usd": _per(total_cost, n_cands),
            "approved": n_approved, "per_approved_usd": _per(total_cost, n_approved),
            "runs": [r for r in sorted(runs.values(), key=lambda r: r["ts"] or 0)
                     if run is None or r["run"] == run],
            "local": local, "limits": limits, "notes": notes}


# ---- projection, --all and text output (80 columns) -------------------------------------------

def projection(rep: dict, minutes: float, scan_ceiling: int) -> dict | None:
    """Linear projection from the cost per class minute; None when there is none."""
    per_minute = rep.get("per_minute_usd")
    if not per_minute:
        return None
    return {"minutes": minutes, "per_minute_usd": per_minute,
            "cost_usd": round(per_minute * minutes, 4), "scan_ceiling": scan_ceiling,
            "warning": f"detail is capped at {scan_ceiling} windows (scan_ceiling), so linear "
                       f"scaling overstates long classes"}


def _minutes(duration) -> float | None:
    """Class minutes from a job.json duration in seconds; None when absent or not a number."""
    try:
        return round(float(duration) / 60, 3) if duration else None
    except (TypeError, ValueError):
        return None


def all_jobs(jobs_dir) -> list[dict]:
    """One row per job folder (folders starting with `_`, such as `_manual`, are skipped)."""
    root = Path(jobs_dir)
    if not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if not (d / "job.json").exists():
            continue
        try:
            rep = job_report(jobs.Job(d))
        except (ValueError, AttributeError, TypeError, OSError) as e:
            out.append({"job": d.name, "minutes": None, "calls": 0, "cost_usd": 0,
                        "per_minute_usd": None, "saved_usd": 0, "candidates": None,
                        "approved": 0, "models": {}, "notes": 1,
                        "error": f"unreadable: {e}"})
            continue
        out.append({"job": rep["job"], "minutes": rep["minutes"],
                    "calls": rep["total"]["calls"], "cost_usd": rep["total"]["cost_usd"],
                    "per_minute_usd": rep["per_minute_usd"],
                    "saved_usd": rep["total"]["saved_usd"],
                    "candidates": rep["candidates"], "approved": rep["approved"],
                    "models": {r["pass"]: r["model"] for r in rep["rows"]},
                    "notes": len(rep["notes"])})
    return out


def estimate_cost(jobs_dir, minutes: float | None, exclude: str | None = None) -> float | None:
    """What `minutes` of class would cost at the cost per class minute of earlier jobs (total
    cost over total minutes of every job with a duration and a cost); None when there is none."""
    rows = [r for r in all_jobs(jobs_dir)
            if r["job"] != exclude and r["minutes"] and r["cost_usd"] > 0]
    if not rows or not minutes:
        return None
    per_minute = sum(r["cost_usd"] for r in rows) / sum(r["minutes"] for r in rows)
    return round(per_minute * minutes, 4)


def _fit(text, width: int) -> str:
    text = str(text)
    return text if len(text) <= width else text[:width - 1] + "~"


def _table(columns: list[tuple[str, int, str]], rows: list[list]) -> list[str]:
    """columns: (header, width, "<" or ">"). Cells longer than the width are cut with "~"."""
    def line(cells):
        return " ".join(f"{_fit(c, w):{a}{w}}" for c, (_, w, a) in zip(cells, columns)).rstrip()
    return [line([h for h, _, _ in columns])] + [line(r) for r in rows]


def _usd(value, places: int = 4) -> str:
    return "-" if value is None else f"${value:.{places}f}"


def _secs(value) -> str:
    return "-" if value is None else f"{round(value)}s"


COST_COLUMNS = [("pass", 15, "<"), ("model", 17, "<"), ("calls", 5, ">"), ("retries", 7, ">"),
                ("failed", 6, ">"), ("cost", 9, ">"), ("share", 5, ">"), ("wall", 7, ">")]
TOKEN_TABLE = [("pass", 15, "<"), ("model", 17, "<"), ("input", 10, ">"),
               ("cache write", 11, ">"), ("cache read", 11, ">"), ("output", 10, ">")]
RUN_COLUMNS = [("run", 18, "<"), ("command", 9, "<"), ("exit", 4, ">"), ("wall", 8, ">"),
               ("calls", 5, ">"), ("cost", 9, ">"), ("saved", 9, ">")]
ALL_COLUMNS = [("job", 20, "<"), ("min", 5, ">"), ("calls", 5, ">"), ("cost", 8, ">"),
               ("per min", 7, ">"), ("models", 29, "<")]


def format_report(rep: dict, proj: dict | None = None, project_minutes: float | None = None) -> str:
    t = rep["total"]
    scope = f"run {rep['run']}" if rep["run"] else "all runs"
    length = f"{rep['minutes']:.1f} class minutes" if rep["minutes"] else "class length unknown"
    basis = f" (cost basis: {', '.join(t['cost_basis'])})" if t["cost_basis"] else ""
    out = [f"Job {rep['job']} ({scope}), {length}",
           f"API-equivalent cost at list price{basis}: an estimate, not a bill.", ""]
    if rep["rows"]:
        out += _table(COST_COLUMNS, [
            [r["pass"], r["model"], r["calls"], r["retries"], r["failed"], _usd(r["cost_usd"]),
             f"{round(r['share'] * 100)}%", _secs(r["wall_s"])] for r in rep["rows"]]
            + [["total", "", t["calls"], t["retries"], t["failed"], _usd(t["cost_usd"]),
                "100%" if t["cost_usd"] else "0%", _secs(t["wall_s"])]])
        out.append("")
        out += _table(TOKEN_TABLE, [
            [r["pass"], r["model"], f"{r['input_tokens']:,}", f"{r['cache_write_tokens']:,}",
             f"{r['cache_read_tokens']:,}", f"{r['output_tokens']:,}"] for r in rep["rows"]]
            + [["total", "", f"{t['input_tokens']:,}", f"{t['cache_write_tokens']:,}",
                f"{t['cache_read_tokens']:,}", f"{t['output_tokens']:,}"]])
    else:
        out.append("No LLM calls logged.")
    out += ["",
            f"Total: {_usd(t['cost_usd'])} for {t['calls']} calls ({t['retries']} retries, "
            f"{t['failed']} failed)",
            f"Cache: {t['cache_hits']} hits saved {_usd(t['saved_usd'])} (not counted as spent)",
            f"Per class minute:  {_usd(rep['per_minute_usd'])}",
            f"Per candidate:     {_usd(rep['per_candidate_usd'])} "
            f"({rep['candidates'] if rep['candidates'] is not None else 0} candidates)",
            f"Per approved clip: {_usd(rep['per_approved_usd'])} ({rep['approved']} approved)"]
    if rep["local"]:
        out += ["", "Local steps (no API cost):"]
        out += [f"  {s['step']:<12} {s['runs']:>3} run(s) {_secs(s['wall_s']):>8}  $0.00 (local)"
                for s in rep["local"]]
    n_limits = len(rep["limits"])
    out += ["", f"Plan use: {t['calls']} calls, {n_limits} usage-limit event"
                f"{'' if n_limits == 1 else 's'}"]
    for lim in rep["limits"]:
        when = datetime.fromtimestamp(lim["ts"]).strftime("%Y-%m-%d %H:%M:%S") if lim["ts"] else "?"
        out.append(_fit(f"  {when} {lim['pass'] or '?'} {lim['model']}: {lim['error']}", 80))
    if rep["runs"]:
        out += ["", "Runs:"]
        out += _table(RUN_COLUMNS, [
            [r["run"], r["command"], "-" if r["exit_code"] is None else r["exit_code"],
             _secs(r["wall_s"]), r["calls"], _usd(r["cost_usd"]), _usd(r["saved_usd"])]
            for r in rep["runs"]])
    if proj:
        out += ["", f"Projection for {proj['minutes']:g} minutes: {_usd(proj['cost_usd'], 2)} "
                    f"(linear from {_usd(proj['per_minute_usd'])} per class minute).",
                textwrap.fill(f"Note: {proj['warning']}.", 80)]
    elif project_minutes is not None:
        out += ["", "Projection: no cost per class minute for this job (no duration or no LLM "
                    "cost)."]
    if rep["notes"]:
        out += ["", "Notes:"]
        out += [textwrap.fill(n, 80, initial_indent="  - ", subsequent_indent="    ")
                for n in rep["notes"]]
    return "\n".join(out)


def format_all(rows: list[dict]) -> str:
    if not rows:
        return "No jobs with a job.json in the jobs folder."
    def models(r):
        return ",".join(dict.fromkeys(m.removeprefix("claude-") for m in r["models"].values()))
    out = _table(ALL_COLUMNS, [
        [r["job"], "-" if r["minutes"] is None else f"{r['minutes']:.1f}", r["calls"],
         _usd(r["cost_usd"]), _usd(r["per_minute_usd"]), models(r)] for r in rows])
    total = sum(r["cost_usd"] for r in rows)
    out += ["", f"Total: {_usd(total)} over {len(rows)} jobs. API-equivalent list price, not a "
                f"bill."]
    if any(r["notes"] for r in rows):
        out.append("Some jobs have notes (old logs, missing fields): run `shorts cost <job>`.")
    for r in rows:
        if r.get("error"):
            out.append(_fit(f"{r['job']}: {r['error']}".replace("\n", " "), 80))
    return "\n".join(out)
