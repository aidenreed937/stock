"""公司行为领域 Mart 测试。"""

from datetime import date

import polars as pl
import pytest

from stock_analytics.marts.corporate_actions import (
    build_block_trade_mart,
    build_insider_activity_mart,
    build_repurchase_mart,
)


def test_build_insider_activity_mart_splits_buy_and_sell_amounts() -> None:
    frame = pl.DataFrame(
        {
            "ann_date": ["2026-08-01", "2026-08-01", "2026-08-02"],
            "in_de": ["IN", "DE", "BUY"],
            "change_vol": [100.0, 50.0, 20.0],
            "avg_price": [10.0, 20.0, 12.0],
        }
    )

    result = build_insider_activity_mart(frame)

    first_day = result.row(0, named=True)
    assert first_day["announcement_date"] == date(2026, 8, 1)
    assert first_day["insider_buy_amount"] == 1000.0
    assert first_day["insider_sell_amount"] == 1000.0
    assert first_day["insider_net_buy_amount"] == 0.0
    assert first_day["insider_buy_event_count"] == 1
    assert first_day["insider_sell_event_count"] == 1
    assert first_day["insider_event_count"] == 2


def test_build_repurchase_mart_counts_implemented_status() -> None:
    frame = pl.DataFrame(
        {
            "ann_date": ["2026-08-01", "2026-08-01", "2026-08-02"],
            "proc": ["完成", "实施中", "董事会预案"],
            "vol": [100.0, 200.0, 300.0],
            "amount": [1000.0, 2000.0, 3000.0],
        }
    )

    result = build_repurchase_mart(frame)

    first_day = result.row(0, named=True)
    assert first_day["repurchase_announcement_count"] == 2
    assert first_day["repurchase_implemented_count"] == 2
    assert first_day["repurchase_volume"] == 300.0
    assert first_day["repurchase_amount"] == 3000.0


def test_build_block_trade_mart_uses_curated_volume_and_discount() -> None:
    block_trade = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": ["2026-08-01", "2026-08-01"],
            "price": [9.0, 11.0],
            "volume": [100.0, 200.0],
            "amount": [900.0, 2200.0],
        }
    )
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 1)],
            "close": [10.0],
        }
    )

    result = build_block_trade_mart(block_trade, bars)
    row = result.row(0, named=True)

    assert row["block_trade_event_count"] == 2
    assert row["block_trade_volume"] == 300.0
    assert row["block_trade_amount"] == 3100.0
    assert row["block_trade_discount_rate_median"] == pytest.approx(0.0)


def test_build_block_trade_mart_keeps_legacy_vol_compatibility() -> None:
    result = build_block_trade_mart(
        pl.DataFrame(
            {
                "trade_date": ["2026-08-01"],
                "price": [10.0],
                "vol": [100.0],
                "amount": [1000.0],
            }
        )
    )

    assert result["block_trade_volume"].to_list() == [100.0]
