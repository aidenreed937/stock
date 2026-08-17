"""UnitNormalizer 单元测试。"""

import polars as pl

from stock_data.normalizer.unit_normalizer import UnitNormalizer


def test_unit_normalizer_tushare_daily() -> None:
    raw_df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260801"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "vol": [100.0],  # 手
            "amount": [1000.0],  # 千元
        }
    )

    normalizer = UnitNormalizer("tushare", "daily")
    normalized = normalizer.normalize_units(raw_df)

    assert "volume" in normalized.columns
    assert "amount" in normalized.columns
    assert "vol" not in normalized.columns
    assert normalized["volume"][0] == 10000.0  # 100 手 * 100 = 10000 股
    assert normalized["amount"][0] == 1000000.0  # 1000 千元 * 1000 = 1000000 元


def test_unit_normalizer_tushare_stock_daily_bar_alias() -> None:
    raw_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": ["20260801"],
            "close": [10.0],
            "vol": [100.0],
            "amount": [1000.0],
        }
    )

    normalizer = UnitNormalizer("tushare", "stock_daily_bar")
    normalized = normalizer.normalize_units(raw_df)

    assert normalized["volume"][0] == 10000.0
    assert normalized["amount"][0] == 1000000.0


def test_unit_normalizer_tushare_bar_infers_mixed_amount_units_per_row() -> None:
    raw_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "trade_date": ["20260801"] * 3,
            "close": [10.0, 10.0, 10.0],
            "vol": [100.0] * 3,
            "amount": [100.0, 100000.0, 5000.0],
            "source_unit_note": [
                "native unit: thousand yuan",
                "amount is normalized to yuan",
                None,
            ],
        }
    )

    normalized, rejected = UnitNormalizer(
        "tushare", "stock_daily_bar"
    ).normalize_units_with_quarantine(raw_df)

    assert normalized["symbol"].to_list() == ["000001.SZ", "000002.SZ"]
    assert normalized["amount"].to_list() == [100000.0, 100000.0]
    assert normalized["volume"].to_list() == [10000.0, 10000.0]
    assert rejected["symbol"].to_list() == ["000003.SZ"]


def test_unit_normalizer_does_not_reconvert_standard_volume_and_amount() -> None:
    raw_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": ["20260801"],
            "close": [10.0],
            "volume": [10000.0],
            "amount": [100000.0],
        }
    )

    normalized, rejected = UnitNormalizer(
        "tushare", "stock_daily_bar"
    ).normalize_units_with_quarantine(raw_df)

    assert normalized["volume"].to_list() == [10000.0]
    assert normalized["amount"].to_list() == [100000.0]
    assert rejected.is_empty()


def test_unit_normalizer_quarantines_ambiguous_note_without_price_evidence() -> None:
    raw_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": ["20260801"],
            "vol": [100.0],
            "amount": [100.0],
            "source_unit_note": ["native unit"],
        }
    )

    normalized, rejected = UnitNormalizer(
        "tushare", "stock_daily_bar"
    ).normalize_units_with_quarantine(raw_df)

    assert normalized.is_empty()
    assert rejected["symbol"].to_list() == ["000001.SZ"]


def test_unit_normalizer_tushare_daily_basic() -> None:
    raw_df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260801"],
            "total_mv": [500000.0],  # 万元
            "circ_mv": [400000.0],  # 万元
        }
    )

    normalizer = UnitNormalizer("tushare", "daily_basic")
    normalized = normalizer.normalize_units(raw_df)

    assert normalized["total_mv"][0] == 5000000000.0  # 500000 万元 * 10000 = 50 亿元
    assert normalized["circ_mv"][0] == 4000000000.0


def test_unit_normalizer_tushare_limit_endpoints_preserves_native_units() -> None:
    raw_df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260814"],
            "close": [10.0],
            "amount": [123456789.0],
            "float_mv": [9876543210.0],
            "limit": ["U"],
        }
    )

    normalized = UnitNormalizer("tushare", "limit_list_d").normalize_units(raw_df)

    assert normalized.equals(raw_df)
    assert (
        UnitNormalizer("tushare", "stk_limit")
        .normalize_units(
            pl.DataFrame(
                {
                    "ts_code": ["000001.SZ"],
                    "trade_date": ["20260814"],
                    "up_limit": [11.0],
                    "down_limit": [9.0],
                }
            )
        )
        .get_column("up_limit")[0]
        == 11.0
    )


def test_unit_normalizer_tushare_sw_daily() -> None:
    raw_df = pl.DataFrame(
        {
            "ts_code": ["801010.SI"],
            "trade_date": ["20260814"],
            "vol": [200.0],  # 手
            "amount": [1500.0],  # 万元
            "total_mv": [120000.0],  # 万元
            "float_mv": [60000.0],  # 万元
        }
    )

    normalizer = UnitNormalizer("tushare", "sw_daily")
    normalized = normalizer.normalize_units(raw_df)

    assert "volume" in normalized.columns
    assert normalized["volume"][0] == 20000.0  # 200 手 * 100 = 20000 股
    assert normalized["amount"][0] == 15000000.0  # 1500 万元 * 10000 = 15000000 元
    assert normalized["total_mv"][0] == 1200000000.0  # 120000 万元 * 10000 = 1200000000 元
    assert normalized["float_mv"][0] == 600000000.0  # 60000 万元 * 10000 = 600000000 元


def test_unit_normalizer_tushare_moneyflow_hsgt() -> None:
    raw_df = pl.DataFrame(
        {
            "trade_date": ["20260814"],
            "ggt_ss": ["1.0"],
            "ggt_sz": ["2.0"],
            "hgt": ["3.0"],
            "sgt": ["4.0"],
            "north_money": ["5.0"],
            "south_money": ["6.0"],
        }
    )

    normalizer = UnitNormalizer("tushare", "moneyflow_hsgt")
    normalized = normalizer.normalize_units(raw_df)

    assert normalized["ggt_ss"].dtype == pl.Float64
    assert normalized["north_money"].dtype == pl.Float64
    assert normalized["ggt_ss"][0] == 1000000.0
    assert normalized["ggt_sz"][0] == 2000000.0
    assert normalized["hgt"][0] == 3000000.0
    assert normalized["sgt"][0] == 4000000.0
    assert normalized["north_money"][0] == 5000000.0
    assert normalized["south_money"][0] == 6000000.0


def test_unit_normalizer_empty_and_unknown() -> None:
    empty_df = pl.DataFrame()
    normalizer = UnitNormalizer("tushare", "daily")
    assert normalizer.normalize_units(empty_df).is_empty()

    unknown_normalizer = UnitNormalizer("unknown_source", "unknown_endpoint")
    df = pl.DataFrame({"a": [1]})
    assert unknown_normalizer.normalize_units(df).equals(df)
