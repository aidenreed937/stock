from datetime import date, timedelta

import polars as pl

from stock.analytics.domains.micro.breadth import MultiPeriodMarketBreadthAnalyzer


def test_market_breadth_series_and_diagnose() -> None:
    # 构造 130 天 5 只股票的数据
    days = 130
    start_d = date(2026, 1, 1)
    dates = [start_d + timedelta(days=i) for i in range(days)]

    records = []
    for d in dates:
        for s in ["000001.SZ", "600519.SH", "300750.SZ", "002270.SZ", "002050.SZ"]:
            # 价格逐步上升，使得全部站上 MA20, MA60, MA120
            p = 10.0 + (d - start_d).days * 0.1
            records.append({"symbol": s, "trade_date": d, "close": p})

    df = pl.DataFrame(records)

    analyzer = MultiPeriodMarketBreadthAnalyzer()
    breadth_df = analyzer.calculate_breadth_series(bars_df=df)

    assert not breadth_df.is_empty()
    latest_row = breadth_df.tail(1).to_dicts()[0]
    assert latest_row["above_ma20_ratio"] == 100.0
    assert latest_row["above_ma60_ratio"] == 100.0
    assert latest_row["above_ma120_ratio"] == 100.0

    diag = analyzer.diagnose_latest(breadth_df=breadth_df)
    assert diag is not None
    assert diag.above_ma20_ratio == 100.0
