from datetime import date

import polars as pl

from stock.analytics.domains.industry.tcr import TCRCalculator


def test_tcr_calculator_normal_and_crowded() -> None:
    # 行业 A 占 300 亿 / 1000 亿 = 30% (拥挤), 行业 B 占 100 亿 / 1000 亿 = 10%
    sw_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)] * 4,
            "symbol": ["801080.SI", "801120.SI", "801150.SI", "801730.SI"],
            "amount": [300e8, 100e8, 150e8, 450e8],
        }
    )

    calc = TCRCalculator()
    res = calc.calculate_daily_tcr(target_date=date(2026, 8, 14), sw_daily_df=sw_df)

    assert res is not None
    assert res.total_amount_yi == 1000.0
    # 801730 (电力设备) 占 40%, 801080 (电子) 占 30%
    assert len(res.crowded_industries) == 2
    assert res.top1_tcr == 45.0
    assert res.industries[0].is_crowded is True
    assert res.industries[0].crowding_penalty > 0.5
