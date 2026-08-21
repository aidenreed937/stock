"""理杏仁 K 线响应到领域模型的转换辅助函数。"""

from datetime import date, datetime
from typing import Any

from stock_core.models.market import DailyBar


def fetch_daily_bars(fetcher: Any, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
    """抓取数据并转换为 DailyBar 模型列表。"""
    df = fetcher.fetch_daily_bars_df(
        symbol, start_date, end_date, endpoint="cn/company/candlestick"
    )
    if df.is_empty():
        return []

    bars: list[DailyBar] = []
    for row in df.iter_rows(named=True):
        trade_date_val = row.get("date") or row.get("trade_date")
        if isinstance(trade_date_val, str):
            parsed_date = datetime.strptime(trade_date_val[:10], "%Y-%m-%d").date()
        elif isinstance(trade_date_val, date):
            parsed_date = trade_date_val
        else:
            parsed_date = date.today()

        code_val = row.get("stockCode", symbol)
        bars.append(
            DailyBar(
                symbol=str(code_val),
                trade_date=parsed_date,
                open=float(row.get("open", row.get("cp", 0.0))),
                high=float(row.get("high", row.get("cp", 0.0))),
                low=float(row.get("low", row.get("cp", 0.0))),
                close=float(row.get("close", row.get("cp", 0.0))),
                volume=float(row.get("volume", 0.0)),
                amount=float(row.get("amount", 0.0)),
            )
        )
    return bars
