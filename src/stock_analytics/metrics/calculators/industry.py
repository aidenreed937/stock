"""申万一级行业指标计算器。

将 :mod:`stock_data` 的 ``sw_daily``（申万行业日行情）中一级行业（SW2021/L1）
日频截面指标封装为标准 :class:`MetricSpec`，接入指标注册表统一调度。
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

#: 行业分类体系（申万 2021）。
_CLASSIFICATION = "SW2021"
#: 一级行业层级。
_INDUSTRY_LEVEL = "L1"
#: 全市场市值换算：元 -> 亿元。
_YI_PER_YUAN: float = 1e8
#: 一级行业截面必需的行情列。
_REQUIRED_COLUMNS = ("trade_date", "symbol", "classification", "industry_level")
#: 指标 ID 到 sw_daily 源列名的映射。
_METRIC_SOURCE_COLUMNS = {
    "sw_industry_pct_change": "pct_change",
    "sw_industry_amount_yi": "amount",
    "sw_industry_pe": "pe",
    "sw_industry_pb": "pb",
}
#: 指标 ID 到所属领域映射。
_METRIC_DOMAINS = {
    "sw_industry_pct_change": MetricDomain.PERFORMANCE,
    "sw_industry_amount_yi": MetricDomain.LIQUIDITY,
    "sw_industry_pe": MetricDomain.VALUATION,
    "sw_industry_pb": MetricDomain.VALUATION,
}


def _industry_l1_frame(context: MetricContext) -> pl.DataFrame:
    """加载申万一级行业日行情并投影为指标截面。"""
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "industry_l1", end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    raw = load_metric_dataset(
        context,
        "sw_daily",
        columns=[
            "trade_date",
            "symbol",
            "name",
            "classification",
            "industry_level",
            "pct_change",
            "amount",
            "pe",
            "pb",
        ],
    )
    if raw.is_empty() or not set(_REQUIRED_COLUMNS).issubset(raw.columns):
        frame = pl.DataFrame()
    else:
        select_exprs: list[pl.Expr] = [
            pl.col("trade_date").cast(pl.Date),
            pl.col("symbol").cast(pl.String).alias("industry_code"),
            pl.col("name").cast(pl.String, strict=False).alias("industry_name"),
        ]
        for source_column in ("pct_change", "amount", "pe", "pb"):
            if source_column in raw.columns:
                select_exprs.append(pl.col(source_column).cast(pl.Float64, strict=False))
            else:
                select_exprs.append(pl.lit(None, dtype=pl.Float64).alias(source_column))
        frame = (
            raw.filter(
                (pl.col("classification") == _CLASSIFICATION)
                & (pl.col("industry_level") == _INDUSTRY_LEVEL)
            )
            .select(select_exprs)
            .drop_nulls(subset=["industry_code", "trade_date"])
            .sort(["trade_date", "industry_code"])
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


def calculate_industry_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    """按指标 ID 调度申万一级行业指标计算。"""
    frame = _industry_l1_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    source_column = _METRIC_SOURCE_COLUMNS[spec.metric_id]
    if source_column not in frame.columns or frame[source_column].null_count() == frame.height:
        return _empty(spec.output_columns)
    metric_frame = frame
    if spec.metric_id == "sw_industry_amount_yi":
        metric_frame = frame.with_columns(
            (pl.col(source_column) / _YI_PER_YUAN).alias(spec.metric_id)
        )
    else:
        metric_frame = frame.rename({source_column: spec.metric_id})
    if context.start_date is not None:
        metric_frame = metric_frame.filter(pl.col("trade_date") >= context.start_date)
    return _select_metric(metric_frame, spec)


def _spec(metric_id: str, name: str, domain: MetricDomain) -> MetricSpec:
    """构造申万一级行业指标定义。"""
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=domain,
        entity_type=EntityType.INDUSTRY,
        required_datasets=("sw_daily",),
        output_columns=("trade_date", "industry_code", "industry_name", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec(
        "sw_industry_pct_change",
        "申万一级行业日涨跌幅（%）",
        MetricDomain.PERFORMANCE,
    ),
    _spec(
        "sw_industry_amount_yi",
        "申万一级行业成交额（亿元）",
        MetricDomain.LIQUIDITY,
    ),
    _spec("sw_industry_pe", "申万一级行业市盈率", MetricDomain.VALUATION),
    _spec("sw_industry_pb", "申万一级行业市净率", MetricDomain.VALUATION),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_industry_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
