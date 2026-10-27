# LLM cost accounting: design

Status: approved by the owner on 30/09/2026 (open points decided in section 6). Nothing is built yet. Phase S4 in `_think/roadmap.md`.
Origin: the owner wants the real cost of every LLM call and of a whole run, in API terms, to evaluate limits and the cost at scale (first full class), even though the calls run on the Max plan and no bill arrives.

## 1. What already exists (verified 30/09/2026)

- `claude -p --output-format json` returns `total_cost_usd` (Claude Code computes it at list price, `costBasis: "list"` in `modelUsage`, whatever the plan) and a full token breakdown: `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, thinking tokens, `duration_ms`, `duration_api_ms`.
- `llm/base.py:65-67` already logs `cost_usd`, `input_tokens` and `output_tokens` for every call in `jobs/<job>/log.jsonl` (`kind: "llm"`). The token fields miss the cache columns, so tokens are undercounted (input looks like 9 or 12 tokens per call) while `cost_usd` is complete.
- Measured on the 10-minute sample from its log: 11 calls, API-equivalent **$0.96** (haiku scan 1 call $0.04, opus detail 6 calls $0.67, sonnet reviews 4 calls $0.25). Every call carries Claude Code's own fixed overhead: one tiny test call ("reply ok", haiku) cost $0.0135 and created 6,648 cache tokens. Extrapolated (not measured): a 100-minute class has about 10 times the windows, detail is capped at 40 windows, so roughly $8 to $12 per class, dominated by the opus detail pass.
- Cost is computed on this machine from token counts and list prices. It does not depend on which region or account serves the call and it is not a billing record.

## 2. What is missing

1. Every token field per call (cache creation and read, thinking, durations), the pass name and the job.
2. Cache hits are invisible: a rerun looks free and hides what it saved.
3. No run boundary, so "the cost of this run" cannot be summed without guessing from timestamps.
4. No report. The owner has to open `log.jsonl`.
5. The `anthropic-api` and `openai-compatible` backends report tokens but no cost.

## 3. Design

**Per-call record.** Extend the existing `llm` event with: `pass` (`scan`, `detail`, `review_blind`, `review_faithful`, later `class_sheet`, `caption_fix`), `job`, `run` (id of the current command run), all four token counts plus thinking tokens, `duration_ms`, `duration_api_ms`, `cost_usd` (as reported), `cost_basis`, and `attempt` (schema retries and transient retries are separate calls with their own cost). Failed calls that report a cost are logged with `ok: false` and counted.

**Cache hits.** A cache hit logs `{"kind": "llm_cache_hit", "pass", "saved_usd"}`. The cache entry stores the cost of the call that filled it, so the report can say "this rerun saved $X".

**Runs.** Each command that can call an LLM (`analyze`, `fixwords`, `run`, later others) writes `run_start` (id, command, args) and `run_end` (id, exit code, wall time). Cost of a run is the sum of `llm` events with that run id.

**API backends.** A price table `pricing.toml` at the repo root: per model, USD per million tokens for input, output, cache write (5 min and 1 h), cache read, plus a `verified_on` date and a source note. It is user-editable and is filled from the current Anthropic price list (checked with the claude-api reference when the phase is built, never from memory). The API backends compute cost from it. For `claude-cli` the reported cost is used and a second column, `cost_table_usd`, is computed from the same table as a cross-check; a difference above 10% prints a warning (the table or the reported cost is off).

**Report: `shorts cost [<job>] [--run ID] [--all] [--json] [--project MINUTES]`.**
- Per pass and model: calls, retries, tokens (input, cache write, cache read, output), API-equivalent cost, wall time.
- Total for the job or the run, cost per class minute (from `job.json` duration), cost per candidate and per approved clip, and the share of each pass.
- Projection: `--project 100` scales the cost per class minute (and warns that detail is capped by `scan_ceiling`, so linear scaling overstates long classes).
- `--all`: one line per job, side by side, with cost per class minute, to compare classes and model choices.
- Local steps (whisper, ffmpeg, Vision) show wall time and cost `$0.00 (local)`, so the owner sees where the time goes even where no API is involved.
- Plan use: number of calls, and any `limit` events with their timestamps, to relate cost to the plan's limits.

**Also printed at the end of `analyze`, `fixwords` and `run`:** one line, `LLM cost this run: $X.XX API-equivalent (N calls, cache saved $Y.YY)`.

## 4. Non-goals

Real billing reconciliation (this is a list-price estimate), API batch or discount modelling, and cost of local compute. Storing anything outside `log.jsonl` and the existing cache entries.

## 5. Testing

Scripted backend with fixed usage: per-call fields logged; retries counted separately; cache hit logs `saved_usd`; `run_start`/`run_end` bracket the events; `shorts cost` totals, per-minute and projection match hand-computed numbers; `pricing.toml` cost for an API backend call; the 10% cross-check warning; a job whose log predates this change (missing fields) is reported with the fields it has and a note, never an error; `--all` over two jobs.
Live check on the first full class: totals within the reported `total_cost_usd` sum.

## 6. Decisions (owner, 30/09/2026)

1. **No cost prompt by default.** The owner runs on a subscription, so `analyze` never asks before spending. The threshold stays available for later API use as an opt-in setting `cost_confirm_above_usd` in `config.toml` (default `0`, meaning disabled). When set above 0, `analyze` and `fixwords` print the estimate before starting and ask `Continue? [y/N]`; a `--yes` flag skips the question for scripts. The estimate comes from the per-class-minute cost of earlier jobs in `--all` (if none exists, no estimate and no question).
2. **Baseline: yes.** After the feature works, the build session runs the 10-minute sample once more on a scratch job with the new logging (about $1 API-equivalent), so the first full class has a like-for-like comparison. The job lives in the S4 worktree's own `jobs/` folder and reuses the copy `~/dev/albatroz-media/masters/260927-amostra-10min.mov`.
3. **Parallel work.** S4 is built in its own git worktree (`~/dev/albatroz-shorts-s4`, branch `s4-cost-accounting`) while S3 builds in the main checkout. Expected merge overlap with S3 is small and additive (`config.toml`, `cli_jobs.py`, `analyze/run.py`, `jobs.py`).
