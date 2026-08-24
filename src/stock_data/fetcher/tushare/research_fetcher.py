"""TuShare 研究型接口的专用抓取逻辑。"""

from datetime import date
from typing import Any

import pandas as pd
import polars as pl

from stock_data.fetcher.tushare.client import TuShareClient
from stock_data.fetcher.tushare.query_builder import post_process_tushare_frame
from stock_data.fetcher.tushare.registry_meta import EndpointMeta


def fetch_dividend_data(
    client: TuShareClient,
    symbol: str,
    start_date: date,
    end_date: date,
    meta: EndpointMeta,
    extra_kwargs: dict[str, Any],
) -> pl.DataFrame:
    """按首次全历史、单日公告日期过滤两种模式采集分红数据。"""
    is_real_symbol = bool(symbol and symbol != meta.api_name)
    query_kwargs = dict(extra_kwargs)
    if is_real_symbol:
        query_kwargs["ts_code"] = symbol
    date_filters = ("ann_date", "record_date", "ex_date", "imp_ann_date")
    has_explicit_filter = any(key in query_kwargs for key in date_filters)
    if not is_real_symbol and not has_explicit_filter:
        raise ValueError("TuShare dividend 查询需要 ts_code 或日期过滤条件")

    query_kwargs.setdefault("fields", meta.request_fields)
    requests: list[dict[str, Any]]
    if has_explicit_filter or not is_real_symbol:
        requests = [query_kwargs]
    elif start_date == end_date:
        date_str = start_date.strftime("%Y%m%d")
        requests = []
        for incremental_filter in ("ann_date", "imp_ann_date"):
            request = dict(query_kwargs)
            request[incremental_filter] = date_str
            requests.append(request)
    else:
        requests = [query_kwargs]

    frames: list[pd.DataFrame] = []
    for request in requests:
        frame = client.query(
            "dividend",
            pagination_limit=meta.max_rows_per_request,
            **request,
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pl.DataFrame()
    return post_process_tushare_frame(pd.concat(frames, ignore_index=True), meta, symbol)


def _is_quarter_end(d: date) -> bool:
    return (d.month, d.day) in {(3, 31), (6, 30), (9, 30), (12, 31)}


def fetch_top10_floatholders_data(
    client: TuShareClient,
    symbol: str,
    start_date: date,
    end_date: date,
    meta: EndpointMeta,
    extra_kwargs: dict[str, Any],
    max_workers: int = 1,
) -> pl.DataFrame:
    """按全市场报告期（回填）或单日公告日期（增量）采集十大流通股东。"""
    is_real_symbol = bool(symbol and symbol != meta.api_name)
    query_kwargs = dict(extra_kwargs)
    if meta.request_fields:
        query_kwargs.setdefault("fields", meta.request_fields)

    # 1. 指定单一股票代码查询
    if is_real_symbol:
        query_kwargs["ts_code"] = symbol
        if start_date == end_date:
            if _is_quarter_end(start_date):
                query_kwargs["period"] = start_date.strftime("%Y%m%d")
            else:
                query_kwargs["ann_date"] = start_date.strftime("%Y%m%d")
        else:
            query_kwargs["start_date"] = start_date.strftime("%Y%m%d")
            query_kwargs["end_date"] = end_date.strftime("%Y%m%d")
        pdf = client.query(
            "top10_floatholders",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(pdf, meta, symbol)

    # 2. 全市场查询：单日非季度末（日常增量 sync）或显式指定 ann_date
    if "ann_date" in query_kwargs or (start_date == end_date and not _is_quarter_end(start_date)):
        if "ann_date" not in query_kwargs:
            query_kwargs["ann_date"] = start_date.strftime("%Y%m%d")
        for key in ("ts_code", "start_date", "end_date", "trade_date", "report_date", "period"):
            query_kwargs.pop(key, None)
        pdf = client.query(
            "top10_floatholders",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(pdf, meta, symbol)

    # 3. 全市场查询：单季度报告期末
    if start_date == end_date and _is_quarter_end(start_date):
        for key in ("ts_code", "start_date", "end_date", "trade_date", "ann_date", "report_date"):
            query_kwargs.pop(key, None)
        query_kwargs["period"] = start_date.strftime("%Y%m%d")
        pdf = client.query(
            "top10_floatholders",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(pdf, meta, symbol)

    # 4. 全市场历史区间回填（调用 fetch_report_periods 按报告期批量并发）
    from stock_data.fetcher.tushare.financial_fetcher import fetch_report_periods

    return fetch_report_periods(
        client, symbol, start_date, end_date, meta, extra_kwargs, max_workers
    )


def fetch_stk_holdernumber_data(
    client: TuShareClient,
    symbol: str,
    start_date: date,
    end_date: date,
    meta: EndpointMeta,
    extra_kwargs: dict[str, Any],
    max_workers: int = 1,
) -> pl.DataFrame:
    """按全市场报告期（回填）或单日公告日期（增量）采集股东户数。"""
    is_real_symbol = bool(symbol and symbol != meta.api_name)
    query_kwargs = dict(extra_kwargs)
    if meta.request_fields:
        query_kwargs.setdefault("fields", meta.request_fields)

    # 1. 指定单一股票代码查询
    if is_real_symbol:
        query_kwargs["ts_code"] = symbol
        if start_date == end_date:
            if _is_quarter_end(start_date):
                query_kwargs["end_date"] = start_date.strftime("%Y%m%d")
            else:
                query_kwargs["ann_date"] = start_date.strftime("%Y%m%d")
        else:
            query_kwargs["start_date"] = start_date.strftime("%Y%m%d")
            query_kwargs["end_date"] = end_date.strftime("%Y%m%d")
        pdf = client.query(
            "stk_holdernumber",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(pdf, meta, symbol)

    # 2. 全市场查询：单日非季度末（日常增量 sync）或显式指定 ann_date
    if "ann_date" in query_kwargs or (start_date == end_date and not _is_quarter_end(start_date)):
        if "ann_date" not in query_kwargs:
            query_kwargs["ann_date"] = start_date.strftime("%Y%m%d")
        for key in ("ts_code", "start_date", "end_date", "trade_date", "report_date", "period"):
            query_kwargs.pop(key, None)
        pdf = client.query(
            "stk_holdernumber",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(pdf, meta, symbol)

    # 3. 全市场查询：单季度报告期末
    if start_date == end_date and _is_quarter_end(start_date):
        for key in ("ts_code", "start_date", "trade_date", "ann_date", "report_date", "period"):
            query_kwargs.pop(key, None)
        query_kwargs["end_date"] = start_date.strftime("%Y%m%d")
        pdf = client.query(
            "stk_holdernumber",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(pdf, meta, symbol)

    # 4. 全市场历史区间回填（按季度末报告期批量拉取）
    from stock_data.fetcher.tushare.financial_fetcher import _report_periods

    periods = _report_periods(start_date, end_date)
    frames: list[pd.DataFrame] = []
    base_kwargs = {
        k: v for k, v in query_kwargs.items() if k not in ("start_date", "end_date", "ann_date")
    }
    for p in periods:
        pdf = client.query(
            "stk_holdernumber",
            end_date=p.strftime("%Y%m%d"),
            pagination_limit=meta.max_rows_per_request,
            **base_kwargs,
        )
        if not pdf.empty:
            frames.append(pdf)
    if not frames:
        return pl.DataFrame()
    return post_process_tushare_frame(pd.concat(frames, ignore_index=True), meta, symbol)
