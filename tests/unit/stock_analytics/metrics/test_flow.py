from datetime import date, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from stock_analytics.metrics import MetricContext, MetricEngine, create_default_registry
from stock_analytics.primitives.rules import rolling_percentile


class FakeCatalog:
    data_source = "tushare"
    storage_dir = Path("data/curated")

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self.datasets = datasets

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: object = None,
        end_date: object = None,
    ) -> pl.DataFrame:
        return self.datasets.get(dataset, pl.DataFrame())


def _context() -> MetricContext:
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(21)]
    margin = pl.DataFrame(
        {
            "trade_date": dates,
            "rzrqye": [100.0 + index for index in range(21)],
            "rzmre": [20.0] * 21,
        }
    )
    bars = pl.DataFrame({"trade_date": dates, "amount": [100.0] * 21})
    daily_basic = pl.DataFrame({"trade_date": dates, "circ_mv": [1000.0] * 21})
    moneyflow = pl.DataFrame(
        {
            "trade_date": dates,
            "net_mf_amount": [10.0] * 21,
            "buy_elg_amount": [8.0] * 21,
            "sell_elg_amount": [3.0] * 21,
        }
    )
    moneyflow_hsgt = pl.DataFrame(
        {
            "trade_date": dates,
            "north_money": [100.0] * 21,
        }
    )
    catalog = FakeCatalog(
        {
            "margin": margin,
            "stock_daily_bar": bars,
            "daily_basic": daily_basic,
            "moneyflow": moneyflow,
            "moneyflow_hsgt": moneyflow_hsgt,
        }
    )
    return MetricContext(catalog=cast("object", catalog))


def test_default_registry_contains_dimensionless_margin_metrics() -> None:
    registry = create_default_registry()

    assert {
        "margin_buy_share",
        "margin_penetration",
        "margin_balance_growth_20d",
        "margin_buy_share_zscore_60d",
        "margin_penetration_percentile_1250d",
        "leverage_sentiment_score",
        "main_money_net_inflow_share",
        "super_large_net_inflow_share",
        "main_money_net_inflow_share_zscore_60d",
        "northbound_net_inflow",
        "northbound_net_inflow_share",
        "northbound_net_inflow_zscore_60d",
        "market_amount_percentile_1250d",
    }.issubset(registry.specs)


def test_engine_computes_margin_share_and_penetration() -> None:
    results = MetricEngine().compute(
        ["margin_buy_share", "margin_penetration"],
        context=_context(),
    )

    assert results[0].frame["margin_buy_share"][0] == 0.2
    assert results[1].frame["margin_penetration"][0] == 0.1


def test_engine_computes_balance_growth_and_handles_zero_market_amount() -> None:
    context = _context()
    context.cache.clear()
    context.cache["tushare:margin:None:None"] = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "rzrqye": [100.0, 110.0],
            "rzmre": [10.0, 10.0],
        }
    )
    context.cache["tushare:stock_daily_bar:None:None"] = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "amount": [0.0, 100.0],
        }
    )
    context.cache["tushare:daily_basic:None:None"] = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "circ_mv": [1000.0, 1000.0],
        }
    )

    result = MetricEngine().compute(["margin_balance_growth_20d"], context=context)[0]

    assert result.frame["margin_balance_growth_20d"].to_list() == [None, None]


def test_engine_computes_moneyflow_and_northbound_market_metrics() -> None:
    dates = [date(2026, 1, 1), date(2026, 1, 2)]
    catalog = FakeCatalog(
        {
            "stock_daily_bar": pl.DataFrame(
                {
                    "trade_date": [dates[0], dates[0], dates[1], dates[1]],
                    "amount": [100.0, 100.0, 200.0, 300.0],
                }
            ),
            "moneyflow": pl.DataFrame(
                {
                    "trade_date": [dates[0], dates[0], dates[1], dates[1]],
                    "net_mf_amount": [10.0, -2.0, 20.0, 5.0],
                    "buy_elg_amount": [8.0, 1.0, 15.0, 2.0],
                    "sell_elg_amount": [3.0, 2.0, 5.0, 1.0],
                }
            ),
            "moneyflow_hsgt": pl.DataFrame(
                {
                    "trade_date": dates,
                    "north_money": [100.0, 200.0],
                }
            ),
        }
    )
    context = MetricContext(catalog=cast("object", catalog))

    results = MetricEngine().compute(
        [
            "main_money_net_inflow_share",
            "super_large_net_inflow_share",
            "northbound_net_inflow",
            "northbound_net_inflow_share",
        ],
        context=context,
    )

    assert results[0].frame["main_money_net_inflow_share"].to_list() == pytest.approx([0.04, 0.05])
    assert results[1].frame["super_large_net_inflow_share"].to_list() == pytest.approx(
        [0.02, 0.022]
    )
    assert results[2].frame["northbound_net_inflow"].to_list() == pytest.approx([100.0, 200.0])
    assert results[3].frame["northbound_net_inflow_share"].to_list() == pytest.approx([0.5, 0.4])


