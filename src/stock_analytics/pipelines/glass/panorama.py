"""玻璃全景对账：月度合并、衍生指标与中游蓄水池状态机。

纯 Polars 计算，不依赖物理 IO，便于单测锁定行为。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.glass.config import RegimeThresholds

CORE_OUTPUT_COLUMN = "glass_output_w_cases"


def aggregate_furnace_capacity_by_month(furnaces: list[dict[str, Any]]) -> dict[str, float]:
    """计算各月份生效的窑炉净增/冷修日熔量变化 (T/D)。"""
    inc_by_month: dict[str, float] = {}
    for f in furnaces:
        cap = float(f.get("capacity_t_d", 0.0))
        # 新点火达产
        start_date = f.get("actual_start")
        if start_date and cap > 0:
            month = str(start_date)[:7]
            inc_by_month[month] = inc_by_month.get(month, 0.0) + cap
        # 冷修停产
        repair_date = f.get("cold_repair_date")
        if repair_date and cap > 0:
            month = str(repair_date)[:7]
            inc_by_month[month] = inc_by_month.get(month, 0.0) - cap
    return inc_by_month


def latest_core_row(df: pl.DataFrame) -> dict[str, Any] | None:
    if df.is_empty():
        return None
    candidates = df
    if CORE_OUTPUT_COLUMN in df.columns:
        filtered = df.filter(pl.col(CORE_OUTPUT_COLUMN).is_not_null())
        if not filtered.is_empty():
            candidates = filtered
    if "report_month" in candidates.columns:
        candidates = candidates.sort("report_month")
    rows = candidates.tail(1).to_dicts()
    return rows[0] if rows else None


def classify_glass_flow_regime(
    delta_inv: float | None,
    shipment_rate: float | None,
    operating_rate: float | None,
    thresholds: RegimeThresholds,
) -> str:
    """中游蓄水池状态机判定。"""
    if shipment_rate is None or operating_rate is None:
        return "--"

    # 出货率高且去库
    if shipment_rate >= thresholds.destocking_shipment_rate and (
        delta_inv is not None and delta_inv <= 0
    ):
        return "genuine_terminal_destocking"  # 真实刚需去库 (健康)
    # 深度降负主动出清
    if operating_rate <= thresholds.active_destocking_operating_rate:
        return "active_capacity_curtailment"  # 深度冷修减产出清 (左侧拐点前兆)
    # 出货迟钝累库
    if shipment_rate < thresholds.passive_shipment_rate and (
        delta_inv is not None and delta_inv > 0
    ):
        return "passive_inventory_accumulation"  # 需求钝化被动累库 (高风险)
    return "balanced_neutral"  # 产销紧平衡/中性


def merge_monthly_panorama(
    glass_df: pl.DataFrame,
    soda_df: pl.DataFrame,
    customs_df: pl.DataFrame,
    receipt_df: pl.DataFrame,
    futures_df: pl.DataFrame,
    weekly_survey_df: pl.DataFrame,
    furnace_increment: dict[str, float] | None = None,
    regime: RegimeThresholds | None = None,
) -> pl.DataFrame:
    """按月份合并形成玻璃全景表。"""
    if glass_df.is_empty():
        return pl.DataFrame()
    t = regime or RegimeThresholds()
    furnace_inc = furnace_increment or {}

    base = glass_df.sort("report_month")
    for frame in (soda_df, customs_df, receipt_df, futures_df, weekly_survey_df):
        if not frame.is_empty():
            base = base.join(frame, on="report_month", how="left")

    # 窑炉日熔量增量
    months = base.get_column("report_month").to_list()
    cum_cap = 0.0
    cum_caps: list[float] = []
    monthly_incs: list[float] = []
    for m in months:
        inc = furnace_inc.get(m, 0.0)
        cum_cap += inc
        monthly_incs.append(inc)
        cum_caps.append(cum_cap)

    base = base.with_columns(
        pl.Series("furnace_net_delta_t_d", monthly_incs),
        pl.Series("cum_furnace_delta_t_d", cum_caps),
    )

    # 供需剪刀差: 玻璃产量增速 - 纯碱产量增速 (下游拉动 vs 原料供给)
    if "glass_output_yoy" in base.columns and "soda_output_yoy" in base.columns:
        base = base.with_columns(
            (pl.col("glass_output_yoy") - pl.col("soda_output_yoy")).alias("scissors_spread_yoy")
        )

    # 厂库变动 delta_factory_inv
    if "factory_inv_month_end_w_tons" in base.columns:
        base = base.with_columns(
            (
                pl.col("factory_inv_month_end_w_tons")
                - pl.col("factory_inv_month_end_w_tons").shift(1)
            ).alias("delta_factory_inv_w_tons")
        )

    # 状态机评估
    regimes: list[str] = []
    for r in base.iter_rows(named=True):
        reg = classify_glass_flow_regime(
            delta_inv=r.get("delta_factory_inv_w_tons"),
            shipment_rate=r.get("survey_shipment_rate_pct"),
            operating_rate=r.get("survey_operating_rate_pct"),
            thresholds=t,
        )
        regimes.append(reg)

    return base.with_columns(pl.Series("flow_regime", regimes))


__all__ = [
    "CORE_OUTPUT_COLUMN",
    "aggregate_furnace_capacity_by_month",
    "classify_glass_flow_regime",
    "latest_core_row",
    "merge_monthly_panorama",
]
