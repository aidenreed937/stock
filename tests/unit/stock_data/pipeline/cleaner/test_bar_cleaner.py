from datetime import date
from pathlib import Path

import polars as pl

from stock_data.governance.quality.quarantine import QuarantineStore
from stock_data.pipeline.cleaner.bar_cleaner import BarDataCleaner


def test_bar_cleaner_handles_suspended_trading_day() -> None:
    cleaner = BarDataCleaner()
    # 构造包含正常停牌 (vol=0, close=10.0, open=0, high=0, low=0) 与非法价格的数据帧
    df = pl.DataFrame(
        {
            "symbol": ["600000.SH", "600001.SH", "600002.SH"],
            "trade_date": [date(2026, 8, 12), date(2026, 8, 12), date(2026, 8, 12)],
            "open": [0.0, 10.0, -1.0],
            "high": [0.0, 11.0, 10.0],
            "low": [0.0, 9.0, 8.0],
            "close": [10.0, 10.5, 9.0],
            "volume": [0.0, 1000.0, 1000.0],
            "amount": [0.0, 10500.0, 9000.0],
        }
    )

    cleaned = cleaner.clean(df)
    # 600000.SH 停牌记录被保留并填充开高低，600001.SH 正常保留，600002.SH 负价格被剔除
    assert len(cleaned) == 2
    symbols = cleaned["symbol"].to_list()
    assert "600000.SH" in symbols
    assert "600001.SH" in symbols
    assert "600002.SH" not in symbols

    suspended_row = cleaned.filter(pl.col("symbol") == "600000.SH")
    assert suspended_row["open"][0] == 10.0
    assert suspended_row["high"][0] == 10.0
    assert suspended_row["low"][0] == 10.0
    assert suspended_row["close"][0] == 10.0
    assert suspended_row["volume"][0] == 0.0


def test_bar_cleaner_handles_suspended_zero_close_with_pre_close() -> None:
    cleaner = BarDataCleaner()
    # 构造 TuShare 停牌无成交数据 (vol=0, close=0.0/null, pre_close=15.0, open/high/low=0.0)
    df = pl.DataFrame(
        {
            "ts_code": ["600530.SH"],
            "trade_date": ["20260803"],
            "open": [0.0],
            "high": [0.0],
            "low": [0.0],
            "close": [0.0],
            "pre_close": [15.0],
            "vol": [0.0],
            "amount": [None],
        }
    )

    cleaned = cleaner.clean(df)
    assert len(cleaned) == 1
    assert cleaned["close"][0] == 15.0
    assert cleaned["open"][0] == 15.0
    assert cleaned["high"][0] == 15.0
    assert cleaned["low"][0] == 15.0
    assert cleaned["amount"][0] == 0.0


def test_bar_cleaner_deduplicates_mixed_date_formats() -> None:
    cleaner = BarDataCleaner()
    df = pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH"],
            "trade_date": ["2026-08-07", "20260807"],
            "open": [1800.0, 1800.0],
            "high": [1820.0, 1820.0],
            "low": [1790.0, 1790.0],
            "close": [1810.0, 1810.0],
            "volume": [1000.0, 1000.0],
            "amount": [1810000.0, 1810000.0],
        }
    )
    cleaned = cleaner.clean(df)
    assert len(cleaned) == 1


def test_bar_cleaner_imputes_missing_high_low() -> None:
    cleaner = BarDataCleaner()
    # 构造成交量 > 0 但 high/low 为 None 或 <= 0 的非停牌边界记录
    df = pl.DataFrame(
        {
            "symbol": ["302132.SZ", "302133.SZ"],
            "trade_date": [date(2023, 8, 2), date(2023, 8, 3)],
            "open": [52.44, 40.0],
            "high": [None, 0.0],
            "low": [None, -1.0],
            "close": [50.96, 42.0],
            "volume": [372535.6, 100000.0],
            "amount": [1912653.39, 4100000.0],
        }
    )
    cleaned = cleaner.clean(df)
    assert len(cleaned) == 2

    row1 = cleaned.filter(pl.col("symbol") == "302132.SZ")
    assert row1["high"][0] == 52.44  # max(52.44, 50.96)
    assert row1["low"][0] == 50.96  # min(52.44, 50.96)

    row2 = cleaned.filter(pl.col("symbol") == "302133.SZ")
    assert row2["high"][0] == 42.0  # max(40.0, 42.0)
    assert row2["low"][0] == 40.0  # min(40.0, 42.0)


def test_bar_cleaner_can_preserve_null_volume_for_index_data() -> None:
    cleaner = BarDataCleaner(allow_null_volume=True)
    df = pl.DataFrame(
        {
            "symbol": ["801980.SI"],
            "trade_date": ["20130104"],
            "open": [3467.65],
            "high": [3485.71],
            "low": [3386.56],
            "close": [3393.80],
            "volume": [None],
        }
    )

    cleaned = cleaner.clean(df)

    assert len(cleaned) == 1
    assert cleaned["volume"].to_list() == [None]


def test_bar_cleaner_quarantine_handles_integer_amount_after_repair(tmp_path: Path) -> None:
    cleaner = BarDataCleaner()
    df = pl.DataFrame(
        {
            "stockCode": ["399001", "399002"],
            "date": ["2026-08-13", "2026-08-13"],
            "open": [0, 10],
            "high": [0, 9],
            "low": [0, 8],
            "close": [10, -1],
            "volume": [0, 100],
            "amount": [0, 1000],
        }
    )

    cleaned = cleaner.clean_with_quarantine(
        df,
        endpoint="index_daily_bar",
        quarantine=QuarantineStore(tmp_path),
    )

    assert cleaned["stockCode"].to_list() == ["399001"]
    quarantined = pl.read_parquet(tmp_path / "endpoint=index_daily_bar" / "records.parquet")
    assert quarantined["stockCode"].to_list() == ["399002"]


def test_bar_cleaner_quarantines_rows_before_listing_date(tmp_path: Path) -> None:
    cleaner = BarDataCleaner({"000001.SZ": date(2026, 8, 5)})
    df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": [date(2026, 8, 4), date(2026, 8, 5)],
            "open": [10.0, 10.0],
            "high": [10.5, 10.5],
            "low": [9.5, 9.5],
            "close": [10.0, 10.0],
            "volume": [1000.0, 1000.0],
            "amount": [10000.0, 10000.0],
        }
    )

    cleaned = cleaner.clean_with_quarantine(
        df,
        endpoint="stock_daily_bar",
        quarantine=QuarantineStore(tmp_path),
    )

    assert cleaned["trade_date"].to_list() == [date(2026, 8, 5)]
    quarantined = pl.read_parquet(tmp_path / "endpoint=stock_daily_bar" / "records.parquet")
    assert quarantined["quarantine_reason"].to_list() == ["trade_date_before_list_date"]
