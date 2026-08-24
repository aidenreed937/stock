"""宏观与跨资产类指标计算器。

将 :mod:`stock_analytics.primitives.macro` 中的宏观原语（国债期限利差、
巴菲特证券化率）封装为标准 :class:`MetricSpec`，接入指标注册表统一调度。
"""

from __future__ import annotations

from typing import Any

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
from stock_analytics.primitives.macro import (
    calculate_macro_spread,
    calculate_securitization_ratio,
    calculate_yield_curve_slope,
)

#: 市值单位换算：元 -> 亿元。
_YI_PER_YUAN: float = 1e8
#: GDP TTM 滚动季度数。
_GDP_TTM_QUARTERS: int = 4
#: 期限利差计算所需的国债收益率列。
_YIELD_CURVE_REQUIRED_COLUMNS = ("trade_date", "tcm_y2", "tcm_y10")
#: 全市场市值聚合所需的日线基础数据列。
_DAILY_BASIC_REQUIRED_COLUMNS = ("trade_date", "total_mv")
#: GDP TTM 推导所需的宏观数据列。
_GDP_REQUIRED_COLUMNS = ("quarter", "gdp")


def _yield_curve_frame(context: MetricContext) -> pl.DataFrame:
    """加载国债收益率曲线并计算期限利差列。"""
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "macro_yield_curve", end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    raw = load_metric_dataset(
        context,
        "national_debt",
        data_source="lixinger",
        columns=["trade_date", "tcm_y2", "tcm_y10", "tcm_y30"],
    )
    if raw.is_empty() or not set(_YIELD_CURVE_REQUIRED_COLUMNS).issubset(raw.columns):
        frame = pl.DataFrame()
    else:
        select_exprs: list[pl.Expr] = [
            pl.col("trade_date").cast(pl.Date),
            pl.col("tcm_y2").cast(pl.Float64, strict=False),
            pl.col("tcm_y10").cast(pl.Float64, strict=False),
        ]
        if "tcm_y30" in raw.columns:
            select_exprs.append(pl.col("tcm_y30").cast(pl.Float64, strict=False))
        base = raw.select(select_exprs).drop_nulls(subset=["tcm_y2", "tcm_y10"]).sort("trade_date")
        frame = calculate_yield_curve_slope(
            base,
            long_yield_col="tcm_y10",
            short_yield_col="tcm_y2",
        )
        if "tcm_y30" in frame.columns:
            frame = calculate_macro_spread(
                frame,
                higher_rate_col="tcm_y30",
                lower_rate_col="tcm_y10",
                spread_col_name="yield_curve_slope_30y_10y",
            )
    context.cache[cache_key] = frame
    return frame


def _market_cap_daily(daily_basic: pl.DataFrame) -> pl.DataFrame:
    """按交易日聚合全市场总市值（亿元）。"""
    return (
        daily_basic.select(
            pl.col("trade_date").cast(pl.Date),
            pl.col("total_mv").cast(pl.Float64, strict=False),
        )
        .drop_nulls(subset=["total_mv"])
        .filter(pl.col("total_mv") > 0)
        .group_by("trade_date")
        .agg((pl.col("total_mv").sum() / _YI_PER_YUAN).alias("total_market_cap_yi"))
        .sort("trade_date")
    )


