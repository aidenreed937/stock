"""GenericCleaner 单元测试。"""

import polars as pl

from stock.data.cleaner.generic_cleaner import GenericCleaner


def test_generic_cleaner_empty() -> None:
    cleaner = GenericCleaner()
    res = cleaner.clean(pl.DataFrame())
    assert res.is_empty()


def test_generic_cleaner_dedup_and_null_filter() -> None:
    cleaner = GenericCleaner(primary_keys=["symbol", "trade_date"])
    df = pl.DataFrame({
        "symbol": ["000001.SZ", "000001.SZ", None, "000002.SZ"],
        "trade_date": ["2026-08-10", "2026-08-10", "2026-08-10", "2026-08-10"],
        "pe": [10.0, 10.5, 8.0, 12.0],
    })
    res = cleaner.clean(df)
    assert len(res) == 2
    assert set(res["symbol"].to_list()) == {"000001.SZ", "000002.SZ"}


def test_generic_cleaner_alias_keys() -> None:
    cleaner = GenericCleaner(primary_keys=["ts_code", "trade_date"])
    df = pl.DataFrame({
        "symbol": ["000001.SZ", "000001.SZ"],
        "date": ["2026-08-10", "2026-08-10"],
        "pe": [10.0, 11.0],
    })
    res = cleaner.clean(df)
    assert len(res) == 1
