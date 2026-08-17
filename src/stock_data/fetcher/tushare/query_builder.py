"""TuShare 查询参数构建器与后处理器模块。"""

from datetime import date
from typing import Any

import pandas as pd
import polars as pl

from stock_data.fetcher.tushare.registry_meta import EndpointMeta

TUSHARE_INDEX_DAILYBASIC_SUPPORTED_CODES = {
    "000001.SH",
    "399001.SZ",
    "000300.SH",
    "000905.SH",
    "399006.SZ",
}


def is_index_dailybasic_supported(endpoint: str, symbol: str) -> bool:
    """检查指数代码是否受 index_dailybasic 接口支持。"""
    if (
        endpoint == "index_dailybasic"
        and symbol
        and symbol not in TUSHARE_INDEX_DAILYBASIC_SUPPORTED_CODES
    ):
        return False
    return True


def should_split_margin_exchanges(endpoint: str, extra_kwargs: dict[str, Any]) -> bool:
    """判断两融接口是否需要自动按各交易所拆分。"""
    return endpoint == "margin" and "exchange_id" not in extra_kwargs


def build_tushare_query(
    meta: EndpointMeta,
    symbol: str,
    start_date: date,
    end_date: date,
    extra_kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """构建 TuShare 调用的最终 API 名称与入参字典。"""
    endpoint = meta.api_name
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    is_real_symbol = bool(symbol and (symbol != endpoint))
    query_kwargs: dict[str, Any] = dict(extra_kwargs)
    index_code_endpoints = {"index_weight", "index_classify", "index_member"}
    symbol_param = "index_code" if endpoint in index_code_endpoints else "ts_code"

    if endpoint == "trade_cal":
        query_kwargs.setdefault("exchange", "")
        query_kwargs["start_date"] = start_str
        query_kwargs["end_date"] = end_str
        return endpoint, query_kwargs

    if endpoint == "stk_account":
        if start_date == end_date:
            query_kwargs["date"] = start_str
        else:
            query_kwargs["start_date"] = start_str
            query_kwargs["end_date"] = end_str
        return endpoint, query_kwargs

    if meta.frequency in ("event", "static"):
        if is_real_symbol:
            query_kwargs[symbol_param] = symbol
        if endpoint == "stock_basic" and not is_real_symbol:
            query_kwargs["list_status"] = "L"
    elif is_real_symbol:
        query_kwargs[symbol_param] = symbol
        query_kwargs["start_date"], query_kwargs["end_date"] = start_str, end_str
    elif start_date == end_date:
        if endpoint in ("forecast", "express"):
            query_kwargs["ann_date"] = start_str
        elif endpoint == "report_rc":
            query_kwargs["report_date"] = start_str
        else:
            query_kwargs["trade_date"] = start_str
    else:
        query_kwargs["start_date"] = start_str
        query_kwargs["end_date"] = end_str

    api_to_call = (
        f"{meta.api_name}_vip"
        if meta.api_name in ("forecast", "express") and not is_real_symbol
        else meta.api_name
    )
    return api_to_call, query_kwargs


def post_process_tushare_frame(
    pandas_df: pd.DataFrame,
    meta: EndpointMeta,
    symbol: str,
) -> pl.DataFrame:
    """将 TuShare 响应转换为 Polars，并按接口契约处理实体列与主键。"""
    if pandas_df.empty:
        return pl.DataFrame()

    pl_df = pl.from_pandas(pandas_df)
    is_real_symbol = bool(symbol and (symbol != meta.api_name))
    if meta.api_name == "margin":
        # margin 是交易所汇总表，symbol 不是上游字段，也不能由任务名补写。
        if "symbol" in pl_df.columns:
            pl_df = pl_df.drop("symbol")
    elif "symbol" not in pl_df.columns and is_real_symbol:
        pl_df = pl_df.with_columns(pl.lit(symbol).alias("symbol"))

    primary_keys = [key for key in meta.primary_keys if key in pl_df.columns]
    if primary_keys:
        pl_df = pl_df.unique(subset=primary_keys, keep="last")
    return pl_df
