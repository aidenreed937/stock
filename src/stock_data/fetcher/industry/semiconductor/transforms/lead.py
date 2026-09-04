"""台积电月度营收的 Curated 派生计算。"""

from __future__ import annotations

from collections.abc import Sequence

from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.semiconductor.models import SemiconductorLeadRecord
from stock_data.pipeline.normalizer.unit_normalizer import (
    convert_ntd_to_usd as _convert_ntd_to_usd,
)
from stock_data.pipeline.normalizer.unit_normalizer import (
    monthly_usdtwd_rate as _monthly_usdtwd_rate,
)


def monthly_usdtwd_rate(
    report_month: str, runtime: DataRuntimeContext | None = None
) -> float | None:
    """读取指定月份美元兑新台币月均汇率（TWD/USD）。"""
    return _monthly_usdtwd_rate(report_month, runtime=runtime)


def convert_ntd_to_usd(
    revenue_ntd_million: float,
    report_month: str,
    runtime: DataRuntimeContext | None = None,
) -> float | None:
    """按当月真实汇率将 NTD 百万营收折算为 USD 百万。"""
    return _convert_ntd_to_usd(revenue_ntd_million, report_month, runtime=runtime)


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
