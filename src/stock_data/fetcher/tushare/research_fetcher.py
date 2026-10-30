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


def _quarter_ends(start_date: date, end_date: date) -> list[date]:
    """列出区间内（含端点）的自然季度末日期。"""
    ends: list[date] = []
    for year in range(start_date.year, end_date.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            quarter_end = date(year, month, day)
            if start_date <= quarter_end <= end_date:
                ends.append(quarter_end)
    return ends


def fetch_fund_portfolio_data(
    client: TuShareClient,
    symbol: str,
    start_date: date,
    end_date: date,
    meta: EndpointMeta,
    extra_kwargs: dict[str, Any],
) -> pl.DataFrame:
    """按基金代码采集持仓明细（季报前十大，半年报/年报全部持仓）。

    上游语义（2026-10 实测，Ground Truth First）：
    - 只接受 ``ts_code`` / ``ann_date`` / ``start_date`` / ``end_date``；
    - ``period`` 参数不存在，传入会被静默忽略并退化成「默认排序的前 8000 行」切片，
      这正是历史 Curated 每只基金每报告期只剩 1 条持仓的根因；
    - ``start_date`` / ``end_date`` 过滤的是公告日 ``ann_date``，不是报告期；
    - 单次返回上限 8000 行，需依赖 client 的 limit/offset 游标分页。

    因此：有基金代码时逐只查询（一次取回该基金全部历史），无代码时按季度末的公告
    窗口批量拉取全市场，绝不回退到 ``period`` 查询。
    """
    is_real_symbol = bool(symbol and symbol != meta.api_name)
    base_kwargs = dict(extra_kwargs)
    if meta.request_fields:
        base_kwargs.setdefault("fields", meta.request_fields)

    if is_real_symbol:
        query_kwargs = dict(base_kwargs)
        query_kwargs["ts_code"] = symbol
        query_kwargs["start_date"] = start_date.strftime("%Y%m%d")
        query_kwargs["end_date"] = end_date.strftime("%Y%m%d")
        frame = client.query(
            "fund_portfolio",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(frame, meta, symbol)

    # 无基金代码：按季度末公告窗口批量拉全市场。窗口固定为季度末起 75 天，
    # 覆盖法定披露期（季报 15 个工作日、年报/半年报 2~3 个月），不随回填区间收窄，
    # 否则单季度回填（start==end）会把窗口压成一个公告日而漏数。
    frames: list[pd.DataFrame] = []
    for quarter_end in _quarter_ends(start_date, end_date):
        query_kwargs = dict(base_kwargs)
        query_kwargs["start_date"] = quarter_end.strftime("%Y%m%d")
        window_end = date.fromordinal(quarter_end.toordinal() + 75)
        query_kwargs["end_date"] = window_end.strftime("%Y%m%d")
        frame = client.query(
            "fund_portfolio",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pl.DataFrame()
    return post_process_tushare_frame(pd.concat(frames, ignore_index=True), meta, symbol)


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
                # TuShare 的 stk_holdernumber 使用 enddate 表示报告截止期；
                # end_date 是公告日期范围的结束日，不能用于季度报告期查询。
                query_kwargs.pop("end_date", None)
                query_kwargs["enddate"] = start_date.strftime("%Y%m%d")
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
        query_kwargs["enddate"] = start_date.strftime("%Y%m%d")
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
            enddate=p.strftime("%Y%m%d"),
            pagination_limit=meta.max_rows_per_request,
            **base_kwargs,
        )
        if not pdf.empty:
            frames.append(pdf)
    if not frames:
        return pl.DataFrame()
    return post_process_tushare_frame(pd.concat(frames, ignore_index=True), meta, symbol)


def fetch_hk_hold_data(
    client: TuShareClient,
    symbol: str,
    start_date: date,
    end_date: date,
    meta: EndpointMeta,
    extra_kwargs: dict[str, Any],
) -> pl.DataFrame:
    """拉取沪深港通持股明细（A股北向 + 港股南向）。

    当按日拉取全市场时，自动遍历沪股通(1)、深股通(2)、港股通(3,4)并合并结果。
    """
    is_real_symbol = bool(symbol and symbol != meta.api_name)
    query_kwargs = dict(extra_kwargs)
    if is_real_symbol:
        query_kwargs["ts_code"] = symbol

    if is_real_symbol or "k_type" in query_kwargs or "code" in query_kwargs:
        if start_date == end_date:
            query_kwargs.setdefault("trade_date", start_date.strftime("%Y%m%d"))
        else:
            query_kwargs.setdefault("start_date", start_date.strftime("%Y%m%d"))
            query_kwargs.setdefault("end_date", end_date.strftime("%Y%m%d"))
        if meta.request_fields:
            query_kwargs.setdefault("fields", meta.request_fields)
        pdf = client.query(
            "hk_hold",
            pagination_limit=meta.max_rows_per_request,
            **query_kwargs,
        )
        return post_process_tushare_frame(pdf, meta, symbol)

    date_str = start_date.strftime("%Y%m%d")
    frames: list[pd.DataFrame] = []
    # k_type: 1=沪股通(北向), 2=深股通(北向), 3=港股通沪, 4=港股通深
    for kt in ["1", "2", "3", "4"]:
        req = dict(query_kwargs)
        req["k_type"] = kt
        if start_date == end_date:
            req["trade_date"] = date_str
        else:
            req["start_date"] = start_date.strftime("%Y%m%d")
            req["end_date"] = end_date.strftime("%Y%m%d")
        if meta.request_fields:
            req.setdefault("fields", meta.request_fields)
        pdf = client.query(
            "hk_hold",
            pagination_limit=meta.max_rows_per_request,
            **req,
        )
        if not pdf.empty:
            frames.append(pdf)

    if not frames:
        return pl.DataFrame()
    raw_df = post_process_tushare_frame(pd.concat(frames, ignore_index=True), meta, symbol)
    if not raw_df.is_empty():
        if "code" in raw_df.columns and "ts_code" not in raw_df.columns:
            raw_df = raw_df.rename({"code": "ts_code"})
        elif "code" in raw_df.columns and "ts_code" in raw_df.columns:
            raw_df = raw_df.with_columns(pl.coalesce(["ts_code", "code"]).alias("ts_code")).drop(
                "code"
            )
    return raw_df
