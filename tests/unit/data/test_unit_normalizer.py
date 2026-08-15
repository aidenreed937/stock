"""UnitNormalizer 单元测试。"""

import polars as pl
from stock.data.normalizer.unit_normalizer import UnitNormalizer


def test_unit_normalizer_tushare_daily() -> None:
    raw_df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260801"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "vol": [100.0],       # 手
            "amount": [1000.0],   # 千元
        }
    )

    normalizer = UnitNormalizer("tushare", "daily")
    normalized = normalizer.normalize_units(raw_df)

    assert "volume" in normalized.columns
    assert "amount" in normalized.columns
    assert "vol" not in normalized.columns
    assert normalized["volume"][0] == 10000.0  # 100 手 * 100 = 10000 股
    assert normalized["amount"][0] == 1000000.0  # 1000 千元 * 1000 = 1000000 元


def test_unit_normalizer_tushare_daily_basic() -> None:
    raw_df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260801"],
            "total_mv": [500000.0],  # 万元
            "circ_mv": [400000.0],   # 万元
        }
    )

    normalizer = UnitNormalizer("tushare", "daily_basic")
    normalized = normalizer.normalize_units(raw_df)

    assert normalized["total_mv"][0] == 5000000000.0  # 500000 万元 * 10000 = 50 亿元
    assert normalized["circ_mv"][0] == 4000000000.0


def test_unit_normalizer_tushare_sw_daily() -> None:
    raw_df = pl.DataFrame(
        {
            "ts_code": ["801010.SI"],
            "trade_date": ["20260814"],
            "vol": [200.0],          # 手
            "amount": [1500.0],       # 万元
            "total_mv": [120000.0],   # 万元
            "float_mv": [60000.0],    # 万元
        }
    )

    normalizer = UnitNormalizer("tushare", "sw_daily")
    normalized = normalizer.normalize_units(raw_df)

    assert "volume" in normalized.columns
    assert normalized["volume"][0] == 20000.0          # 200 手 * 100 = 20000 股
    assert normalized["amount"][0] == 15000000.0       # 1500 万元 * 10000 = 15000000 元
    assert normalized["total_mv"][0] == 1200000000.0   # 120000 万元 * 10000 = 1200000000 元
    assert normalized["float_mv"][0] == 600000000.0    # 60000 万元 * 10000 = 600000000 元


def test_unit_normalizer_empty_and_unknown() -> None:
    empty_df = pl.DataFrame()
    normalizer = UnitNormalizer("tushare", "daily")
    assert normalizer.normalize_units(empty_df).is_empty()

    unknown_normalizer = UnitNormalizer("unknown_source", "unknown_endpoint")
    df = pl.DataFrame({"a": [1]})
    assert unknown_normalizer.normalize_units(df).equals(df)
