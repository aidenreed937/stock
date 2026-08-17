from datetime import date

import polars as pl

from stock.analytics.domains.micro.sentiment import MarketSentimentAnalyzer


def test_market_sentiment_analyzer() -> None:
    # 10 只股票，其中 2 只 PB < 1.0 -> 破净率 20%
    basic_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)] * 10,
            "symbol": [f"STOCK_{i}" for i in range(10)],
            "pb": [0.8, 0.9, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0, 2.5, 1.8],
            "turnover_rate": [1.5] * 10,  # 换手率 1.5% (<2.3% 地量)
        }
    )

    analyzer = MarketSentimentAnalyzer()
    res = analyzer.diagnose_latest(sentiment_df=analyzer.calculate_series(daily_basic_df=basic_df))

    assert res is not None
    assert res.pb_break_ratio == 20.0
    assert res.turnover_ratio == 1.5
    assert res.is_wide_pb_broken_bottom is True
    assert res.is_shrink_volume_bottom is True
    assert res.is_huge_volume_peak is False
