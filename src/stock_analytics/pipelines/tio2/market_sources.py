"""钛白粉全景对账管线市场侧数据读取（价差/二级行业行情/公司面板）。

Curated 事实一律通过 ``DataCatalog``（或鸭子类型测试替身）读取；读取失败时
返回空表或空字典，由合并层/渲染层容错。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import polars as pl

from stock_analytics.pipelines.tio2.sources import (
    _TIO2_SYMBOL,
    DatasetReader,
    _load_symbol_dataset,
    _pick_date_column,
)

logger = logging.getLogger(__name__)

_CHEM_RAW_MATERIAL_L2 = "220200"  # 申万二级：化学原料
_TIO2_L3_CODE = "850326.SI"  # 申万三级：钛白粉

# 月频产能利用率来源优先级（同月多源时：隆众 > Mysteel > SMM 开工率）
_MONTHLY_OP_SOURCE_PRIORITY = {"Longzhong": 0, "Mysteel": 1, "SMM": 2}


def load_spreads(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载钛白粉理论价差与毛利（月度均值 + 利润状态）。"""
    df = _load_symbol_dataset(catalog, dataset, _TIO2_SYMBOL)
    if df.is_empty():
        return pl.DataFrame()
    date_col = _pick_date_column(df, ("trade_date", "date", "report_date"))
    if date_col is None:
        return pl.DataFrame()
    return (
        df.with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("product_price_cny").cast(pl.Float64, strict=False),
            pl.col("spread_margin_cny").cast(pl.Float64, strict=False),
        )
        .group_by("report_month")
        .agg(
            [
                pl.col("product_price_cny").mean().alias("tio2_spread_price_cny"),
                pl.col("spread_margin_cny").mean().alias("tio2_margin_cny"),
                pl.col("margin_regime").last().alias("margin_regime"),
            ]
        )
        .sort("report_month")
    )


