"""市场温度计期权结算价隐含波动率代理事实。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.features.store import FeatureStore

if TYPE_CHECKING:
    from datetime import date


def settlement_iv_rows(
    as_of_date: date,
    storage_dir: Path | str | None,
    metric_row_factory: Any,
    percentile_factory: Any,
) -> list[dict[str, Any]]:
    """生成期权结算价 BS-IV 代理与 Put-Call Skew 温度事实。"""
    store = FeatureStore(mart_dir=Path(storage_dir) / "mart" if storage_dir else None)
    frame = store.get_domain_mart(
        "settlement_iv_proxy_daily",
        date_column="trade_date",
        end_date=as_of_date,
    )
    if frame.is_empty() or "trade_date" not in frame.columns:
        return [
            metric_row_factory(
                "sentiment",
                "settlement_iv_proxy_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="settlement_iv_proxy_daily mart 不可用",
            )
        ]
    required = {"settlement_iv_proxy_median", "settlement_iv_proxy_put_call_skew"}
    if not required.issubset(frame.columns):
        return [
            metric_row_factory(
                "sentiment",
                "settlement_iv_proxy_temperature",
                as_of_date,
                None,
                status="insufficient",
                note="settlement_iv_proxy_daily mart 缺少 IV/Skew 字段",
            )
        ]
    aggregated = (
        frame.select(
            "trade_date",
            pl.col("settlement_iv_proxy_median").cast(pl.Float64, strict=False),
            pl.col("settlement_iv_proxy_put_call_skew").cast(pl.Float64, strict=False),
        )
        .group_by("trade_date")
        .agg(
            pl.col("settlement_iv_proxy_median").median().alias("_value"),
            pl.col("settlement_iv_proxy_put_call_skew").median().alias("_skew"),
        )
        .sort("trade_date")
    )
    median_frame = aggregated.select("trade_date", "_value")
    skew_frame = aggregated.select("trade_date", pl.col("_skew").alias("_value"))
    return [
        percentile_factory(
            median_frame,
            "settlement_iv_proxy_temperature",
            "_value",
            as_of_date,
            inverse=True,
            dimension="sentiment",
            note="期权结算价BS-IV全市场中位数历史反向分位；IV高=恐慌避险需求；非标准VIX",
        ),
        percentile_factory(
            skew_frame,
            "settlement_iv_proxy_skew_temperature",
            "_value",
            as_of_date,
            inverse=True,
            dimension="sentiment",
            note="期权认沽-认购IV偏度历史反向分位；偏高=尾部对冲需求；非标准VIX",
        ),
    ]
