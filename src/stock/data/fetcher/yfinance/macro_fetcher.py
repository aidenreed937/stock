"""Yahoo Finance 全球宏观资产日线抓取辅助函数。"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl


if TYPE_CHECKING:
    from stock.data.fetcher.yfinance.client import YFinanceClient

logger = logging.getLogger(__name__)


def _macro_number(value: Any) -> float | None:
    """将 Yahoo 数值转换为有限浮点数，保留合法负值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fetch_macro_daily_bars_df(
    client: YFinanceClient,
    symbol: str,
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """抓取宏观资产原始 OHLC，绕过股票 DailyBar 的正价格约束。"""
    end_date_ex = end_date + timedelta(days=1)
    try:
        df = client.query_history(
            symbol=symbol,
            start_date_str=start_date.isoformat(),
            end_date_str=end_date_ex.isoformat(),
            auto_adjust=False,
            repair=True,
        )
    except Exception as exc:
        logger.error(f"YFinance 宏观数据抓取失败 [{symbol}]: {exc}", exc_info=True)
        return pl.DataFrame()

    if df.empty:
        logger.warning(f"YFinance 宏观数据为空: {symbol}")
        return pl.DataFrame()

    rows: list[dict[str, Any]] = []
    for dt, row in df.iterrows():
        trade_date = dt.date() if hasattr(dt, "date") else dt
        rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": _macro_number(row.get("Open")),
                "high": _macro_number(row.get("High")),
                "low": _macro_number(row.get("Low")),
                "close": _macro_number(row.get("Close")),
                "volume": _macro_number(row.get("Volume")) or 0.0,
                "amount": 0.0,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "symbol": pl.String,
            "trade_date": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
            "amount": pl.Float64,
        },
    )


DEFAULT_MACRO_SYMBOLS = (
    "^TNX",
    "^IRX",
    "DX-Y.NYB",
    "CNH=X",
    "GC=F",
    "CL=F",
    "HG=F",
    "^VIX",
)


def fetch_macro_indicators_df(
    client: YFinanceClient,
    start_date: date,
    end_date: date,
    symbols: list[str] | None = None,
) -> pl.DataFrame:
    """批量抓取全球核心宏观资产日线。"""
    target_symbols = symbols or list(DEFAULT_MACRO_SYMBOLS)
    frames = [
        fetch_macro_daily_bars_df(client, symbol, start_date, end_date)
        for symbol in target_symbols
    ]
    frames = [frame for frame in frames if not frame.is_empty()]
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()
