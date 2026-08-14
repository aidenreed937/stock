from datetime import date, timedelta

import polars as pl

from stock.analytics.industry.momentum_spread import IndustryMomentumSpreadAnalyzer


def test_momentum_spread_analyzer() -> None:
    # 构造 150 天的历史数据，10 个行业
    days = 150
    start_d = date(2026, 1, 1)
    dates = [start_d + timedelta(days=i) for i in range(days)]

    records = []
    for d in dates:
        for i in range(1, 12):
            sym = f"8010{i:02d}.SI"
            # 行业 1~5 涨幅巨大，行业 6~10 持续阴跌
            base_price = 10.0 + (i * 2.0)
            if i <= 5:
                price = base_price * (1.0 + (d - start_d).days * 0.01)
            else:
                price = base_price * (1.0 - (d - start_d).days * 0.002)
            records.append({"symbol": sym, "trade_date": d, "close": price})

    df = pl.DataFrame(records)

    analyzer = IndustryMomentumSpreadAnalyzer()
    res = analyzer.calculate_spread(sw_daily_df=df, long_window=60, short_window=10)

    assert res is not None
    assert len(res.top_leaders_120d) == 5
    assert len(res.bottom_laggards_20d) == 5
    assert res.spread > 0
