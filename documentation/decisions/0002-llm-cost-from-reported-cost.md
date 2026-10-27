# ADR-0002: LLM cost comes from the reported cost, with pricing.toml as a cross-check

- **Status:** accepted
- **Date:** 30/09/26

## Context
Phase S4 records what every LLM call costs so the owner can judge plan limits and the cost of a
100-minute class. `claude -p` (the default backend) reports `total_cost_usd` at API list price,
whatever the plan. The `anthropic-api` and `openai-compatible` backends report tokens only. The
pass, job and run that own a call are known by the caller, but the event is written deep inside
`LLMBackend.complete()`. The cost must never count cached answers as spent, and logs written before
S4 must still be readable.

## Decision
- The cost of a call is the reported cost when there is one, and the `pricing.toml` cost (USD per
  million tokens, with `verified_on` and `source`) otherwise. The table cost is always computed as
  well (`cost_table_usd`), and a difference above 10% prints one warning per backend.
- A `claude -p` envelope with no `usage.cache_creation` split has all its cache writes priced at
  the 1-hour rate (verified 30/09/2026 against a real haiku call: 0.01351 USD).
- One `llm` event per attempt, failed attempts included, in the existing `log.jsonl`.
  `cost_usd` is null, not zero, when a call reports no usage.
- Pass, job and run reach the backend through a context variable (`llm/context.py`), not through
  new parameters.
- A cache hit costs 0, logs `llm_cache_hit` with `saved_usd`, and never enters the spent total. The
  entry stores the cost of the call that filled it (`_cost_usd`) and is written only on a miss.
- The cost question before `analyze` is opt-in (`cost_confirm_above_usd`, default 0).

## Consequences
- The reported number is a list-price estimate, not a bill; every report says so.
- `pricing.toml` needs a refill from the official price list when prices change; the cross-check
  warns when it drifts.
- No new state files. Old logs are reported with the fields they have, plus notes.
- The context variable hides one data flow; tests pin its nesting and restoration.

## Alternatives considered
- Recompute every cost from the table: two numbers for one fact, and the table must always be right.
- Trust the reported cost without a check: a stale price or a misread field goes unnoticed.
- New parameters on `complete()` and every pass: signature changes across many call sites and test doubles.
- A separate cost ledger file: forbidden by the S4 spec (no state outside `log.jsonl` and the cache entries).
- Ask for confirmation by default: on a flat-rate plan the cost is theoretical and the question is noise.
