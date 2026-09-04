"""台积电月度营收的 Curated 派生计算。"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import polars as pl

from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.semiconductor.models import SemiconductorLeadRecord

logger = logging.getLogger(__name__)

_FRED_READ_WARNED = False


def monthly_usdtwd_rate(report_month: str) -> float | None:
    """读取指定月份美元兑新台币月均汇率（TWD/USD）。"""
    global _FRED_READ_WARNED
    try:
        from stock_data.catalog import DataCatalog
        from stock_data.core.runtime import DataRuntimeContext

        cat = DataCatalog(data_source="fred", runtime=DataRuntimeContext.from_root("data"))
        df = cat.load_dataset("macro_indicators", symbols=["DEXTAUS"])
        if df.is_empty():
            return None
        df = df.filter(pl.col("symbol") == "DEXTAUS")
        if df.is_empty():
            return None

        year, month = parse_month_string(report_month)
        target = f"{year:04d}-{month:02d}"
        sub = df.filter(pl.col("trade_date").dt.strftime("%Y-%m") == target)
        if sub.is_empty():
            return None
        mean_val = sub["close"].mean()
        return round(float(str(mean_val)), 4) if mean_val is not None else None
    except Exception as exc:  # noqa: BLE001
        if not _FRED_READ_WARNED:
            logger.warning("读取 FRED DEXTAUS 汇率失败，TSMC USD 营收保持缺失: %s", exc)
            _FRED_READ_WARNED = True
        return None


def convert_ntd_to_usd(revenue_ntd_million: float, report_month: str) -> float | None:
    """按当月真实汇率将 NTD 百万营收折算为 USD 百万。"""
    rate = monthly_usdtwd_rate(report_month)
    if rate is None or rate <= 0:
        return None
    return round(revenue_ntd_million / rate, 2)


def derive_tsmc_mom(records: Sequence[SemiconductorLeadRecord]) -> dict[str, float | None]:
    """在 Curated 阶段按连续月份计算 TSMC 营收环比。"""
    result: dict[str, float | None] = {}
    previous: SemiconductorLeadRecord | None = None
    for record in sorted(records, key=lambda item: item.report_month):
        mom = record.tsmc_revenue_mom
        if (
            mom is None
            and previous is not None
            and _is_consecutive_month(previous.report_month, record.report_month)
            and previous.tsmc_revenue_ntd_million > 0
        ):
            mom = round(
                record.tsmc_revenue_ntd_million / previous.tsmc_revenue_ntd_million - 1.0, 4
            )
        result[record.report_month] = mom
        previous = record
    return result


def _is_consecutive_month(left: str, right: str) -> bool:
    left_year, left_month = parse_month_string(left)
    right_year, right_month = parse_month_string(right)
    if right_year == left_year:
        return right_month == left_month + 1
    return right_year == left_year + 1 and left_month == 12 and right_month == 1
