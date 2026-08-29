from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.industry_structure.factor_panel import (
    _cs_percentile,
    build_industry_factor_panel,
    load_latest_industry_factors,
    save_industry_factor_panel,
)


def test_cs_percentile_expression() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1)] * 3 + [date(2026, 1, 2)] * 3,
            "val": [10.0, 20.0, 30.0, 100.0, 50.0, 200.0],
        }
    )
    res = df.with_columns(_cs_percentile("val").alias("pct"))
    assert res["pct"].to_list() == [0.0, 50.0, 100.0, 50.0, 0.0, 100.0]


def test_build_industry_factor_panel_runs() -> None:
    panel = build_industry_factor_panel(start_date=date(2026, 8, 1))
    assert not panel.is_empty()
    assert {
        "trade_date",
        "industry_code",
        "industry_name",
        "close",
        "ind_momentum",
        "ind_scissors",
        "ind_crowding",
        "ind_valuation",
        "ind_smart_flow",
        "composite_industry_score",
    }.issubset(panel.columns)


def test_save_and_load_industry_factors(tmp_path: Path) -> None:
    panel = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 25), date(2026, 8, 26)],
            "industry_code": ["801010.SI", "801010.SI"],
            "industry_name": ["农林牧渔", "农林牧渔"],
            "close": [100.0, 101.0],
            "ind_momentum": [60.0, 65.0],
            "ind_scissors": [50.0, 55.0],
            "ind_crowding": [20.0, 22.0],
            "ind_valuation": [80.0, 78.0],
            "ind_smart_flow": [60.0, 62.0],
            "composite_industry_score": [62.0, 64.0],
        }
    )
    save_industry_factor_panel(panel, output_dir=tmp_path, as_of=date(2026, 8, 26))
    _run_dir, loaded, _manifest = load_latest_industry_factors(artifact_root=tmp_path)
    assert len(loaded) == 2
    assert loaded["industry_code"].to_list() == ["801010.SI", "801010.SI"]
