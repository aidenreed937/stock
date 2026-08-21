"""理杏仁公司风险事件与限售解禁汇总抓取辅助函数。"""

from datetime import date
from typing import Any

import polars as pl

from stock_core.config.loader import load_data_config
from stock_core.exceptions import DataFetchError
from stock_data.core.task_registry import resolve_task
from stock_data.fetcher.lixinger import query_helpers
from stock_data.fetcher.lixinger.client import LixingerClient
from stock_data.fetcher.lixinger.registry import EndpointMeta

_UNLOCK_ENDPOINT = "cn/company/hot/elr"
RISK_ENDPOINTS = frozenset(
    {
        "cn/company/measures",
        "cn/company/inquiry",
        _UNLOCK_ENDPOINT,
    }
)


def _configured_lixinger_stock_codes() -> list[str]:
    """返回解禁汇总默认使用的 LiXinger 观察池代码。"""
    try:
        data_cfg = load_data_config()
        watchlist = getattr(data_cfg.watchlists, "lixinger", None)
    except Exception:
        return []
    if watchlist is None:
        return []
    stocks = list(getattr(watchlist, "stocks", []) or [])
    return stocks or list(getattr(watchlist, "all_symbols", []) or [])


def _is_generic_symbol(raw_code: str, endpoint: str, meta: EndpointMeta) -> bool:
    """判断传入字符串是否只是任务名/接口名，而非实际股票代码。"""
    if not raw_code or raw_code in {endpoint, meta.api_name}:
        return True
    try:
        return resolve_task("lixinger", raw_code).api_name == endpoint
    except ValueError:
        return False


def _fetch_batch_unlock_summary(
    client: LixingerClient,
    meta: EndpointMeta,
    symbols: list[str],
    query_kwargs: dict[str, Any],
) -> pl.DataFrame:
    """按限售解禁汇总接口的 100 代码上限批量查询。"""
    frames: list[pl.DataFrame] = []
    for index in range(0, len(symbols), 100):
        batch_kwargs = dict(query_kwargs)
        batch_kwargs["stockCodes"] = symbols[index : index + 100]
        frame = client.query(meta.api_name, **batch_kwargs)
        if not frame.empty:
            frame = query_helpers.ensure_pledge_date_column(meta.api_name, frame)
            frames.append(pl.from_pandas(frame))
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def _fetch_paginated_unlock_summary(
    client: LixingerClient,
    meta: EndpointMeta,
    query_kwargs: dict[str, Any],
) -> pl.DataFrame:
    """按解禁汇总接口的全市场排序分页模式查询。"""
    frames: list[pl.DataFrame] = []
    page_index = int(query_kwargs.get("pageIndex", 0))
    page_size = min(max(int(query_kwargs.get("pageSize", 100)), 1), 100)
    while True:
        page_kwargs = dict(query_kwargs)
        page_kwargs.update(
            {
                "sortName": page_kwargs.get("sortName", "srl_last"),
                "sortOrder": page_kwargs.get("sortOrder", "desc"),
                "pageIndex": page_index,
                "pageSize": page_size,
            }
        )
        frame = client.query(meta.api_name, **page_kwargs)
        if frame.empty:
            break
        frame = query_helpers.ensure_pledge_date_column(meta.api_name, frame)
        frames.append(pl.from_pandas(frame))
        if len(frame) < page_size:
            break
        page_index += 1
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def fetch_risk_endpoint(
    client: LixingerClient,
    endpoint: str,
    meta: EndpointMeta,
    symbol: str,
    start_date: date,
    end_date: date,
    kwargs: dict[str, Any],
) -> pl.DataFrame | None:
    """抓取已注册的公司风险接口；非风险接口返回 None。"""
    if endpoint not in RISK_ENDPOINTS:
        return None

    raw_code = symbol.split(".")[0] if symbol else ""
    query_kwargs: dict[str, Any] = {**meta.default_params, **kwargs}
    if meta.default_metrics:
        query_kwargs["metricsList"] = meta.default_metrics

    if endpoint == _UNLOCK_ENDPOINT:
        if not _is_generic_symbol(raw_code, endpoint, meta) and not query_kwargs.get("stockCodes"):
            query_kwargs["stockCodes"] = [raw_code]
        symbols = list(query_kwargs.pop("stockCodes", []) or [])
        if not symbols and not any(
            key in query_kwargs for key in ("pageIndex", "pageSize", "sortName", "sortOrder")
        ):
            symbols = _configured_lixinger_stock_codes()
        if symbols:
            return _fetch_batch_unlock_summary(client, meta, symbols, query_kwargs)
        if not any(
            key in query_kwargs for key in ("pageIndex", "pageSize", "sortName", "sortOrder")
        ):
            raise DataFetchError(
                "LiXinger 限售解禁汇总默认仅允许观察池；如需全市场分页，必须显式传入分页参数"
            )
        return _fetch_paginated_unlock_summary(client, meta, query_kwargs)

    start_str, end_str = query_helpers.query_date_strings(endpoint, start_date, end_date)
    query_kwargs.update({"startDate": start_str, "endDate": end_str})
    if _is_generic_symbol(raw_code, endpoint, meta):
        raise DataFetchError(f"LiXinger 风险接口 [{endpoint}] 必须显式传入股票代码")
    if meta.code_param_name == "stockCode":
        query_kwargs["stockCode"] = raw_code
    else:
        query_kwargs["stockCodes"] = [raw_code]

    frame = query_helpers.query_frame(
        client,
        meta.api_name,
        endpoint,
        query_kwargs,
        stock_code=raw_code,
    )
    return pl.from_pandas(frame) if not frame.empty else pl.DataFrame()
