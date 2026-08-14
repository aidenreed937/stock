from datetime import date

import polars as pl

from stock.analytics.industry.pb_roe import IndustryPBROEAnalyzer


def test_industry_pb_roe_analyzer() -> None:
    val_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)] * 6,
            "symbol": ["IND_1", "IND_2", "IND_3", "IND_4", "IND_5", "IND_6"],
            "name": ["行业1", "行业2", "行业3", "行业4", "行业5", "行业6"],
            "pb.ew": [1.0, 2.0, 3.0, 4.0, 1.2, 5.0],
            "roe.ttm": [5.0, 10.0, 15.0, 20.0, 18.0, 25.0],  # 行业5 高 ROE (18%) 但低 PB (1.2)
        }
    )

    analyzer = IndustryPBROEAnalyzer()
    res = analyzer.analyze_cross_section(target_date=date(2026, 8, 14), val_df=val_df)

    assert res is not None
    assert res.regression_beta > 0  # ROE 越高通常 PB 越高
    assert res.r_squared > 0.5
    # 行业5 应该具有最低的残差 (被低估)
    assert res.industries[0]["name"] == "行业5"
    assert "行业5" in res.undervalued_industries
