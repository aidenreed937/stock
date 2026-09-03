"""聪明钱组合信号 Mart 测试。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.marts.smart_money_build import build_smart_money


class _CatalogStub:
    def __init__(self, top10_holders: pl.DataFrame) -> None:
        self.top10_holders = top10_holders

    def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
        assert dataset == "top10_floatholders"
        return self.top10_holders


def _prepare_store(
    tmp_path: Path, days: int = 600
) -> tuple[FeatureStore, _CatalogStub, list[date]]:
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(days)]
    source_dates = dates[:-10]
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.save_market_daily(pl.DataFrame({"trade_date": dates}))
    store.save_domain_mart(
        "insider_activity_daily",
        pl.DataFrame(
            {
                "announcement_date": source_dates,
                "insider_net_buy_amount": [float(i % 7 + 1) for i in range(len(source_dates))],
            }
        ),
        keys=["announcement_date"],
        date_column="announcement_date",
        overwrite=True,
    )
    store.save_domain_mart(
        "block_trade_daily",
        pl.DataFrame(
            {
                "trade_date": source_dates,
                "block_trade_amount": [1_000_000.0] * len(source_dates),
                "block_trade_discount_rate_median": [-0.05] * len(source_dates),
            }
        ),
        keys=["trade_date"],
        date_column="trade_date",
        overwrite=True,
    )
    event_dates = dates[::20]
    top10 = pl.DataFrame(
        {
            "ann_date": event_dates,
            "holder_name": ["中央汇金"] * len(event_dates),
            "hold_change": [float(i + 1) for i in range(len(event_dates))],
        }
    )
    return store, _CatalogStub(top10), dates


def test_narrow_build_keeps_history_for_rolling_scores(tmp_path: Path) -> None:
    store, catalog, dates = _prepare_store(tmp_path)

    result = build_smart_money(
        catalog,
        store,
        start_date=dates[-2],
        end_date=dates[-1],
    )

    assert result["trade_date"].to_list() == dates[-2:]
    assert result["smart_money_score"].null_count() == 0
    persisted = store.get_domain_mart("smart_money_daily", date_column="trade_date")
    assert persisted.height == len(dates)
    assert persisted.tail(2)["smart_money_score"].null_count() == 0


def test_existing_null_rows_are_recomputed(tmp_path: Path) -> None:
    store, catalog, dates = _prepare_store(tmp_path)
    store.save_domain_mart(
        "smart_money_daily",
        pl.DataFrame(
            {
                "trade_date": dates,
                "insider_score": [1.0] * (len(dates) - 2) + [None, None],
                "block_score": [1.0] * (len(dates) - 2) + [None, None],
                "nat_score": [1.0] * (len(dates) - 2) + [None, None],
                "smart_money_score": [1.0] * (len(dates) - 2) + [None, None],
            }
        ),
        keys=["trade_date"],
        date_column="trade_date",
        overwrite=True,
    )

    build_smart_money(
        catalog,
        store,
        start_date=dates[-2],
        end_date=dates[-1],
    )

    persisted = store.get_domain_mart("smart_money_daily", date_column="trade_date")
    assert persisted.tail(2)["smart_money_score"].null_count() == 0
