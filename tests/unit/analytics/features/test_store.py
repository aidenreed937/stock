"""FeatureStore 单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.analytics.features.store import FeatureStore


def test_feature_store_read_write_and_projection(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    assert store.get_market_daily().is_empty()

    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1), date(2026, 8, 2)],
            "total_turnover": [1000000.0, 2000000.0],
            "adv_dec_ratio": [1.5, 0.8],
            "above_ma20_ratio": [0.65, 0.60],
        }
    )
    store.save_market_daily(df)

    # 1. 完整读取
    loaded = store.get_market_daily()
    assert len(loaded) == 2
    assert "total_turnover" in loaded.columns

    # 2. 列投影读取
    projected = store.get_market_daily(columns=["trade_date", "total_turnover"])
    assert projected.columns == ["trade_date", "total_turnover"]
    assert len(projected) == 2

    # 3. 日期过滤
    filtered = store.get_market_daily(start_date=date(2026, 8, 2), end_date=date(2026, 8, 2))
    assert len(filtered) == 1
    assert filtered["trade_date"][0] == date(2026, 8, 2)

    # 4. 最新日期
    assert store.get_latest_market_daily_date() == date(2026, 8, 2)


def test_feature_store_merge_incremental(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")

    df1 = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1)],
            "total_turnover": [1000.0],
        }
    )
    store.save_market_daily(df1)

    df2 = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 2)],
            "total_turnover": [2000.0],
        }
    )
    store.save_market_daily(df2, overwrite=False)

    merged = store.get_market_daily()
    assert len(merged) == 2
    assert merged["trade_date"].to_list() == [date(2026, 8, 1), date(2026, 8, 2)]
