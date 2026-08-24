"""期权与衍生品类指标计算器。

将全市场期权面板（``opt_daily`` + ``opt_basic``）的认沽/认购比（PCR）与
基于结算价反解的 Black-Scholes 隐含波动率代理（IV Proxy）封装为标准
:class:`MetricSpec`，归属新增的 :class:`MetricDomain.DERIVATIVES` 领域。
"""

from __future__ import annotations

import polars as pl

from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.datasets.loaders import load_metric_dataset
from stock_analytics.metrics.datasets.windows import empty_metric_frame as _empty
from stock_analytics.metrics.spec import (
    EntityType,
    MetricCalculator,
    MetricDomain,
    MetricSpec,
)
from stock_analytics.plugins.options import compute_fast_bs_iv

#: PCR 计算所需的期权行情列。
_PCR_DAILY_COLUMNS = ("symbol", "trade_date", "vol", "oi")
#: PCR 计算所需的期权合约属性列。
_PCR_BASIC_COLUMNS = ("symbol", "call_put")
#: IV 代理计算所需的期权行情列。
_IV_DAILY_COLUMNS = ("symbol", "trade_date", "settle")
#: IV 代理计算所需的期权合约属性列。
_IV_BASIC_COLUMNS = ("symbol", "call_put", "exercise_price", "maturity_date", "opt_code")
#: 无风险利率代理：SHIBOR 3 个月期限（报价为百分数，需除以 100 转为小数）。
_RISK_FREE_TENOR = "3m"


def _pcr_frame(context: MetricContext) -> pl.DataFrame:
    """计算全市场期权认沽/认购成交量比与持仓量比。"""
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "option_pcr", end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    daily = load_metric_dataset(context, "opt_daily", columns=["symbol", "trade_date", "vol", "oi"])
    basic = load_metric_dataset(
        context, "opt_basic", columns=["symbol", "call_put"], reference=True
    )
    if (
        daily.is_empty()
        or basic.is_empty()
        or not set(_PCR_DAILY_COLUMNS).issubset(daily.columns)
        or not set(_PCR_BASIC_COLUMNS).issubset(basic.columns)
    ):
        frame = pl.DataFrame()
    else:
        frame = (
            daily.join(basic, on="symbol", how="inner")
            .group_by(pl.col("trade_date").cast(pl.Date))
            .agg(
                pl.when(pl.col("call_put") == "P")
                .then(pl.col("vol"))
                .otherwise(0.0)
                .sum()
                .alias("_put_vol"),
                pl.when(pl.col("call_put") == "C")
                .then(pl.col("vol"))
                .otherwise(0.0)
                .sum()
                .alias("_call_vol"),
                pl.when(pl.col("call_put") == "P")
                .then(pl.col("oi"))
                .otherwise(0.0)
                .sum()
                .alias("_put_oi"),
                pl.when(pl.col("call_put") == "C")
                .then(pl.col("oi"))
                .otherwise(0.0)
                .sum()
                .alias("_call_oi"),
            )
            .with_columns(
                pl.when(pl.col("_call_vol") > 0)
                .then(pl.col("_put_vol") / pl.col("_call_vol"))
                .otherwise(None)
                .alias("option_put_call_volume_ratio"),
                pl.when(pl.col("_call_oi") > 0)
                .then(pl.col("_put_oi") / pl.col("_call_oi"))
                .otherwise(None)
                .alias("option_put_call_oi_ratio"),
            )
            .select(
                "trade_date",
                "option_put_call_volume_ratio",
                "option_put_call_oi_ratio",
            )
            .sort("trade_date")
        )
    context.cache[cache_key] = frame
    return frame


def _underlying_prices_frame(context: MetricContext) -> pl.DataFrame:
    """加载期权标的收盘价（ETF 期权用 ``fund_daily``，指数期权用 ``index_daily``）。"""
    frames: list[pl.DataFrame] = []
    for dataset in ("fund_daily", "index_daily"):
        frame = load_metric_dataset(context, dataset, columns=["symbol", "trade_date", "close"])
        if not frame.is_empty() and {"symbol", "trade_date", "close"}.issubset(frame.columns):
            frames.append(
                frame.select(
                    pl.col("symbol").cast(pl.String),
                    pl.col("trade_date").cast(pl.Date),
                    pl.col("close").cast(pl.Float64, strict=False),
                )
            )
    if not frames:
        return pl.DataFrame()
    return (
        pl.concat(frames)
        .drop_nulls(subset=["symbol", "trade_date", "close"])
        .unique(subset=["symbol", "trade_date"], keep="last")
    )


