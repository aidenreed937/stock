"""乘联会 / 中汽协新能源汽车月度产销与渗透率事实表转换器。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_data.fetcher.industry.models import NevMonthlyRecord

NEV_MONTHLY_SCHEMA: dict[str, Any] = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "wholesale_volume_ten_thousand": pl.Float64,
    "retail_volume_ten_thousand": pl.Float64,
    "export_volume_ten_thousand": pl.Float64,
    "penetration_rate": pl.Float64,
    "battery_installation_gwh": pl.Float64,
    "yoy_growth": pl.Float64,
}


def empty_nev_monthly() -> pl.DataFrame:
    """返回空新能源车月度事实表 DataFrame。"""
    return pl.DataFrame(schema=NEV_MONTHLY_SCHEMA)


def records_to_nev_frame(records: list[NevMonthlyRecord]) -> pl.DataFrame:
    """将新能源汽车记录列表转换为标准化的 Polars DataFrame。"""
    if not records:
        return empty_nev_monthly()

    data: dict[str, list[Any]] = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "wholesale_volume_ten_thousand": [r.wholesale_volume_ten_thousand for r in records],
        "retail_volume_ten_thousand": [r.retail_volume_ten_thousand for r in records],
        "export_volume_ten_thousand": [r.export_volume_ten_thousand for r in records],
        "penetration_rate": [r.penetration_rate for r in records],
        "battery_installation_gwh": [r.battery_installation_gwh for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
    }
    return (
        pl.DataFrame(data, schema=NEV_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