def load_industry_market(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载化学原料(220200)或钛白粉三级行业的月度行情与估值分位。"""
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return pl.DataFrame()
    if df.is_empty():
        return pl.DataFrame()

    code_col = next((c for c in ("industry_code", "code", "symbol") if c in df.columns), None)
    if code_col is None:
        return pl.DataFrame()

    filtered = df.filter(pl.col(code_col).is_in([_CHEM_RAW_MATERIAL_L2, _TIO2_L3_CODE]))
    if filtered.is_empty():
        return pl.DataFrame()

    date_col = _pick_date_column(filtered, ("trade_date", "date"))
    if date_col is None:
        return pl.DataFrame()

    return (
        filtered.with_columns(
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .group_by("report_month")
        .agg(
            [
                pl.col("close").last().alias("industry_close_month_end"),
                pl.col("pb_ew_percentile_10y").drop_nulls().last().alias("pb_pct_10y")
                if "pb_ew_percentile_10y" in filtered.columns
                else pl.lit(None).cast(pl.Float64).alias("pb_pct_10y"),
                pl.col("pe_ttm_ew_percentile_5y").drop_nulls().last().alias("pe_pct_5y")
                if "pe_ttm_ew_percentile_5y" in filtered.columns
                else pl.lit(None).cast(pl.Float64).alias("pe_pct_5y"),
            ]
        )
        .sort("report_month")
    )


def load_company_panel(
    catalog: DatasetReader,
    dataset: str,
    fallback_builder: Callable[[], pl.DataFrame] | None = None,
) -> pl.DataFrame:
    """加载钛白粉上市公司对账面板。"""
    try:
        df = catalog.load_dataset(dataset)
        if not df.is_empty():
            return df
    except Exception as exc:
        logger.debug("读取公司面板数据集失败: %s (%s)", dataset, exc)

    if fallback_builder is not None:
        try:
            return fallback_builder()
        except Exception as exc:
            logger.warning("动态构建钛白粉公司面板失败: %s", exc)

    return pl.DataFrame()


def load_weekly_survey(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载钛白粉周度开工率与厂库（月度聚合：月末开工率 + 截至月末连续去库周数）。"""
    df = _load_symbol_dataset(catalog, dataset, _TIO2_SYMBOL)
    if df.is_empty():
        return pl.DataFrame()
    date_col = _pick_date_column(df, ("trade_date", "date", "report_date"))
    if date_col is None:
        return pl.DataFrame()

    op_col = next((c for c in ("operating_rate_pct", "operating_rate") if c in df.columns), None)
    inv_col = next(
        (
            c
            for c in ("factory_inventory_w_tons", "factory_inventory", "inventory_w_tons")
            if c in df.columns
        ),
        None,
    )

    month_last: dict[str, dict[str, Any]] = {}
    prev_inv: float | None = None
    consec = 0
    for row in df.sort(date_col).iter_rows(named=True):
        month = str(row.get(date_col))[:7]
        inv_val = row.get(inv_col) if inv_col else None
        inv = float(str(inv_val)) if inv_val is not None else None
        if inv is not None and prev_inv is not None:
            consec = consec + 1 if inv < prev_inv else 0
        else:
            consec = 0
        if inv is not None:
            prev_inv = inv
        op_val = row.get(op_col) if op_col else None
        month_last[month] = {
            "operating_rate_pct": (float(str(op_val)) if op_val is not None else None),
            "consecutive_destock_weeks": consec,
        }

    return pl.DataFrame(
        [{"report_month": month, **values} for month, values in sorted(month_last.items())]
    )


def load_monthly_survey(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """加载钛白粉月频调研（月度产能利用率/厂库/产量，SMM + 隆众·Mysteel）。

    同月多源时按 :data:`_MONTHLY_OP_SOURCE_PRIORITY` 取产能利用率；
    厂库绝对值优先，环比增速兜底；并计算截至最新数据月的连续去库月数。
    输出列：report_month / operating_rate_pct_monthly / factory_inventory_w_tons_monthly /
    consecutive_destock_months / monthly_survey_as_of / monthly_survey_sources。
    """
    df = _load_symbol_dataset(catalog, dataset, _TIO2_SYMBOL)
    if df.is_empty() or "report_month" not in df.columns:
        return pl.DataFrame()

    by_month: dict[str, dict[str, Any]] = {}
    for r in df.iter_rows(named=True):
        month = str(r.get("report_month"))[:7]
        m = by_month.setdefault(
            month,
            {
                "report_month": month,
                "operating_rate_pct_monthly": None,
                "operating_rate_source": None,
                "operating_rate_priority": 99,
                "factory_inventory_w_tons_monthly": None,
                "inventory_mom_pct": None,
                "inventory_yoy_pct": None,
                "production_w_tons": None,
                "survey_sources": [],
            },
        )
        src = str(r.get("source") or "")
        if src and src not in m["survey_sources"]:
            m["survey_sources"].append(src)
        op = r.get("operating_rate_pct")
        if op is not None:
            priority = _MONTHLY_OP_SOURCE_PRIORITY.get(src, 99)
            if priority < m["operating_rate_priority"]:
                m["operating_rate_pct_monthly"] = float(op)
                m["operating_rate_source"] = src
                m["operating_rate_priority"] = priority
        inv = r.get("factory_inventory_w_tons")
        if inv is not None and m["factory_inventory_w_tons_monthly"] is None:
            m["factory_inventory_w_tons_monthly"] = float(inv)
        if m["inventory_mom_pct"] is None and r.get("inventory_mom_pct") is not None:
            m["inventory_mom_pct"] = float(r["inventory_mom_pct"])
        if m["inventory_yoy_pct"] is None and r.get("inventory_yoy_pct") is not None:
            m["inventory_yoy_pct"] = float(r["inventory_yoy_pct"])
        if m["production_w_tons"] is None and r.get("production_w_tons") is not None:
            m["production_w_tons"] = float(r["production_w_tons"])

    # 连续去库月数（有绝对库存时用绝对量比较，否则用环比符号）
    months = sorted(by_month)
    prev_level: float | None = None
    streak = 0
    latest_data_month: str | None = None
    for month in months:
        m = by_month[month]
        inv_abs = m["factory_inventory_w_tons_monthly"]
        inv_mom = m["inventory_mom_pct"]
        has_inv = inv_abs is not None or inv_mom is not None
        decline: bool | None = None
        if inv_abs is not None and prev_level is not None:
            decline = inv_abs < prev_level
        elif inv_mom is not None:
            decline = inv_mom < 0
        if decline is True:
            streak += 1
        elif decline is False:
            streak = 0
        else:
            streak = 0
        if inv_abs is not None:
            prev_level = inv_abs
        if has_inv:
            latest_data_month = month
        m["consecutive_destock_months"] = streak

    return pl.DataFrame(
        [
            {
                "report_month": month,
                "operating_rate_pct_monthly": by_month[month]["operating_rate_pct_monthly"],
                "factory_inventory_w_tons_monthly": by_month[month][
                    "factory_inventory_w_tons_monthly"
                ],
                "consecutive_destock_months": by_month[month]["consecutive_destock_months"],
                "monthly_survey_as_of": latest_data_month,
                "monthly_survey_sources": ";".join(by_month[month]["survey_sources"]),
            }
            for month in months
        ]
    ).sort("report_month")


def load_ma20_signal(catalog: DatasetReader, dataset: str) -> pl.DataFrame:
    """从申万二级化学原料(220200)日频行情计算月末 MA20 突破信号 (收盘价 > 20日均线)。"""
    try:
        df = catalog.load_dataset(dataset)
    except Exception:
        return pl.DataFrame()
    if df.is_empty():
        return pl.DataFrame()

    code_col = next((c for c in ("industry_code", "code", "symbol") if c in df.columns), None)
    date_col = _pick_date_column(df, ("trade_date", "date"))
    close_col = next((c for c in ("close", "close_price") if c in df.columns), None)
    if code_col is None or date_col is None or close_col is None:
        return pl.DataFrame()

    filtered = df.filter(pl.col(code_col).cast(pl.String) == _CHEM_RAW_MATERIAL_L2)
    if filtered.is_empty():
        return pl.DataFrame()

    daily = (
        filtered.sort(date_col)
        .with_columns(
            pl.col(close_col).cast(pl.Float64, strict=False).alias("_close_f"),
            pl.col(date_col).cast(pl.String).str.slice(0, 7).alias("report_month"),
        )
        .with_columns(
            pl.col("_close_f").rolling_mean(window_size=20, min_samples=10).alias("_ma20")
        )
        .filter(pl.col("_ma20").is_not_null())
        .with_columns(
            pl.when(pl.col("_close_f") > pl.col("_ma20"))
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("ma20_break")
        )
    )
    return (
        daily.group_by("report_month")
        .agg(pl.col("ma20_break").last().alias("ma20_break"))
        .sort("report_month")
    )