def _risk_free_frame(context: MetricContext) -> pl.DataFrame:
    """加载 SHIBOR 3 个月无风险利率代理（小数形式）。"""
    frame = load_metric_dataset(context, "shibor", columns=["trade_date", _RISK_FREE_TENOR])
    if frame.is_empty() or not {"trade_date", _RISK_FREE_TENOR}.issubset(frame.columns):
        return pl.DataFrame()
    return (
        frame.select(
            pl.col("trade_date").cast(pl.Date),
            pl.col(_RISK_FREE_TENOR).cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .with_columns((pl.col(_RISK_FREE_TENOR) / 100.0).alias("_risk_free_rate"))
        .select("trade_date", "_risk_free_rate")
        .unique(subset=["trade_date"], keep="last")
    )


def _iv_proxy_frame(context: MetricContext) -> pl.DataFrame:
    """计算全市场期权结算价隐含波动率代理。"""
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "option_iv_proxy", end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    daily = load_metric_dataset(context, "opt_daily", columns=["symbol", "trade_date", "settle"])
    basic = load_metric_dataset(
        context,
        "opt_basic",
        columns=["symbol", "call_put", "exercise_price", "maturity_date", "opt_code"],
        reference=True,
    )
    underlying = _underlying_prices_frame(context)
    risk_free = _risk_free_frame(context)
    if (
        daily.is_empty()
        or basic.is_empty()
        or underlying.is_empty()
        or not set(_IV_DAILY_COLUMNS).issubset(daily.columns)
        or not set(_IV_BASIC_COLUMNS).issubset(basic.columns)
    ):
        frame = pl.DataFrame()
    else:
        valid_underlyings = underlying["symbol"].unique().to_list()
        joined = (
            daily.join(basic, on="symbol", how="inner")
            .with_columns(
                pl.col("opt_code").str.replace(r"^OP", "").alias("_underlying_symbol"),
                pl.col("trade_date").cast(pl.Date),
                pl.col("maturity_date").cast(pl.Date),
                pl.col("settle").cast(pl.Float64, strict=False),
                pl.col("exercise_price").cast(pl.Float64, strict=False),
            )
            .filter(pl.col("_underlying_symbol").is_in(valid_underlyings))
            .join(
                underlying.rename({"symbol": "_underlying_symbol"}),
                on=["_underlying_symbol", "trade_date"],
                how="inner",
            )
            .join(risk_free, on="trade_date", how="left")
            .with_columns(
                pl.col("_risk_free_rate").fill_null(0.0),
                ((pl.col("maturity_date") - pl.col("trade_date")).dt.total_days() / 365.0).alias(
                    "_time_years"
                ),
            )
            .with_columns(
                compute_fast_bs_iv(
                    pl.col("settle"),
                    pl.col("close"),
                    pl.col("exercise_price"),
                    pl.col("_time_years"),
                    pl.col("_risk_free_rate"),
                    pl.col("call_put"),
                ).alias("_iv")
            )
            .filter(pl.col("_iv").is_not_null() & pl.col("_iv").is_finite())
        )
        if joined.is_empty():
            frame = pl.DataFrame()
        else:
            frame = (
                joined.group_by("trade_date")
                .agg(
                    pl.col("_iv").median().alias("option_settlement_iv_proxy_median"),
                    pl.when(pl.col("call_put") == "P")
                    .then(pl.col("_iv"))
                    .otherwise(None)
                    .median()
                    .alias("_put_iv"),
                    pl.when(pl.col("call_put") == "C")
                    .then(pl.col("_iv"))
                    .otherwise(None)
                    .median()
                    .alias("_call_iv"),
                )
                .with_columns(
                    (pl.col("_put_iv") - pl.col("_call_iv")).alias(
                        "option_settlement_iv_proxy_put_call_skew"
                    )
                )
                .select(
                    "trade_date",
                    "option_settlement_iv_proxy_median",
                    "option_settlement_iv_proxy_put_call_skew",
                )
                .sort("trade_date")
            )
    context.cache[cache_key] = frame
    return frame


def _select_metric(frame: pl.DataFrame, spec: MetricSpec) -> pl.DataFrame:
    """投影指标列，缺失时返回空 Schema 帧。"""
    return (
        frame.select(spec.output_columns)
        if not frame.is_empty() and set(spec.output_columns).issubset(frame.columns)
        else _empty(spec.output_columns)
    )


def calculate_derivatives_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    """按指标 ID 调度期权与衍生品指标计算。"""
    frame = (
        _pcr_frame(context)
        if spec.metric_id in ("option_put_call_volume_ratio", "option_put_call_oi_ratio")
        else _iv_proxy_frame(context)
    )
    if frame.is_empty():
        return _empty(spec.output_columns)
    if context.start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return _select_metric(frame, spec)


def _spec(metric_id: str, name: str, datasets: tuple[str, ...]) -> MetricSpec:
    """构造衍生品指标定义。"""
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.DERIVATIVES,
        entity_type=EntityType.MARKET,
        required_datasets=datasets,
        output_columns=("trade_date", metric_id),
    )


_IV_DATASETS = ("opt_daily", "opt_basic", "fund_daily", "index_daily", "shibor")

METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec(
        "option_put_call_volume_ratio",
        "全市场期权认沽/认购成交量比",
        ("opt_daily", "opt_basic"),
    ),
    _spec(
        "option_put_call_oi_ratio",
        "全市场期权认沽/认购持仓量比",
        ("opt_daily", "opt_basic"),
    ),
    _spec(
        "option_settlement_iv_proxy_median",
        "期权结算价隐含波动率代理（中位数）",
        _IV_DATASETS,
    ),
    _spec(
        "option_settlement_iv_proxy_put_call_skew",
        "期权结算价IV认沽认购偏度",
        _IV_DATASETS,
    ),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_derivatives_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
