from datetime import date

import polars as pl

from stock.analytics.micro.margin import MarginPenetrationCalculator


def test_margin_penetration_calculator() -> None:
    # 优先使用 rzrqye 融资融券余额 (1.52e12 元 = 15200 亿元)
    margin_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "rzrqye": [1.52e12],
            "rzye": [1.50e12],
            "rqye": [0.02e12],
        }
    )
    # 流通市值 600000 亿元 (6e13 元) -> 渗透率 = 15200 / 600000 * 100 = 2.5333% -> 2.53%
    basic_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "circ_mv": [6e13],
        }
    )

    calc = MarginPenetrationCalculator()
    res_df = calc.calculate_series(margin_df=margin_df, daily_basic_df=basic_df)

    assert len(res_df) == 1
    assert res_df["margin_balance_yi"][0] == 15200.0
    assert res_df["circ_mv_yi"][0] == 600000.0
    assert round(res_df["margin_penetration"][0], 2) == 2.53


def test_margin_penetration_calculator_sum_rzye_rqye() -> None:
    # 无 rzrqye 时通过 rzye + rqye 自动合成 (1.50e12 + 0.02e12 = 1.52e12 元)
    margin_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "rzye": [1.50e12],
            "rqye": [0.02e12],
        }
    )
    basic_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "circ_mv": [6e13],
        }
    )

    calc = MarginPenetrationCalculator()
    res_df = calc.calculate_series(margin_df=margin_df, daily_basic_df=basic_df)

    assert len(res_df) == 1
    assert res_df["margin_balance_yi"][0] == 15200.0
    assert round(res_df["margin_penetration"][0], 2) == 2.53
