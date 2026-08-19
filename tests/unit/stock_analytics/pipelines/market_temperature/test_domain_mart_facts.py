"""市场温度计领域 Mart 观察事实测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.pipelines.market_temperature.domain_mart_facts import (
    collect_domain_mart_observations,
)


def test_collect_domain_mart_observations_reads_latest_available_rows(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.save_domain_mart(
        "convertible_bond_daily",
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 1), date(2026, 8, 2)],
                "cb_price_median": [105.0, 108.0],
                "cb_conversion_premium_median": [10.0, 12.0],
                "cb_valid_count": [100, 101],
                "cb_low_price_count": [20, 21],
            }
        ),
        keys=["trade_date"],
        date_column="trade_date",
    )

    rows = collect_domain_mart_observations(as_of_date=date(2026, 8, 2), storage_dir=tmp_path)

    price = next(row for row in rows if row["metric_id"] == "cb_price_median_observation")
    low_share = next(row for row in rows if row["metric_id"] == "cb_low_price_share_observation")
    assert price["value_float"] == 108.0
    assert price["status"] == "ok"
    assert price["sample_size"] == 101
    assert low_share["value_float"] == 21.0 / 101.0
    assert low_share["sample_size"] == 101
    assert all(row["category"] == "domain_observation" for row in rows)


def test_collect_domain_mart_observations_does_not_use_future_rows(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.save_domain_mart(
        "block_trade_daily",
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 3)],
                "block_trade_discount_rate_median": [-0.02],
                "block_trade_event_count": [4],
            }
        ),
        keys=["trade_date"],
        date_column="trade_date",
    )

    rows = collect_domain_mart_observations(as_of_date=date(2026, 8, 2), storage_dir=tmp_path)
    block_trade = next(
        row for row in rows if row["metric_id"] == "block_trade_discount_observation"
    )
    assert block_trade["value_float"] is None
    assert block_trade["status"] == "unavailable"


def test_collect_domain_mart_observations_keeps_iv_underlying_identity(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.save_domain_mart(
        "settlement_iv_proxy_daily",
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 2)],
                "underlying_symbol": ["000300.SH"],
                "settlement_iv_proxy_median": [0.24],
                "settlement_iv_proxy_valid_count": [12],
            }
        ),
        keys=["trade_date", "underlying_symbol"],
        date_column="trade_date",
    )

    rows = collect_domain_mart_observations(as_of_date=date(2026, 8, 2), storage_dir=tmp_path)
    iv = next(
        row for row in rows if row["metric_id"] == "settlement_iv_proxy_observation.000300.SH"
    )
    assert iv["value_float"] == 0.24
    assert iv["sample_size"] == 12
