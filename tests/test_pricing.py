"""pricing.toml loader and table cost (S4 spec 3, "API backends"). Uses a fixture table, never
the repo's real pricing.toml, so a price update never breaks a test."""
import pytest

from shorts.config import load_config
from shorts.pricing import ModelPrice, PriceTable, cost_from_usage, load_pricing

TABLE = '''verified_on = "2026-09-30"
source = "test fixture"

[models.m-small]
input = 1.0
output = 5.0
cache_write_5m = 1.25
cache_write_1h = 2.0
cache_read = 0.1
'''


def write(tmp_path, text=TABLE):
    p = tmp_path / "pricing.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_pricing_reads_every_price_and_the_verification_date(tmp_path):
    t = load_pricing(write(tmp_path))
    assert t.verified_on == "2026-09-30" and t.source == "test fixture"
    assert t.for_model("m-small") == ModelPrice(1.0, 5.0, 1.25, 2.0, 0.1)
    assert t.for_model("unknown-model") is None


def test_cost_from_usage_prices_each_token_column():
    price = ModelPrice(input=1.0, output=5.0, cache_write_5m=1.25, cache_write_1h=2.0,
                       cache_read=0.1)
    usage = {"input_tokens": 1_000_000, "cache_creation_input_tokens": 3_000_000,
             "cache_creation_1h_input_tokens": 1_000_000, "cache_read_input_tokens": 10_000_000,
             "output_tokens": 200_000}
    # 1.0 + 2 M x 1.25 + 1 M x 2.0 + 10 M x 0.1 + 0.2 M x 5.0 = 1 + 2.5 + 2 + 1 + 1
    assert cost_from_usage(usage, price) == pytest.approx(7.5)


def test_cost_from_usage_matches_the_verified_haiku_call():
    """30/09/2026: 9 input, 6648 cache-write (1 h), 41 output tokens; claude -p reported 0.01351."""
    haiku = ModelPrice(input=1.0, output=5.0, cache_write_5m=1.25, cache_write_1h=2.0,
                       cache_read=0.1)
    usage = {"input_tokens": 9, "cache_creation_input_tokens": 6648,
             "cache_creation_1h_input_tokens": 6648, "cache_read_input_tokens": 0,
             "output_tokens": 41}
    assert cost_from_usage(usage, haiku) == pytest.approx(0.01351)


def test_missing_or_none_usage_fields_count_as_zero():
    price = ModelPrice(1.0, 5.0, 1.25, 2.0, 0.1)
    assert cost_from_usage({"input_tokens": None, "output_tokens": 1_000_000}, price) == 5.0
    assert cost_from_usage({}, price) == 0.0


def test_a_one_hour_count_above_the_total_is_clamped():
    price = ModelPrice(0.0, 0.0, 1.0, 10.0, 0.0)
    usage = {"cache_creation_input_tokens": 1_000_000, "cache_creation_1h_input_tokens": 5_000_000}
    assert cost_from_usage(usage, price) == 10.0


@pytest.mark.parametrize("text,msg", [
    (TABLE.replace('verified_on = "2026-09-30"\n', ""), "verified_on"),
    (TABLE.replace('source = "test fixture"\n', ""), "source"),
    (TABLE.replace("cache_read = 0.1\n", ""), "cache_read"),
    (TABLE.replace("output = 5.0", "output = -5.0"), "negative"),
])
def test_bad_tables_fail_with_a_readable_message(tmp_path, text, msg):
    with pytest.raises(ValueError, match=msg):
        load_pricing(write(tmp_path, text))


def test_repo_pricing_toml_loads_and_prices_every_configured_model():
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    app = load_config(repo / "config.toml")
    table = load_pricing(app.pricing_path)
    for cfg in app.backends.values():
        assert table.for_model(cfg["model"]) is not None, cfg["model"]


def test_config_finds_pricing_toml_next_to_it_or_none(tmp_path):
    (tmp_path / "config.toml").write_text('media_root = "m"\n', encoding="utf-8")
    assert load_config(tmp_path / "config.toml").pricing_path is None
    write(tmp_path)
    assert load_config(tmp_path / "config.toml").pricing_path == tmp_path / "pricing.toml"


def test_price_table_is_a_plain_value():
    t = PriceTable("2026-09-30", "s", {"a": ModelPrice(1, 2, 3, 4, 5)})
    assert t.for_model("a").cache_read == 5
