"""GenericCleaner 单元测试。"""

import polars as pl

from stock_data.cleaner.generic_cleaner import GenericCleaner, LixingerIndexFundamentalCleaner


def test_generic_cleaner_empty() -> None:
    cleaner = GenericCleaner()
    res = cleaner.clean(pl.DataFrame())
    assert res.is_empty()


def test_generic_cleaner_dedup_and_null_filter() -> None:
    cleaner = GenericCleaner(primary_keys=["symbol", "trade_date"])
    df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", None, "000002.SZ"],
            "trade_date": ["2026-08-10", "2026-08-10", "2026-08-10", "2026-08-10"],
            "pe": [10.0, 10.5, 8.0, 12.0],
        }
    )
    res = cleaner.clean(df)
    assert len(res) == 2
    assert set(res["symbol"].to_list()) == {"000001.SZ", "000002.SZ"}


def test_generic_cleaner_alias_keys() -> None:
    cleaner = GenericCleaner(primary_keys=["ts_code", "trade_date"])
    df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "date": ["2026-08-10", "2026-08-10"],
            "pe": [10.0, 11.0],
        }
    )
    res = cleaner.clean(df)
    assert len(res) == 1


def test_generic_cleaner_compound_entity_keys_with_placeholder_symbol() -> None:
    cleaner = GenericCleaner()
    # 模拟 index_member 场景：多个成分股记录具有相同的 symbol 常量占位符
    df = pl.DataFrame(
        {
            "index_code": ["801812.SI", "801812.SI", "801813.SI"],
            "con_code": ["002294.SZ", "600461.SH", "002756.SZ"],
            "in_date": ["20110105", "20070306", "20210104"],
            "out_date": ["20130628", "20070312", "20211231"],
            "symbol": ["index_member", "index_member", "index_member"],
        }
    )
    res = cleaner.clean(df)
    assert len(res) == 3


def test_lixinger_index_fundamental_cleaner_drops_only_empty_metric_rows() -> None:
    cleaner = LixingerIndexFundamentalCleaner(primary_keys=["stockCode", "date"])
    df = pl.DataFrame(
        {
            "stockCode": ["000300", "000905", "000300"],
            "date": ["2022-04-05", "2026-08-14", "2026-08-14"],
            "pe_ttm.ew": [None, 12.0, None],
            "pe_ttm.mcw": [None, 11.0, 13.0],
            "pb.ew": [None, 1.5, None],
            "pb.mcw": [None, 1.4, None],
            "ps_ttm.ew": [None, 1.2, None],
            "ps_ttm.mcw": [None, 1.1, None],
            "dyr.ew": [None, 0.03, None],
            "dyr.mcw": [None, 0.028, None],
            "mc": [None, 100.0, None],
        }
    )

    result = cleaner.clean(df)

    assert set(result["stockCode"].to_list()) == {"000905", "000300"}

    legacy_df = pl.DataFrame(
        {
            "stockCode": ["000300", "000905"],
            "date": ["2022-04-05", "2026-08-14"],
            "pe_ttm.ew": [None, 12.0],
            "pb.ew": [None, 1.5],
            "ps_ttm.ew": [None, 1.2],
            "dyr.ew": [None, 0.03],
            "mc": [None, 100.0],
        }
    )

    legacy_result = cleaner.clean(legacy_df)

    assert legacy_result["stockCode"].to_list() == ["000905"]
