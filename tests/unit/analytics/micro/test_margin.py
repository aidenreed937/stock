from datetime import date

import polars as pl

from stock.analytics.micro.margin import MarginPenetrationCalculator


def test_margin_penetration_calculator() -> None:
    # 两融余额 15000 亿元 (1.5e12 元)
    margin_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "rzye": [1.5e12],
        }
    )
    # 流通市值 600000 亿元 (6e13 元) -> 渗透率 = 15000 / 600000 * 100 = 2.5%
    basic_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "circ_mv": [6e13],
        }
    )

    calc = MarginPenetrationCalculator()
    res_df = calc.calculate_series(margin_df=margin_df, daily_basic_df=basic_df)

    assert len(res_df) == 1
    assert res_df["margin_balance_yi"][0] == 15000.0
    assert res_df["circ_mv_yi"][0] == 600000.0
    assert round(res_df["margin_penetration"][0], 2) == 2.5
