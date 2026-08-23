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
