"""全市场资金博弈与筹码结构 Mart 数据加载与物化构建器。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.marts.capital_game import (
    CAPITAL_GAME_MART_NAME,
    build_capital_game_frame,
)

if TYPE_CHECKING:
    from stock_analytics.features.store import FeatureStore
    from stock_data.catalog import DataCatalog


def build_capital_game(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    overwrite: bool = False,
) -> pl.DataFrame:
    """加载 ETF、两融、订单流、龙虎榜、大宗与筹码胜率，物化全市场资金博弈宽表。"""
    effective_start = start_date
    if not overwrite:
        existing = store.get_domain_mart(
            CAPITAL_GAME_MART_NAME,
            date_column="trade_date",
            columns=["trade_date"],
        )
        if not existing.is_empty() and "trade_date" in existing.columns:
            latest_val = existing["trade_date"].drop_nulls().max()
            if isinstance(latest_val, date):
                if end_date is None or latest_val <= end_date:
                    if effective_start is None or effective_start <= latest_val:
                        effective_start = latest_val

    load_start = None
    if effective_start is not None:
        lookback_days = 2 * 366 * 6
        load_start = effective_start - timedelta(days=lookback_days)

    etf_flow = store.get_domain_mart(
        "etf_flow_daily",
        date_column="trade_date",
        start_date=load_start,
        end_date=end_date,
    )
    dragon_tiger = store.get_domain_mart(
        "dragon_tiger_daily",
        date_column="trade_date",
        start_date=load_start,
        end_date=end_date,
    )
    block_trade = store.get_domain_mart(
        "block_trade_daily",
        date_column="trade_date",
        start_date=load_start,
        end_date=end_date,
    )
    market_turnover = store.get_market_daily(
        start_date=load_start,
        end_date=end_date,
        columns=["trade_date", "total_turnover"],
    )
    margin = catalog.load_dataset(
        "margin",
        start_date=load_start,
        end_date=end_date,
        columns=["trade_date", "rzmre", "rzche", "rzye"],
    )
    moneyflow = catalog.load_dataset(
        "moneyflow",
        start_date=load_start,
        end_date=end_date,
        columns=[
            "trade_date",
            "buy_elg_amount",
            "sell_elg_amount",
            "buy_lg_amount",
            "sell_lg_amount",
            "buy_sm_amount",
            "sell_sm_amount",
        ],
    )
    cyq_perf = catalog.load_dataset(
        "cyq_perf",
        start_date=load_start,
        end_date=end_date,
        columns=["trade_date", "winner_rate", "cost_5pct", "cost_50pct", "cost_95pct"],
    )

    result = build_capital_game_frame(
        etf_flow=etf_flow,
        margin=margin,
        moneyflow=moneyflow,
        dragon_tiger=dragon_tiger,
        block_trade=block_trade,
        cyq_perf=cyq_perf,
        market_turnover=market_turnover,
        percentile_cutoff=effective_start,
    )
    if result.is_empty():
        return result

    sliced = result
    if effective_start is not None:
        sliced = sliced.filter(pl.col("trade_date") >= effective_start)
    if end_date is not None:
        sliced = sliced.filter(pl.col("trade_date") <= end_date)

    if not sliced.is_empty():
        store.save_domain_mart(
            CAPITAL_GAME_MART_NAME,
            sliced,
            keys=["trade_date"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return result


__all__ = ["build_capital_game"]
