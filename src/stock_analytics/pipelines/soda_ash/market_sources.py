"""纯碱全景对账管线市场侧数据读取（价差/龙虎榜/期货/现货基差/公司面板）。

Curated 事实一律通过 ``DataCatalog``（或鸭子类型测试替身）读取；读取失败时
返回空表或空字典，由合并层/渲染层容错。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

import polars as pl

from stock_analytics.pipelines.soda_ash.sources import (
    _CZCE_SYMBOL,
    DatasetReader,
    _load_symbol_dataset,
    _pick_date_column,
)

logger = logging.getLogger(__name__)


def load_spreads(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载纯碱价差与双吨理论利润（月度均值 + 最新利润状态）。"""
    df = _load_symbol_dataset(catalog, dataset, _CZCE_SYMBOL)
    if df.is_empty():
        return pl.DataFrame()
    date_col = _pick_date_column(df, ("trade_date", "date", "report_date"))
    if date_col is None:
        return pl.DataFrame()
    return (
        df.with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("product_price_cny").cast(pl.Float64, strict=False),
            pl.col("byproduct_price_cny").cast(pl.Float64, strict=False),
            pl.col("spread_margin_cny").cast(pl.Float64, strict=False),
        )
        .sort(date_col)
        .group_by("report_month", maintain_order=True)
        .agg(
            [
                pl.col("product_price_cny").mean().alias("soda_spot_price_cny"),
                pl.col("byproduct_price_cny").mean().alias("nh4cl_spot_price_cny"),
                pl.col("spread_margin_cny").mean().alias("double_ton_margin_cny"),
                pl.col("margin_regime").last().alias("margin_regime"),
            ]
        )
        .sort("report_month")
    )


def load_hold_rank(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载纯碱期货主力龙虎榜席位博弈特征。"""
    df = _load_symbol_dataset(catalog, dataset, _CZCE_SYMBOL)
    if df.is_empty():
        return pl.DataFrame()
    date_col = _pick_date_column(df, ("trade_date", "date", "report_date"))
    if date_col is None or "top20_net_long_vol" not in df.columns:
        return pl.DataFrame()
    return (
        df.with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("top20_net_long_vol").cast(pl.Float64, strict=False),
        )
        .sort(date_col)
        .group_by("report_month", maintain_order=True)
        .agg(
            [
                pl.col("top20_net_long_vol").last().alias("top20_net_long_vol"),
                pl.col("smart_money_bias").last().alias("smart_money_bias"),
            ]
        )
        .sort("report_month")
    )


def load_futures_daily(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载纯碱期货主力连续月度行情与结算价。"""
    df = _load_symbol_dataset(catalog, dataset, _CZCE_SYMBOL)
    if df.is_empty():
        return pl.DataFrame()
    date_col = _pick_date_column(df, ("trade_date", "date", "report_date"))
    if date_col is None or "settle" not in df.columns:
        return pl.DataFrame()
    return (
        df.with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("settle").cast(pl.Float64, strict=False),
        )
        .sort(date_col)
        .group_by("report_month", maintain_order=True)
        .agg(
            [
                pl.col("settle").drop_nulls().last().alias("futures_settle_month_end"),
                pl.col("settle").drop_nulls().mean().alias("futures_settle_avg"),
            ]
        )
        .sort("report_month")
    )


def load_spot_benchmark(
    catalog: DatasetReader,
    spot_dataset: str,
    futures_dataset: str,
) -> dict[str, Any]:
    """加载 100ppi 现货出厂基准与最新期货主力基差指标。"""
    result: dict[str, Any] = {}
    try:
        spot_df = catalog.load_dataset(spot_dataset)
    except Exception:
        return result
    if spot_df.is_empty():
        return result

    for sym, key in (
        ("SA", "sa_heavy_price"),
        ("SA_light", "sa_light_price"),
        ("UR", "ur_price"),
        ("ZC", "zc_price"),
        ("FG", "fg_price"),
        ("SH", "sh_price"),
    ):
        try:
            sub = spot_df.filter(pl.col("symbol") == sym).sort("trade_date")
        except Exception:
            continue
        if sub.is_empty():
            continue
        try:
            result[key] = float(sub["spot_price_cny"].to_list()[-1])
            result[f"{key}_date"] = str(sub["trade_date"].to_list()[-1])
        except (IndexError, TypeError, ValueError):
            continue

    try:
        fut_df = catalog.load_dataset(futures_dataset)
        fut_df = fut_df.filter(pl.col("symbol") == _CZCE_SYMBOL).sort("trade_date")
        if not fut_df.is_empty():
            result["futures_sa0_settle"] = float(fut_df["settle"].to_list()[-1])
            result["futures_sa0_date"] = str(fut_df["trade_date"].to_list()[-1])
            sa_heavy = result.get("sa_heavy_price")
            sa_fut = result.get("futures_sa0_settle")
            if sa_heavy is not None and sa_fut:
                basis = round(float(sa_heavy) - float(sa_fut), 2)
                result["basis_cny"] = basis
                result["basis_rate_pct"] = round(basis / float(sa_fut) * 100, 2)
    except Exception:
        logger.debug("读取期货主力结算价失败", exc_info=True)
    return result


def load_company_panel(
    catalog: DatasetReader,
    dataset: str,
    tushare_factory: Callable[[], DatasetReader] | None = None,
) -> pl.DataFrame:
    """加载纯碱上市公司日频行情、估值反向时钟与财报对账面板。

    优先读取已物化 Mart；缺失时可回退调用领域 Mart 构建函数（默认关闭，
    由管线显式开启，避免测试与离线场景触发重计算）。
    """
    try:
        df = catalog.load_dataset(dataset)
        if not df.is_empty():
            return df
    except Exception:
        logger.debug("读取纯碱公司面板 Mart 失败，尝试回退构建", exc_info=True)

    if tushare_factory is None:
        return pl.DataFrame()
    try:
        from stock_analytics.marts.soda_ash_company_panel import (
            build_soda_ash_company_panel,
        )

        return build_soda_ash_company_panel(catalog=cast("Any", tushare_factory()))
    except Exception:
        logger.debug("回退构建纯碱公司面板失败", exc_info=True)
        return pl.DataFrame()


__all__ = [
    "load_company_panel",
    "load_futures_daily",
    "load_hold_rank",
    "load_spot_benchmark",
    "load_spreads",
]