def test_market_flow_rolling_metrics_use_declared_windows() -> None:
    dates = [date(2022, 1, 1) + timedelta(days=index) for index in range(1251)]
    catalog = FakeCatalog(
        {
            "stock_daily_bar": pl.DataFrame(
                {
                    "trade_date": dates,
                    "amount": [100.0 + index for index in range(1251)],
                }
            ),
            "moneyflow": pl.DataFrame(
                {
                    "trade_date": dates,
                    "net_mf_amount": [float(index + 1) for index in range(1251)],
                    "buy_elg_amount": [10.0] * 1251,
                    "sell_elg_amount": [5.0] * 1251,
                }
            ),
            "moneyflow_hsgt": pl.DataFrame(
                {
                    "trade_date": dates,
                    "north_money": [100.0 + index * 100.0 for index in range(1251)],
                }
            ),
            "daily_basic": pl.DataFrame(
                {
                    "trade_date": dates,
                    "circ_mv": [1000.0] * 1251,
                }
            ),
        }
    )
    context = MetricContext(catalog=cast("object", catalog))

    results = MetricEngine().compute(
        [
            "market_amount_percentile_1250d",
            "main_money_net_inflow_share_zscore_60d",
            "northbound_net_inflow_zscore_60d",
        ],
        context=context,
    )

    assert results[0].frame["market_amount_percentile_1250d"].tail(2).to_list() == [
        100.0,
        100.0,
    ]
    assert results[1].frame["main_money_net_inflow_share_zscore_60d"].null_count() == 59
    assert results[2].frame["northbound_net_inflow_zscore_60d"].null_count() == 59


def test_rolling_percentile_uses_rank_instead_of_min_max_position() -> None:
    frame = pl.DataFrame({"value": [1.0, 100.0, 2.0]}).with_columns(rolling_percentile("value", 3))

    assert frame["value_percentile_3d"][-1] == pytest.approx(50.0)


def test_market_flow_share_returns_none_when_amount_or_float_mv_is_invalid() -> None:
    dates = [date(2026, 1, 1), date(2026, 1, 2)]
    catalog = FakeCatalog(
        {
            "stock_daily_bar": pl.DataFrame({"trade_date": dates, "amount": [0.0, 100.0]}),
            "daily_basic": pl.DataFrame({"trade_date": dates, "circ_mv": [1000.0, 0.0]}),
            "moneyflow": pl.DataFrame(
                {
                    "trade_date": dates,
                    "net_mf_amount": [10.0, 10.0],
                    "buy_elg_amount": [8.0, 8.0],
                    "sell_elg_amount": [3.0, 3.0],
                }
            ),
        }
    )
    result = MetricEngine().compute(
        ["main_money_net_inflow_share", "market_amount_percentile_1250d"],
        context=MetricContext(catalog=cast("object", catalog)),
    )

    assert result[0].frame["main_money_net_inflow_share"].to_list() == [None, 0.1]
    assert result[1].frame["market_amount_percentile_1250d"].to_list() == [None, None]


def test_market_turnover_and_moneyflow_share_are_scale_invariant() -> None:
    dates = [date(2026, 1, 1), date(2026, 1, 2)]
    base = {
        "stock_daily_bar": pl.DataFrame({"trade_date": dates, "amount": [100.0, 200.0]}),
        "daily_basic": pl.DataFrame({"trade_date": dates, "circ_mv": [1000.0, 1000.0]}),
        "moneyflow": pl.DataFrame(
            {
                "trade_date": dates,
                "net_mf_amount": [10.0, 20.0],
                "buy_elg_amount": [8.0, 16.0],
                "sell_elg_amount": [3.0, 6.0],
            }
        ),
    }
    scaled = {
        "stock_daily_bar": base["stock_daily_bar"].with_columns(
            (pl.col("amount") * 1000.0).alias("amount")
        ),
        "daily_basic": base["daily_basic"].with_columns(
            (pl.col("circ_mv") * 1000.0).alias("circ_mv")
        ),
        "moneyflow": base["moneyflow"].with_columns(
            (pl.col("net_mf_amount") * 1000.0).alias("net_mf_amount"),
            (pl.col("buy_elg_amount") * 1000.0).alias("buy_elg_amount"),
            (pl.col("sell_elg_amount") * 1000.0).alias("sell_elg_amount"),
        ),
    }

    base_results = MetricEngine().compute(
        ["main_money_net_inflow_share"],
        context=MetricContext(catalog=cast("object", FakeCatalog(base))),
    )
    scaled_results = MetricEngine().compute(
        ["main_money_net_inflow_share"],
        context=MetricContext(catalog=cast("object", FakeCatalog(scaled))),
    )

    assert scaled_results[0].frame["main_money_net_inflow_share"].to_list() == pytest.approx(
        base_results[0].frame["main_money_net_inflow_share"].to_list()
    )


def test_rolling_percentile_ignores_historical_nulls_when_current_value_exists() -> None:
    frame = pl.DataFrame({"value": [1.0, 2.0, None, 3.0, 4.0, None]}).with_columns(
        rolling_percentile("value", 5)
    )

    assert frame["value_percentile_5d"][4] == pytest.approx(100.0)
    assert frame["value_percentile_5d"][5] is None
