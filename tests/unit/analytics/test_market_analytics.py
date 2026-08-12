from datetime import date
from unittest.mock import MagicMock

import polars as pl

from stock.analytics.market import MarketBreadthAnalyzer


def test_calculate_breadth_empty():
    mock_store = MagicMock()
    mock_store.query_history.return_value = pl.DataFrame()

    analyzer = MarketBreadthAnalyzer(store=mock_store)
    result = analyzer.calculate_breadth(start_date=date(2026, 1, 1), end_date=date(2026, 1, 10))

    assert result.is_empty()
    assert "breadth_ratio" in result.columns


def test_calculate_breadth_success():
    # 构造模拟数据：2只股票，各 5 天数据 (window=3)
    # A 股票价格上涨并保持在 3日均线上方
    # B 股票价格下跌并跌破 3日均线
    dates = [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
    ]

    data = []
    # Stock A: [10, 11, 12, 13, 14] -> MA3 on day 5 = 13, close=14 > 13 (is_above=True)
    for d, p in zip(dates, [10.0, 11.0, 12.0, 13.0, 14.0], strict=False):
        data.append({"symbol": "000001.SZ", "trade_date": d, "close": p})

    # Stock B: [14, 13, 12, 11, 10] -> MA3 on day 5 = 11, close=10 < 11 (is_above=False)
    for d, p in zip(dates, [14.0, 13.0, 12.0, 11.0, 10.0], strict=False):
        data.append({"symbol": "000002.SZ", "trade_date": d, "close": p})

    mock_df = pl.DataFrame(data)
    mock_store = MagicMock()
    mock_store.query_history.return_value = mock_df

    analyzer = MarketBreadthAnalyzer(store=mock_store)
    result = analyzer.calculate_breadth(window=3)

    assert len(result) == 5
    # 第 5 天 (2026-01-05)：Stock A is_above=True, Stock B is_above=False -> ratio = 0.5
    last_row = result.filter(pl.col("trade_date") == date(2026, 1, 5))
    assert last_row["total_stocks"].item() == 2
    assert last_row["stocks_above_ma"].item() == 1
    assert last_row["breadth_ratio"].item() == 0.5
