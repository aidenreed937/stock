"""TuShare 全市场财务报告期请求辅助函数。"""

import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import polars as pl

from stock_core.utils.logger import logger
from stock_data.fetcher.tushare.client import TuShareClient
from stock_data.fetcher.tushare.query_builder import post_process_tushare_frame
from stock_data.fetcher.tushare.registry_meta import EndpointMeta


def _quarter_end(value: date) -> date:
    """返回给定日期所在自然季度的报告期末。"""
    month = ((value.month - 1) // 3 + 1) * 3
    return date(value.year, month, calendar.monthrange(value.year, month)[1])


def _next_quarter_end(value: date) -> date:
    """返回下一个自然季度的报告期末。"""
    if value.month >= 10:
        year, month = value.year + 1, 3
    else:
        year, month = value.year, value.month + 3
    return date(year, month, calendar.monthrange(year, month)[1])


def _report_periods(start_date: date, end_date: date) -> list[date]:
    """生成请求范围内的自然季度报告期末日期。"""
    periods: list[date] = []
    period = _quarter_end(start_date)
    while period <= end_date:
        periods.append(period)
        period = _next_quarter_end(period)
    return periods


def fetch_report_periods(
    client: TuShareClient,
    symbol: str,
    start_date: date,
    end_date: date,
    meta: EndpointMeta,
    extra_kwargs: dict[str, Any],
    max_workers: int = 1,
) -> pl.DataFrame:
    """按报告期末调用 VIP 全市场接口并合并结果。"""
    if symbol:
        logger.warning(
            "TuShare 财务 VIP 接口忽略传入 symbol=%s，始终按报告期拉取全市场数据",
            symbol,
        )

    query_kwargs = dict(extra_kwargs)
    for key in (
        "ts_code",
        "start_date",
        "end_date",
        "trade_date",
        "ann_date",
        "report_date",
        "period",
    ):
        query_kwargs.pop(key, None)

    periods = _report_periods(start_date, end_date)

    def query_period(period: date) -> Any:
        return client.query(meta.api_name, period=period.strftime("%Y%m%d"), **query_kwargs)

    worker_count = max(1, min(int(max_workers), 8))
    if worker_count > 1 and len(periods) > 1:
        logger.info(
            f"TuShare 财务报告期请求启用并发: 接口={meta.api_name}, "
            f"报告期={len(periods)}, Worker={worker_count}"
        )
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            responses = list(executor.map(query_period, periods))
    else:
        responses = [query_period(period) for period in periods]

    frames = [
        post_process_tushare_frame(pandas_df, meta, "")
        for pandas_df in responses
        if not pandas_df.empty
    ]
    if not frames:
        return pl.DataFrame()

    merged = pl.concat(frames, how="diagonal_relaxed")
    primary_keys = [key for key in meta.primary_keys if key in merged.columns]
    if primary_keys:
        merged = merged.unique(subset=primary_keys, keep="last")
    sort_columns = [column for column in ("end_date", "ts_code") if column in merged.columns]
    return merged.sort(sort_columns) if sort_columns else merged
