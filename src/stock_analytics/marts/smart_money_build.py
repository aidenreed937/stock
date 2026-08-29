"""聪明钱组合信号 Mart 数据加载与物化构建器。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.marts.corporate_actions import (
    BLOCK_TRADE_MART_NAME,
    INSIDER_MART_NAME,
)
from stock_analytics.marts.smart_money import (
    SMART_MONEY_MART_NAME,
    build_smart_money_frame,
)

if TYPE_CHECKING:
    from stock_analytics.features.store import FeatureStore
    from stock_data.catalog import DataCatalog


def build_smart_money(
    catalog: DataCatalog,
    store: FeatureStore,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    overwrite: bool = False,
) -> pl.DataFrame:
    """加载增持/大宗/十大股东数据并物化聪明钱组合信号宽表。

    组合信号需要长回看窗口（1250/500 日滚动分位）做冷启动，
    计算量小（输入均为已物化 Mart / 事实表），默认全量重算。
    """
    if not overwrite:
        existing = store.get_domain_mart(
            SMART_MONEY_MART_NAME,
            date_column="trade_date",
            columns=["trade_date"],
        )
        if not existing.is_empty() and "trade_date" in existing.columns:
            latest_val = existing["trade_date"].drop_nulls().max()
            if isinstance(latest_val, date) and (end_date is None or latest_val >= end_date):
                if start_date is None or latest_val >= start_date:
                    return existing

    insider = store.get_domain_mart(
        INSIDER_MART_NAME,
        date_column="announcement_date",
        start_date=start_date,
        end_date=end_date,
    )
    block_trade = store.get_domain_mart(
        BLOCK_TRADE_MART_NAME,
        date_column="trade_date",
        start_date=start_date,
        end_date=end_date,
    )
    top10_holders = catalog.load_dataset("top10_floatholders")
    calendar = (
        store.get_market_daily(columns=["trade_date"]).select("trade_date").sort("trade_date")
    )
    if start_date is not None:
        calendar = calendar.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        calendar = calendar.filter(pl.col("trade_date") <= end_date)

    frame = build_smart_money_frame(insider, block_trade, top10_holders, calendar)
    if not frame.is_empty():
        store.save_domain_mart(
            SMART_MONEY_MART_NAME,
            frame,
            keys=["trade_date"],
            date_column="trade_date",
            overwrite=overwrite,
        )
    return frame


__all__ = ["build_smart_money"]