def _gdp_ttm_frame(gdp: pl.DataFrame) -> pl.DataFrame:
    """由季度累计 GDP 推导滚动 4 季 GDP TTM，并锚定到季度末日期。

    tushare ``cn_gdp`` 的 ``gdp`` 为年初至今累计值（亿元）。本函数先还原单季
    值（Q1 即累计值，其余为当季累计减上季累计），再对连续 4 个季度求和得到
    GDP TTM，并以季度末日期作为该 TTM 的可用日期。
    """
    return (
        gdp.select(
            pl.col("quarter").cast(pl.Utf8),
            pl.col("gdp").cast(pl.Float64, strict=False),
        )
        .drop_nulls(subset=["gdp"])
        .filter(pl.col("gdp") > 0)
        .unique(subset=["quarter"])
        .sort("quarter")
        .with_columns(
            pl.col("quarter").str.extract(r"^(\d{4})Q([1-4])$", 1).cast(pl.Int32).alias("_year"),
            pl.col("quarter")
            .str.extract(r"^(\d{4})Q([1-4])$", 2)
            .cast(pl.Int32)
            .alias("_quarter_no"),
        )
        .with_columns(
            pl.when(pl.col("_quarter_no") == 1)
            .then(pl.col("gdp"))
            .otherwise(pl.col("gdp") - pl.col("gdp").shift(1).over("_year"))
            .alias("_quarterly_gdp")
        )
        .with_columns(
            pl.col("_quarterly_gdp")
            .rolling_sum(_GDP_TTM_QUARTERS, min_samples=_GDP_TTM_QUARTERS)
            .alias("gdp_ttm_yi")
        )
        .with_columns(
            pl.date(pl.col("_year"), pl.col("_quarter_no") * 3, 1)
            .dt.month_end()
            .alias("quarter_end")
        )
        .select(["quarter_end", "gdp_ttm_yi"])
        .drop_nulls()
    )


def _apply_securitization_ratio(row: Any) -> float | None:
    """按行调用证券化率原语，并透传缺失数据。"""
    if row is None:
        return None
    total_market_cap = row["total_market_cap_yi"]
    gdp_ttm = row["gdp_ttm_yi"]
    if total_market_cap is None or gdp_ttm is None:
        return None
    return calculate_securitization_ratio(total_market_cap, gdp_ttm)


def _buffett_frame(context: MetricContext) -> pl.DataFrame:
    """加载全市场市值与 GDP，计算巴菲特证券化率。"""
    start_date = context.start_date
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "macro_buffett", start_date, end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    daily_basic = load_metric_dataset(
        context,
        "daily_basic",
        columns=["trade_date", "total_mv"],
    )
    gdp = load_metric_dataset(
        context,
        "cn_gdp",
        columns=["quarter", "gdp"],
    )
    if (
        daily_basic.is_empty()
        or gdp.is_empty()
        or not set(_DAILY_BASIC_REQUIRED_COLUMNS).issubset(daily_basic.columns)
        or not set(_GDP_REQUIRED_COLUMNS).issubset(gdp.columns)
    ):
        frame = pl.DataFrame()
    else:
        frame = (
            _market_cap_daily(daily_basic)
            .join_asof(
                _gdp_ttm_frame(gdp),
                left_on="trade_date",
                right_on="quarter_end",
                strategy="backward",
            )
            .with_columns(
                pl.struct(["total_market_cap_yi", "gdp_ttm_yi"])
                .map_elements(_apply_securitization_ratio, return_dtype=pl.Float64)
                .alias("buffett_securitization_ratio")
            )
            .select(["trade_date", "buffett_securitization_ratio"])
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


def calculate_macro_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    """按指标 ID 调度宏观指标计算。"""
    frame = (
        _buffett_frame(context)
        if spec.metric_id == "buffett_securitization_ratio"
        else _yield_curve_frame(context)
    )
    if frame.is_empty():
        return _empty(spec.output_columns)
    if context.start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return _select_metric(frame, spec)


def _spec(metric_id: str, name: str, datasets: tuple[str, ...]) -> MetricSpec:
    """构造宏观指标定义。"""
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.MACRO,
        entity_type=EntityType.MARKET,
        required_datasets=datasets,
        output_columns=("trade_date", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec("yield_curve_slope_10y_2y", "中国国债10Y-2Y期限利差", ("national_debt",)),
    _spec("yield_curve_slope_30y_10y", "中国国债30Y-10Y期限利差", ("national_debt",)),
    _spec("buffett_securitization_ratio", "巴菲特证券化率", ("daily_basic", "cn_gdp")),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_macro_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
