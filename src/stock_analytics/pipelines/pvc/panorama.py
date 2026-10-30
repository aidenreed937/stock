"""聚氯乙烯 (PVC / V) 全景基本面对账：月度/日度合并、衍生指标、中游蓄水池状态机与大拐点检测。

纯 Polars 向量化计算，保证计算确定性与无物理副作用。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.pvc.config import HistoryConfig, RegimeThresholds

_MISSING = "--"


def classify_pvc_inventory_regime(
    basis_rate_pct: float | None,
    warehouse_w_tons: float | None,
    warrant_pct_3y: float | None,
    delta_warrant: float | None,
    operating_rate_pct: float | None,
) -> str:
    """判定 PVC 中游蓄水池流动性与风险状态。"""
    if warehouse_w_tons is None and delta_warrant is None:
        return _MISSING

    # 1. 天量仓单悬顶 (分位数 > 90% 且 Contango 深贴水)
    if warrant_pct_3y is not None and warrant_pct_3y >= 90.0:
        if basis_rate_pct is not None and basis_rate_pct < -0.5:
            return "bearish_contango_overhang"
        return "high_inventory_pressure"

    # 2. 虚假去库/隐形搬家 (Contango 贴水结构下仓单持续激增)
    if (
        basis_rate_pct is not None
        and basis_rate_pct < -1.0
        and delta_warrant is not None
        and delta_warrant > 0.5
    ):
        return "speculative_transfer_risk"

    # 3. 主动减产去库 (开工率低位 < 75% 且仓单下降)
    if (
        operating_rate_pct is not None
        and operating_rate_pct <= 75.0
        and delta_warrant is not None
        and delta_warrant < 0
    ):
        return "active_destocking"

    # 4. 真实终端去化 (基差走强 Back/平水 且 仓单去化)
    if (
        basis_rate_pct is not None
        and basis_rate_pct >= 0.0
        and delta_warrant is not None
        and delta_warrant < 0
    ):
        return "genuine_terminal_destocking"

    # 5. 被动累库
    if delta_warrant is not None and delta_warrant > 0:
        return "passive_accumulation"

    return "neutral"


def build_pvc_monthly_panorama(
    customs_df: pl.DataFrame,
    receipt_df: pl.DataFrame,
    basis_df: pl.DataFrame,
    weekly_survey_df: pl.DataFrame | None = None,
    regime_cfg: RegimeThresholds | None = None,
) -> pl.DataFrame:
    """按月份汇总合并 PVC 供需、进出口、基差与库存月度全景表。"""
    if customs_df.is_empty() and basis_df.is_empty() and receipt_df.is_empty():
        return pl.DataFrame()

    # 以海关月度为基准月份轴，若无海关则以基差月度为轴
    if not customs_df.is_empty():
        monthly_base = (
            customs_df.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("report_month"))
            .group_by("report_month")
            .agg(
                [
                    pl.col("export_volume_w_tons").sum(),
                    pl.col("export_value_w_usd").sum(),
                    pl.col("export_volume_yoy_pct").last(),
                ]
            )
            .sort("report_month")
        )
    else:
        monthly_base = pl.DataFrame({"report_month": pl.Series([], dtype=pl.Utf8)})

    # 月末仓单
    if not receipt_df.is_empty():
        receipt_monthly = (
            receipt_df.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("report_month"))
            .sort("trade_date")
            .group_by("report_month")
            .last()
            .select(["report_month", "warrant_w_tons", "warrant_contracts"])
            .rename(
                {
                    "warrant_w_tons": "warehouse_w_tons_month_end",
                    "warrant_contracts": "warehouse_contracts_month_end",
                }
            )
        )
        if monthly_base.is_empty():
            monthly_base = receipt_monthly
        else:
            monthly_base = monthly_base.join(
                receipt_monthly, on="report_month", how="full", coalesce=True
            )

    # 月末基差与现期均价
    if not basis_df.is_empty():
        basis_monthly = (
            basis_df.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("report_month"))
            .sort("trade_date")
            .group_by("report_month")
            .agg(
                [
                    pl.col("spot_price_cny").mean().alias("spot_price_monthly_mean"),
                    pl.col("futures_close_cny").mean().alias("futures_close_monthly_mean"),
                    pl.col("basis_cny").last().alias("basis_cny_month_end"),
                    pl.col("basis_rate_pct").last().alias("basis_rate_month_end"),
                    pl.col("basis_term_structure").last().alias("term_structure_month_end"),
                    pl.col("receipts_pctl_3y").last().alias("warrant_pct_3y_month_end"),
                ]
            )
        )
        if monthly_base.is_empty():
            monthly_base = basis_monthly
        else:
            monthly_base = monthly_base.join(
                basis_monthly, on="report_month", how="full", coalesce=True
            )

    # 周度开工率与厂库按月平均
    if weekly_survey_df is not None and not weekly_survey_df.is_empty():
        survey_monthly = (
            weekly_survey_df.with_columns(
                pl.col("trade_date").dt.strftime("%Y-%m").alias("report_month")
            )
            .group_by("report_month")
            .agg(
                [
                    pl.col("operating_rate_pct").mean().alias("operating_rate_monthly_mean"),
                    pl.col("factory_inventory_w_tons").last().alias("factory_inv_w_tons_month_end"),
                ]
            )
        )
        monthly_base = monthly_base.join(survey_monthly, on="report_month", how="left")

    monthly_base = monthly_base.sort("report_month")

    # 仓单月度变动
    if "warehouse_w_tons_month_end" in monthly_base.columns:
        monthly_base = monthly_base.with_columns(
            (
                pl.col("warehouse_w_tons_month_end") - pl.col("warehouse_w_tons_month_end").shift(1)
            ).alias("delta_warrant_w_tons")
        )

    # 电石法吨现金成本与综合利润估算 (假设电石法现金成本约 5100 元/吨基准)
    if "spot_price_monthly_mean" in monthly_base.columns:
        monthly_base = monthly_base.with_columns(
            (pl.col("spot_price_monthly_mean") - 5100.0).alias("carbide_cash_margin_cny"),
            (pl.col("spot_price_monthly_mean") - 5600.0).alias("carbide_full_margin_cny"),
        )

    # 蓄水池状态机
    regimes: list[str] = []
    for r in monthly_base.iter_rows(named=True):
        reg = classify_pvc_inventory_regime(
            basis_rate_pct=r.get("basis_rate_month_end"),
            warehouse_w_tons=r.get("warehouse_w_tons_month_end"),
            warrant_pct_3y=r.get("warrant_pct_3y_month_end"),
            delta_warrant=r.get("delta_warrant_w_tons"),
            operating_rate_pct=r.get("operating_rate_monthly_mean"),
        )
        regimes.append(reg)

    monthly_base = monthly_base.with_columns(pl.Series("inventory_flow_regime", regimes))
    return monthly_base.sort("report_month")


def detect_pvc_regime_episodes(
    monthly_panorama: pl.DataFrame,
    history_cfg: HistoryConfig | None = None,
) -> list[dict[str, Any]]:
    """从 PVC 月度全景表中自动识别历史高利润牛市期与深度亏损磨底期。"""
    cfg = history_cfg or HistoryConfig()
    if monthly_panorama.is_empty() or "carbide_cash_margin_cny" not in monthly_panorama.columns:
        return []

    episodes: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_kind: str | None = None

    for row in monthly_panorama.sort("report_month").iter_rows(named=True):
        margin = row.get("carbide_cash_margin_cny")
        if margin is None:
            kind = None
        elif float(margin) >= cfg.high_profit_margin:
            kind = "high_profit"
        elif float(margin) <= cfg.deep_loss_margin:
            kind = "deep_loss"
        else:
            kind = None

        if kind is None or kind != current_kind:
            if current:
                episodes.append(current)
            current = [row] if kind is not None else []
            current_kind = kind
        elif kind == current_kind:
            current.append(row)

    if current:
        episodes.append(current)

    results: list[dict[str, Any]] = []
    for group in episodes:
        if len(group) < cfg.min_episode_months:
            continue
        margins = [
            float(r["carbide_cash_margin_cny"])
            for r in group
            if r.get("carbide_cash_margin_cny") is not None
        ]
        spots = [
            float(r["spot_price_monthly_mean"])
            for r in group
            if r.get("spot_price_monthly_mean") is not None
        ]
        exports = [
            float(r["export_volume_w_tons"])
            for r in group
            if r.get("export_volume_w_tons") is not None
        ]
        if not margins:
            continue

        results.append(
            {
                "kind": group[0].get("kind", "deep_loss" if margins[0] < 0 else "high_profit"),
                "label": "超额利润景气期" if margins[0] > 0 else "现金击穿深度亏损期",
                "start_month": str(group[0]["report_month"]),
                "end_month": str(group[-1]["report_month"]),
                "months_count": len(group),
                "margin_mean": round(sum(margins) / len(margins), 1),
                "margin_min": round(min(margins), 1),
                "margin_max": round(max(margins), 1),
                "spot_min": round(min(spots), 1) if spots else None,
                "spot_max": round(max(spots), 1) if spots else None,
                "export_mean_w_tons": round(sum(exports) / len(exports), 1) if exports else None,
            }
        )

    results.sort(key=lambda x: abs(float(x.get("margin_mean") or 0.0)), reverse=True)
    if cfg.max_episodes > 0:
        results = results[: cfg.max_episodes]
    return results


__all__ = [
    "build_pvc_monthly_panorama",
    "classify_pvc_inventory_regime",
    "detect_pvc_regime_episodes",
]
