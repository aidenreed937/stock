"""PTA 全景基本面对账表合并与蓄水池状态机判定。

打通宏观供需剪刀差、加工差状态机、郑商所仓单流向与期现基差率。
"""

from __future__ import annotations

import logging
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

FLOW_REGIME_CN: dict[str, str] = {
    "speculative_transfer_risk": "疑似投机移库 (囤货预警)",
    "genuine_terminal_destocking": "真实刚需去库 (健康)",
    "passive_accumulation": "被动累库胀库 (承压)",
    "active_destocking": "主动减产去库 (筑底)",
    "active_stocking": "主动补库囤货 (景气扩张)",
    "balanced_neutral": "产销紧平衡 (中性)",
    "neutral": "中性平稳",
    "--": "--",
}

CHAIN_MARGIN_REGIME_CN: dict[str, str] = {
    "both_profitable": "全产业链景气共振",
    "upstream_squeeze": "上游挤压下游 (炼化强/长丝弱)",
    "downstream_expansion": "下游长丝红利期 (长丝强/炼化弱)",
    "both_loss": "全线深度亏损磨底",
    "balanced_neutral": "中枢紧平衡",
    "neutral": "中性平稳",
    "--": "--",
}


def aggregate_capacity_by_month(projects: list[dict[str, Any]]) -> pl.DataFrame:
    """将重大产能投产事件按月份聚合成月度新增产能表 (万吨)。"""
    records: list[dict[str, Any]] = []
    for p in projects:
        start_date = p.get("actual_start") or p.get("expected_start")
        cap = float(p.get("capacity_w_tons", 0.0))
        if start_date and cap != 0:
            month = str(start_date)[:7]
            records.append({"report_month": month, "new_capacity_w_tons": cap})

    if not records:
        return pl.DataFrame(schema={"report_month": pl.Utf8, "new_capacity_w_tons": pl.Float64})

    df = pl.DataFrame(records)
    return df.group_by("report_month").agg(pl.col("new_capacity_w_tons").sum()).sort("report_month")


def classify_flow_regime(
    scissors: float | None,
    delta_receipt: float | None,
    spread: float | None,
) -> str:
    """根据供需剪刀差与仓单蓄水池增减判定库存流动状态机。"""
    if scissors is None or delta_receipt is None:
        return "neutral"

    if scissors > 0 and delta_receipt <= 0:
        return "genuine_terminal_destocking"
    if scissors < 0 and delta_receipt > 0:
        return "passive_accumulation"
    if scissors < 0 and delta_receipt <= 0:
        return "speculative_transfer_risk"
    if scissors > 0 and delta_receipt > 0:
        return "active_stocking"
    return "balanced_neutral"


def classify_margin_regime(
    spread: float | None,
    high_profit_threshold: float = 600.0,
    profitable_threshold: float = 450.0,
    breakeven_threshold: float = 350.0,
) -> str:
    """根据理论加工费测算利润状态机。"""
    if spread is None:
        return "neutral"
    if spread >= high_profit_threshold:
        return "high_profit"
    if spread >= profitable_threshold:
        return "profitable"
    if spread >= breakeven_threshold:
        return "near_breakeven"
    return "deep_loss"


def classify_chain_margin_regime(
    pta_spread: float | None,
    poy_spread: float | None,
    pta_breakeven: float = 350.0,
    poy_breakeven: float = 800.0,
    pta_profit: float = 550.0,
    poy_profit: float = 1100.0,
) -> str:
    """根据 PTA 与 POY 双加工差判定上下游产业链利润博弈状态机。"""
    if pta_spread is None or poy_spread is None:
        return "neutral"

    pta_strong = pta_spread >= pta_profit
    pta_weak = pta_spread < pta_breakeven
    poy_strong = poy_spread >= poy_profit
    poy_weak = poy_spread < poy_breakeven

    if pta_strong and poy_strong:
        return "both_profitable"
    if pta_strong and poy_weak:
        return "upstream_squeeze"
    if pta_weak and poy_strong:
        return "downstream_expansion"
    if pta_weak and poy_weak:
        return "both_loss"
    if pta_weak and poy_spread >= poy_breakeven:
        return "downstream_expansion"
    if pta_spread >= pta_breakeven and poy_weak:
        return "upstream_squeeze"
    return "balanced_neutral"


