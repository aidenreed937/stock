"""新能源汽车月度产销与渗透率 (CPCA/CAAM) Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import NevMonthlyRecord

NEV_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "wholesale_volume_ten_thousand": pl.Float64,
    "retail_volume_ten_thousand": pl.Float64,
    "export_volume_ten_thousand": pl.Float64,
    "penetration_rate": pl.Float64,
    "battery_installation_gwh": pl.Float64,
    "yoy_growth": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_nev_monthly() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=NEV_MONTHLY_SCHEMA)


def records_to_nev_frame(records: Sequence[NevMonthlyRecord]) -> pl.DataFrame:
    """将新能源汽车月度记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_nev_monthly()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "wholesale_volume_ten_thousand": [r.wholesale_volume_ten_thousand for r in records],
        "retail_volume_ten_thousand": [r.retail_volume_ten_thousand for r in records],
        "export_volume_ten_thousand": [r.export_volume_ten_thousand for r in records],
        "penetration_rate": [r.penetration_rate for r in records],
        "battery_installation_gwh": [r.battery_installation_gwh for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "unit": [r.unit or "ten_thousand_units" for r in records],
        "source": [r.source or "CPCA" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    return (
        pl.DataFrame(data, schema=NEV_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
