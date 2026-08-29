"""申万一级行业产业资本增减持与回购日频 Mart 单元测试。"""

from datetime import date

import polars as pl

from stock_analytics.marts.insider_industry import (
    INSIDER_INDUSTRY_SCHEMA,
    build_insider_industry_frame,
    empty_insider_industry,
)


def _sample_industry_daily() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
            "industry_code": ["801120.SI", "801120.SI", "801120.SI"],
            "industry_name": ["食品饮料", "食品饮料", "食品饮料"],
        }
    )


def _sample_sw_constituents() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "con_code": ["600519.SH", "000858.SZ"],
            "index_code": ["801120.SI", "801120.SI"],
            "in_date": [date(2010, 1, 1), date(2010, 1, 1)],
            "out_date": [None, None],
        }
    )


def _sample_holdertrade() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600519.SH", "000858.SZ"],
            "ann_date": [date(2026, 8, 3), date(2026, 8, 4)],
            "in_de": ["IN", "DE"],
            "change_vol": [10000.0, 5000.0],
            "avg_price": [1500.0, 120.0],
        }
    )


def _sample_repurchase() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "ann_date": [date(2026, 8, 5)],
            "amount": [5000000.0],
        }
    )


def test_empty_insider_industry() -> None:
    df = empty_insider_industry()
    assert df.is_empty()
    assert df.schema == INSIDER_INDUSTRY_SCHEMA


def test_build_insider_industry_frame_normal() -> None:
    ind_daily = _sample_industry_daily()
    constituents = _sample_sw_constituents()
    ht = _sample_holdertrade()
    rep = _sample_repurchase()

    mart = build_insider_industry_frame(ht, rep, constituents, ind_daily)

    assert len(mart) == 3
    assert set(mart.columns) == set(INSIDER_INDUSTRY_SCHEMA.keys())

    # 2026-08-03: 600519 增持 10000 * 1500 = 15,000,000
    day1 = mart.filter(pl.col("trade_date") == date(2026, 8, 3))
    assert day1["increase_amount"][0] == 15000000.0
    assert day1["decrease_amount"][0] == 0.0
    assert day1["increase_count"][0] == 1

    # 2026-08-04: 000858 减持 5000 * 120 = 600,000
    day2 = mart.filter(pl.col("trade_date") == date(2026, 8, 4))
    assert day2["increase_amount"][0] == 0.0
    assert day2["decrease_amount"][0] == 600000.0
    assert day2["decrease_count"][0] == 1

    # 2026-08-05: 600519 回购 5,000,000
    day3 = mart.filter(pl.col("trade_date") == date(2026, 8, 5))
    assert day3["repurchase_amount"][0] == 5000000.0
    assert day3["repurchase_count"][0] == 1

    # 滚动 60D 净额累计: (15,000,000 - 600,000 + 5,000,000) / 1e8 = 0.194 亿元
    assert round(day3["insider_net_amount_yi_60d"][0], 3) == 0.194


def test_build_insider_industry_frame_empty_inputs() -> None:
    res = build_insider_industry_frame(
        pl.DataFrame(), pl.DataFrame(), pl.DataFrame(), pl.DataFrame()
    )
    assert res.is_empty()