def merge_monthly_panorama(
    pta_output_df: pl.DataFrame,
    fiber_df: pl.DataFrame,
    cap_increment: pl.DataFrame,
    receipt_df: pl.DataFrame,
    futures_df: pl.DataFrame,
    spreads_df: pl.DataFrame,
    export_df: pl.DataFrame,
    high_profit_margin: float = 600.0,
    deep_loss_margin: float = 350.0,
) -> pl.DataFrame:
    """构建月度全景基本面对账核心大宽表。"""
    # 1. 收集所有涉及的月份集合并强制转为 Utf8 格式
    all_months: set[str] = set()
    clean_inputs: list[pl.DataFrame] = []
    for d in (
        pta_output_df,
        fiber_df,
        cap_increment,
        receipt_df,
        futures_df,
        spreads_df,
        export_df,
    ):
        if not d.is_empty() and "report_month" in d.columns:
            cd = d.with_columns(pl.col("report_month").cast(pl.Utf8))
            all_months.update(cd.get_column("report_month").drop_nulls().to_list())
            clean_inputs.append(cd)
        else:
            clean_inputs.append(d)

    (
        c_pta_out,
        c_fiber,
        c_cap,
        c_receipt,
        c_futures,
        c_spreads,
        c_export,
    ) = clean_inputs

    if not all_months:
        return pl.DataFrame()

    base_df = pl.DataFrame({"report_month": sorted(list(all_months))})

    # 2. 依次关联各事实表
    joined = base_df
    pta_col = (
        "actual_output_w_tons"
        if "actual_output_w_tons" in c_pta_out.columns
        else ("output_w_tons" if "output_w_tons" in c_pta_out.columns else None)
    )
    if not c_pta_out.is_empty() and pta_col is not None:
        sub_out = c_pta_out.select(
            [
                "report_month",
                pl.col(pta_col).alias("pta_output_w_tons"),
                pl.col("implied_capacity_utilization_pct").alias("pta_capacity_utilization_pct"),
            ]
        )
        joined = joined.join(sub_out, on="report_month", how="left")
    else:
        joined = joined.with_columns(
            [
                pl.lit(None).cast(pl.Float64).alias("pta_output_w_tons"),
                pl.lit(None).cast(pl.Float64).alias("pta_capacity_utilization_pct"),
            ]
        )

    if not c_fiber.is_empty():
        joined = joined.join(c_fiber, on="report_month", how="left")
    else:
        joined = joined.with_columns(
            pl.lit(None).cast(pl.Float64).alias("synthetic_fiber_production")
        )

    if not c_cap.is_empty():
        joined = joined.join(c_cap, on="report_month", how="left")
    else:
        joined = joined.with_columns(pl.lit(0.0).alias("new_capacity_w_tons"))

    if not c_receipt.is_empty():
        joined = joined.join(c_receipt, on="report_month", how="left")
    else:
        joined = joined.with_columns(
            pl.lit(None).cast(pl.Float64).alias("warehouse_receipt_month_end")
        )

    if not c_futures.is_empty():
        joined = joined.join(c_futures, on="report_month", how="left")
    else:
        joined = joined.with_columns(
            [
                pl.lit(None).cast(pl.Float64).alias("futures_close_monthly_avg"),
                pl.lit(None).cast(pl.Float64).alias("futures_close_month_end"),
            ]
        )

    if not c_spreads.is_empty():
        joined = joined.join(c_spreads, on="report_month", how="left")
    else:
        joined = joined.with_columns(
            [
                pl.lit(None).cast(pl.Float64).alias("spread_margin_monthly_avg"),
                pl.lit(None).cast(pl.Float64).alias("spread_margin_month_end"),
                pl.lit(None).cast(pl.Float64).alias("poy_spread_monthly_avg"),
                pl.lit(None).cast(pl.Float64).alias("poy_spread_month_end"),
            ]
        )

    if "poy_spread_monthly_avg" not in joined.columns:
        joined = joined.with_columns(pl.lit(None).cast(pl.Float64).alias("poy_spread_monthly_avg"))
    if "poy_spread_month_end" not in joined.columns:
        joined = joined.with_columns(pl.lit(None).cast(pl.Float64).alias("poy_spread_month_end"))

    if not c_export.is_empty():
        joined = joined.join(c_export, on="report_month", how="left")
    else:
        joined = joined.with_columns(pl.lit(None).cast(pl.Float64).alias("polyester_export_w_tons"))

    joined = joined.sort("report_month")

    # 3. 计算一阶导与二阶导：同比与差分
    # 填充 new_capacity_w_tons null 为 0.0
    joined = joined.with_columns(pl.col("new_capacity_w_tons").fill_null(0.0))

    # 计算 PTA 产量同比与化纤产量同比 (按 12 期 shift)
    joined = joined.with_columns(
        [
            (
                (pl.col("pta_output_w_tons") - pl.col("pta_output_w_tons").shift(12))
                / pl.col("pta_output_w_tons").shift(12)
                * 100.0
            ).alias("pta_output_yoy"),
            (
                (
                    pl.col("synthetic_fiber_production")
                    - pl.col("synthetic_fiber_production").shift(12)
                )
                / pl.col("synthetic_fiber_production").shift(12)
                * 100.0
            ).alias("synthetic_fiber_yoy"),
            (
                (pl.col("polyester_export_w_tons") - pl.col("polyester_export_w_tons").shift(12))
                / pl.col("polyester_export_w_tons").shift(12)
                * 100.0
            ).alias("polyester_export_yoy"),
            (
                pl.col("warehouse_receipt_month_end")
                - pl.col("warehouse_receipt_month_end").shift(1)
            ).alias("delta_warehouse_receipt"),
        ]
    )

    # 供需剪刀差 (Scissors = 下游合成纤维实物产量同比增速 - 上游 PTA 官方实物产量同比增速) 与 出口拉动率
    joined = joined.with_columns(
        [
            (pl.col("synthetic_fiber_yoy") - pl.col("pta_output_yoy")).alias("scissors_spread_yoy"),
            (
                pl.col("polyester_export_w_tons") / pl.col("synthetic_fiber_production") * 100.0
            ).alias("export_pull_rate_pct"),
        ]
    )

    # 期现基差
    if "spot_price_monthly_avg" in joined.columns and "futures_close_monthly_avg" in joined.columns:
        joined = joined.with_columns(
            (pl.col("spot_price_monthly_avg") - pl.col("futures_close_monthly_avg")).alias(
                "basis_cny"
            )
        )
        joined = joined.with_columns(
            (pl.col("basis_cny") / pl.col("futures_close_monthly_avg") * 100.0).alias(
                "basis_rate_pct"
            )
        )
    else:
        joined = joined.with_columns(
            [
                pl.lit(None).cast(pl.Float64).alias("basis_cny"),
                pl.lit(None).cast(pl.Float64).alias("basis_rate_pct"),
            ]
        )

    # 4. 状态机判定 (Flow Regime, Margin Regime & Chain Margin Regime)
    flow_regimes: list[str] = []
    margin_regimes: list[str] = []
    chain_margin_regimes: list[str] = []
    for r in joined.iter_rows(named=True):
        f_reg = classify_flow_regime(
            scissors=r.get("scissors_spread_yoy"),
            delta_receipt=r.get("delta_warehouse_receipt"),
            spread=r.get("spread_margin_monthly_avg"),
        )
        m_reg = classify_margin_regime(
            spread=r.get("spread_margin_monthly_avg"),
            high_profit_threshold=high_profit_margin,
            breakeven_threshold=deep_loss_margin,
        )
        c_reg = classify_chain_margin_regime(
            pta_spread=r.get("spread_margin_monthly_avg"),
            poy_spread=r.get("poy_spread_monthly_avg"),
        )
        flow_regimes.append(f_reg)
        margin_regimes.append(m_reg)
        chain_margin_regimes.append(c_reg)

    joined = joined.with_columns(
        [
            pl.Series("inventory_flow_regime", flow_regimes),
            pl.Series("margin_regime", margin_regimes),
            pl.Series("chain_margin_regime", chain_margin_regimes),
        ]
    )

    return joined.sort("report_month")


