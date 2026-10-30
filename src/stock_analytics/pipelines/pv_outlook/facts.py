"""光伏景气前瞻仪表盘：事实加载、价差计算与数据缺口矩阵。

Ground Truth First：全部读数来自本地 Curated（``DataCatalog(data_source="industry")``），
数据集对应源端（InfoLink/能源局/硅业分会/NBS/海关）在缺口矩阵中明示；
本地缺失的数据如实标记为缺口，不补造。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock_analytics.pipelines.pv_outlook.config import PvOutlookConfig
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

_MONTHLY_DATASETS = (
    "solar_capacity",
    "polysilicon_inventory_monthly",
    "polysilicon_supply_monthly",
    "polysilicon_balance",
    "solar_supply_demand",
    "solar_cell_production",
    "customs_trade_gacc",
)


def load_price_chain(runtime: DataRuntimeContext, config: PvOutlookConfig) -> pl.DataFrame:
    """读取周度价格链并按报告日期升序，返回含环节毛利空间的 DataFrame。

    简化口径（趋势跟踪用，非绝对盈利测算）：
    - 组件毛利空间 = 组件价 - 电池片价 (元/W)
    - 电池片毛利空间 = 电池片价 - 硅片价/每片瓦数
    - 硅片毛利空间(粗) = 硅片价/每片瓦数 - 硅料价*每瓦硅耗/1000
    """
    catalog = DataCatalog(data_source="industry", runtime=runtime)
    df = catalog.load_dataset("solar_price_chain")
    if df.is_empty():
        return df
    df = df.sort("report_date")
    spread = config.spread
    df = df.with_columns(
        [
            (pl.col("module_price_cny_watt") - pl.col("cell_price_cny_watt")).alias(
                "spread_module_cny_watt"
            ),
            (
                pl.col("cell_price_cny_watt")
                - pl.col("wafer_price_cny_piece") / spread.wafers_per_piece
            ).alias("spread_cell_cny_watt"),
            (
                pl.col("wafer_price_cny_piece") / spread.wafers_per_piece
                - pl.col("polysilicon_price_cny_kg") * spread.polysilicon_per_watt_g / 1000.0
            ).alias("spread_wafer_cny_watt"),
        ]
    )
    if "module_price_cny_watt" in df.columns:
        mom_expr = (
            pl.when(
                pl.col("module_price_cny_watt").is_not_null()
                & (pl.col("module_price_cny_watt").shift(1) > 0)
            )
            .then(
                (
                    pl.col("module_price_cny_watt") / pl.col("module_price_cny_watt").shift(1) - 1.0
                ).round(4)
            )
            .otherwise(None)
        )
        yoy_expr = (
            pl.when(
                pl.col("module_price_cny_watt").is_not_null()
                & (pl.col("module_price_cny_watt").shift(52) > 0)
            )
            .then(
                (
                    pl.col("module_price_cny_watt") / pl.col("module_price_cny_watt").shift(52)
                    - 1.0
                ).round(4)
            )
            .otherwise(None)
        )
        if "module_price_mom" not in df.columns:
            df = df.with_columns(mom_expr.alias("module_price_mom"))
        else:
            df = df.with_columns(
                pl.coalesce([pl.col("module_price_mom"), mom_expr]).alias("module_price_mom")
            )
        if "module_price_yoy" not in df.columns:
            df = df.with_columns(yoy_expr.alias("module_price_yoy"))
        else:
            df = df.with_columns(
                pl.coalesce([pl.col("module_price_yoy"), yoy_expr]).alias("module_price_yoy")
            )
    return df


def load_monthly_watermarks(
    runtime: DataRuntimeContext, config: PvOutlookConfig
) -> dict[str, dict[str, Any]]:
    """读取各月度数据集的最新水位（最新报告月、最新报告期日期、行数）。

    研究口径只消费 GACC 官方数据：海关出口表先按 source=GACC 过滤，再按光伏产品行过滤，
    避免非光伏/非 GACC 行污染水位；缺失时保留为事实缺口，不回退到其他来源。
    """
    catalog = DataCatalog(data_source="industry", runtime=runtime)
    watermarks: dict[str, dict[str, Any]] = {}
    for dataset in _MONTHLY_DATASETS:
        try:
            df = catalog.load_dataset(dataset)
            if dataset == "customs_trade_gacc":
                if "source" in df.columns:
                    df = df.filter(pl.col("source") == "GACC")
                conds = []
                if "product_key" in df.columns:
                    conds.append(
                        pl.col("product_key").is_in(["solar_cell", "solar"])
                        | pl.col("product_key").str.contains("solar", literal=True)
                    )
                if "product_name" in df.columns:
                    conds.append(pl.col("product_name").str.contains("光伏|太阳能"))
                if conds:
                    active_cond = conds[0]
                    for c in conds[1:]:
                        active_cond = active_cond | c
                    df = df.filter(active_cond)
            if df.is_empty():
                watermarks[dataset] = {"latest_period": None, "latest_date": None, "rows": 0}
                continue
            period_col = "report_month" if "report_month" in df.columns else "trade_date"
            latest = df[period_col].max()
            latest_date = df["trade_date"].max() if "trade_date" in df.columns else None
            watermarks[dataset] = {
                "latest_period": str(latest),
                "latest_date": latest_date,
                "rows": len(df),
            }
        except Exception as exc:  # noqa: BLE001 - 缺口即事实，加载失败记 missing
            logger.warning("数据集 %s 加载失败: %s", dataset, exc)
            watermarks[dataset] = {"latest_period": None, "latest_date": None, "rows": 0}
    return watermarks


def _expected_month(as_of: date, release_lag_days: int) -> str:
    """按发布滞后推算数据应覆盖到的最新月份 (YYYY-MM)。"""
    anchor = as_of - timedelta(days=release_lag_days)
    return f"{anchor.year:04d}-{anchor.month:02d}"


def _month_diff(latest_period: str | None, expected: str) -> int:
    """latest_period (YYYY-MM) 落后 expected 的月数；无法解析或缺失时返回 None。"""
    if not latest_period or latest_period == "None":
        return 999
    try:
        ly, lm = (int(x) for x in latest_period.split("-")[:2])
        ey, em = (int(x) for x in expected.split("-")[:2])
    except (ValueError, TypeError):
        return 999
    return (ey - ly) * 12 + (em - lm)


def build_gap_matrix(
    runtime: DataRuntimeContext,
    config: PvOutlookConfig,
    as_of: date,
    price_chain: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """构建数据缺口矩阵：每个跟踪数据集的来源、节奏、最新水位与缺口状态。

    status: ok=数据在发布滞后窗口内 / lagging=滞后超窗 / missing=本地缺失。
    缺口如实明示，供后续补充采集。
    """
    price_chain = price_chain if price_chain is not None else load_price_chain(runtime, config)
    monthly = load_monthly_watermarks(runtime, config)

    rows: list[dict[str, Any]] = []
    for spec in config.datasets:
        if spec.cadence == "weekly":
            if price_chain.is_empty():
                latest_period, lag_note = None, "本地缺失"
            else:
                latest_scalar = price_chain["report_date"].max()
                latest_date = latest_scalar if isinstance(latest_scalar, date) else None
                if latest_date is None:
                    latest_period, lag_note = None, "报告期不可解析"
                else:
                    expected_floor = as_of - timedelta(days=spec.release_lag_days)
                    lag_days = (as_of - latest_date).days
                    status = "ok" if latest_date >= expected_floor else "lagging"
                    latest_period = str(latest_date)
                    lag_note = "" if status == "ok" else f"滞后 {lag_days} 天"
            rows.append(
                {
                    "dataset": spec.dataset,
                    "source": spec.source,
                    "cadence": spec.cadence,
                    "latest_period": latest_period,
                    "expected_period": str(as_of - timedelta(days=spec.release_lag_days)),
                    "status": "missing" if latest_period is None else status,
                    "note": "" if (latest_period is not None and status == "ok") else lag_note,
                }
            )
        else:
            wm = monthly.get(spec.dataset, {})
            latest_period = wm.get("latest_period")
            expected = _expected_month(as_of, spec.release_lag_days)
            lag_months = _month_diff(latest_period, expected)
            if lag_months == 999:
                status = "missing"
                note = "本地缺失"
            elif lag_months > 1:
                status = "lagging"
                note = f"滞后约 {lag_months} 个月"
            else:
                status = "ok"
                note = ""
            rows.append(
                {
                    "dataset": spec.dataset,
                    "source": spec.source,
                    "cadence": spec.cadence,
                    "latest_period": latest_period,
                    "expected_period": expected,
                    "status": status,
                    "note": note,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"latest_period": pl.String})


def latest_price_row(price_chain: pl.DataFrame) -> pl.DataFrame | None:
    """返回价格链最新一行（含价差），空表返回 None。"""
    if price_chain.is_empty():
        return None
    return price_chain.tail(1)
