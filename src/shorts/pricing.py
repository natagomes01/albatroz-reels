"""pricing.toml: API list prices per model, USD per million tokens (S4 spec 3, "API backends").

The API backends take their cost from this table; for `claude-cli` the reported cost stays the
cost and the table cost is only a cross-check. It is a list-price estimate, never a bill.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PRICE_FIELDS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


@dataclass(frozen=True)
class ModelPrice:
    input: float            # USD per million uncached input tokens
    output: float           # USD per million output tokens (thinking tokens are output tokens)
    cache_write_5m: float   # USD per million tokens written to a 5-minute cache entry
    cache_write_1h: float   # USD per million tokens written to a 1-hour cache entry
    cache_read: float       # USD per million tokens read from the cache


@dataclass(frozen=True)
class PriceTable:
    verified_on: str        # the date someone checked the prices against the official list
    source: str             # where they were checked
    models: dict[str, ModelPrice]

    def for_model(self, model: str) -> ModelPrice | None:
        return self.models.get(model)


def load_pricing(path: Path) -> PriceTable:
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ("verified_on", "source"):
        if not str(data.get(key, "")).strip():
            raise ValueError(f"{path.name}: missing '{key}' (when and where the prices were checked)")
    models: dict[str, ModelPrice] = {}
    for name, row in (data.get("models") or {}).items():
        missing = [f for f in PRICE_FIELDS if f not in row]
        if missing:
            raise ValueError(f"{path.name}: model '{name}' is missing {', '.join(missing)}")
        values = {f: float(row[f]) for f in PRICE_FIELDS}
        if any(v < 0 for v in values.values()):
            raise ValueError(f"{path.name}: model '{name}' has a negative price")
        models[name] = ModelPrice(**values)
    return PriceTable(str(data["verified_on"]), str(data["source"]), models)


def cost_from_usage(usage: dict, price: ModelPrice) -> float:
    """USD for one call. Missing or None token fields count as 0. Cache writes without a TTL
    split are priced at the 5-minute rate (the backend fills the 1-hour count when it knows it)."""
    def n(key: str) -> int:
        return int(usage.get(key) or 0)

    written = n("cache_creation_input_tokens")
    written_1h = min(n("cache_creation_1h_input_tokens"), written)
    total = (n("input_tokens") * price.input
             + (written - written_1h) * price.cache_write_5m
             + written_1h * price.cache_write_1h
             + n("cache_read_input_tokens") * price.cache_read
             + n("output_tokens") * price.output)
    return total / 1_000_000