def detect_regime_episodes(
    df: pl.DataFrame,
    high_profit_threshold: float = 600.0,
    deep_loss_threshold: float = 350.0,
    min_months: int = 2,
    max_episodes: int = 6,
    follow_up_months: int = 3,
) -> list[dict[str, Any]]:
    """检测历史加工费周期大拐点 (暴利顶区与现金出清底区)。"""
    if df.is_empty() or "spread_margin_monthly_avg" not in df.columns:
        return []

    episodes: list[dict[str, Any]] = []
    current_type: str | None = None
    start_idx: int = 0
    count: int = 0

    rows = df.to_dicts()
    for i, r in enumerate(rows):
        sp = r.get("spread_margin_monthly_avg")
        if sp is None:
            if count >= min_months and current_type:
                episodes.append(
                    _build_episode(rows, start_idx, i - 1, current_type, follow_up_months)
                )
            current_type = None
            count = 0
            continue

        r_type = None
        if sp >= high_profit_threshold:
            r_type = "high_profit_peak"
        elif sp <= deep_loss_threshold:
            r_type = "deep_loss_trough"

        if r_type == current_type and r_type is not None:
            count += 1
        else:
            if count >= min_months and current_type:
                episodes.append(
                    _build_episode(rows, start_idx, i - 1, current_type, follow_up_months)
                )
            current_type = r_type
            start_idx = i
            count = 1 if r_type is not None else 0

    if count >= min_months and current_type:
        episodes.append(
            _build_episode(rows, start_idx, len(rows) - 1, current_type, follow_up_months)
        )

    return episodes[-max_episodes:]


def _build_episode(
    rows: list[dict[str, Any]],
    start_idx: int,
    end_idx: int,
    ep_type: str,
    follow_up_months: int,
) -> dict[str, Any]:
    start_month = rows[start_idx]["report_month"]
    end_month = rows[end_idx]["report_month"]
    dur = end_idx - start_idx + 1
    spreads = [
        rows[j]["spread_margin_monthly_avg"]
        for j in range(start_idx, end_idx + 1)
        if rows[j].get("spread_margin_monthly_avg") is not None
    ]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0.0

    fu_end = min(len(rows) - 1, end_idx + follow_up_months)
    fu_spreads = [
        rows[j]["spread_margin_monthly_avg"]
        for j in range(end_idx + 1, fu_end + 1)
        if rows[j].get("spread_margin_monthly_avg") is not None
    ]
    fu_avg_spread = sum(fu_spreads) / len(fu_spreads) if fu_spreads else None

    return {
        "type": ep_type,
        "start_month": start_month,
        "end_month": end_month,
        "duration_months": dur,
        "avg_spread": avg_spread,
        "follow_up_avg_spread": fu_avg_spread,
    }
