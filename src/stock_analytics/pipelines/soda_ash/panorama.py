"""纯碱全景对账：月度合并、衍生指标、中游蓄水池状态机与历史拐点检测。

本模块全部为纯 Polars 计算（不读写物理目录），便于单元测试锁定行为。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.soda_ash.config import HistoryConfig, RegimeThresholds

_MISSING = "--"

# 核心事实列：缺失该列即该月供需平衡尚未成立（NBS 未发布），不得作为最新基准月
CORE_OUTPUT_COLUMN = "soda_output_w_tons"


def aggregate_capacity_by_month(projects: list[dict[str, Any]]) -> dict[str, float]:
    """计算各月份生效的新增/退出有效产能增量 (万吨/年)。

    仅采信 ``actual_start``（已投料达产/已关停的既成事实）。在建项目的
    ``expected_start`` 属于计划而非事实，不得提前计入累计有效产能，
    否则会把规划产能当作 Ground Truth 并引入前视。
    """
    inc_by_month: dict[str, float] = {}
    for p in projects:
        start_date = p.get("actual_start")
        cap = p.get("capacity_w_tons")
        if start_date and cap is not None:
            month = str(start_date)[:7]
            inc_by_month[month] = inc_by_month.get(month, 0.0) + float(cap)
    return inc_by_month


def latest_core_row(df: pl.DataFrame) -> dict[str, Any] | None:
    """返回最近一个核心产量非空的月份行。

    NBS 月度产量存在「月份已建行但值待发布」的尾行（如 2026-08 仅有仓单/厂库），
    若直接取 ``tail(1)`` 会把研报基准月与门禁评估落在空值行上。

    调用方可能只提供不带 ``report_month`` 的截面（如单元测试的合成门禁输入），
    此时退化为取最后一行，保持向后兼容。
    """
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


def classify_flow_regime(
    delta_f: float | None,
    ship_r: float | None,
    delta_rec: float | None,
    basis: float | None,
    op_r: float | None,
    t: RegimeThresholds,
) -> str:
    """判定单月中游蓄水池流量状态（保留 MVP 口径）。"""
    if delta_f is None and ship_r is None:
        return _MISSING

    epsilon = t.delta_inv_epsilon
    is_destocking = (delta_f is not None and delta_f < -epsilon) or (
        ship_r is not None and ship_r >= t.destocking_shipment_rate
    )
    if is_destocking:
        speculative = (
            basis is not None
            and basis < t.basis_speculative_cny
            and delta_rec is not None
            and delta_rec > t.receipt_speculative_delta
        )
        return "speculative_transfer_risk" if speculative else "genuine_terminal_destocking"

    passive_by_rate = (delta_f is not None and delta_f > epsilon) and (
        ship_r is not None and ship_r < t.passive_shipment_rate
    )
    if passive_by_rate:
        return "passive_accumulation"
    if op_r is not None and op_r < t.active_destocking_operating_rate:
        return "active_destocking"
    if ship_r is not None and t.balanced_shipment_min <= ship_r <= t.balanced_shipment_max:
        return "balanced_neutral"
    if delta_f is not None and delta_f > 0:
        return "passive_accumulation"
    return "neutral"


def merge_monthly_panorama(
    *,
    soda_df: pl.DataFrame,
    glass_df: pl.DataFrame,
    customs_df: pl.DataFrame,
    cap_increment: dict[str, float],
    receipt_df: pl.DataFrame,
    factory_df: pl.DataFrame,
    spreads_df: pl.DataFrame,
    futures_df: pl.DataFrame | None = None,
    hold_rank_df: pl.DataFrame | None = None,
    regime: RegimeThresholds | None = None,
) -> pl.DataFrame:
    """按月份合并形成全景事实表，并追加衍生指标与蓄水池状态机。"""
    if soda_df.is_empty():
        return pl.DataFrame()
    thresholds = regime or RegimeThresholds()

    base = soda_df.sort("report_month")
    for frame in (glass_df, customs_df, receipt_df, factory_df, spreads_df):
        if not frame.is_empty():
            base = base.join(frame, on="report_month", how="left")
    for optional_frame in (futures_df, hold_rank_df):
        if optional_frame is not None and not optional_frame.is_empty():
            base = base.join(optional_frame, on="report_month", how="left")

    # 产能事件新增量与累计增量
    months = base.get_column("report_month").to_list()
    cum_cap = 0.0
    cum_caps: list[float] = []
    monthly_incs: list[float] = []
    for m in months:
        inc = cap_increment.get(m, 0.0)
        cum_cap += inc
        monthly_incs.append(inc)
        cum_caps.append(cum_cap)
    base = base.with_columns(
        pl.Series("cap_increment_w_tons", monthly_incs),
        pl.Series("cum_cap_expansion_w_tons", cum_caps),
    )

    # 供需剪刀差 proxy: 玻璃同比 - 纯碱同比
    if "glass_output_yoy" in base.columns and "soda_output_yoy" in base.columns:
        base = base.with_columns(
            (pl.col("glass_output_yoy") - pl.col("soda_output_yoy")).alias("scissors_spread_yoy")
        )

    # 基差与库存变动
    base_cols = base.columns
    if "soda_spot_price_cny" in base_cols and "futures_settle_month_end" in base_cols:
        base = base.with_columns(
            (pl.col("soda_spot_price_cny") - pl.col("futures_settle_month_end")).alias(
                "basis_month_end"
            ),
            (
                (pl.col("soda_spot_price_cny") - pl.col("futures_settle_month_end"))
                / pl.col("futures_settle_month_end")
                * 100.0
            ).alias("basis_rate_month_end"),
        )
    if "factory_inv_month_end_w_tons" in base_cols:
        base = base.with_columns(
            (
                pl.col("factory_inv_month_end_w_tons")
                - pl.col("factory_inv_month_end_w_tons").shift(1)
            ).alias("delta_factory_inv_w_tons")
        )
    if "warehouse_receipt_month_end" in base_cols:
        base = base.with_columns(
            (
                pl.col("warehouse_receipt_month_end")
                - pl.col("warehouse_receipt_month_end").shift(1)
            ).alias("delta_warehouse_receipt")
        )

    regimes = [
        classify_flow_regime(
            delta_f=r.get("delta_factory_inv_w_tons"),
            ship_r=r.get("survey_shipment_rate_pct"),
            delta_rec=r.get("delta_warehouse_receipt"),
            basis=r.get("basis_month_end"),
            op_r=r.get("survey_operating_rate_pct"),
            t=thresholds,
        )
        for r in base.iter_rows(named=True)
    ]
    base = base.with_columns(pl.Series("inventory_flow_regime", regimes))
    return base.sort("report_month")


def detect_regime_episodes(
    panorama: pl.DataFrame,
    history: HistoryConfig | None = None,
) -> list[dict[str, Any]]:
    """从全景表自动识别历史高利润/深度亏损拐点期（数据驱动，无硬编码年份）。

    每个拐点期的统计量（利润均值/极值、现货价格区间、剪刀差首尾）均来自
    本地 Curated 数据；机制解读由渲染层标注为推断。
    """
    cfg = history or HistoryConfig()
    if panorama.is_empty() or "double_ton_margin_cny" not in panorama.columns:
        return []

    episodes: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_kind: str | None = None
    for row in panorama.sort("report_month").iter_rows(named=True):
        kind = _episode_kind(row, cfg)
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
        summary = _summarize_episode(group, panorama, cfg)
        if summary is not None:
            results.append(summary)

    results.sort(
        key=lambda item: abs(float(item.get("margin_mean") or 0.0)),
        reverse=True,
    )
    if cfg.max_episodes > 0:
        results = results[: cfg.max_episodes]
    return results


def _episode_kind(row: dict[str, Any], cfg: HistoryConfig) -> str | None:
    # 权威口径：history.high_profit_margin / deep_loss_margin（品种级配置驱动）。
    # 数值落在中性区间时显式返回 None，以正确切断连续状态期（避免把 2019~2025
    # 这类跨越中位利润的长区间误判为单一「高利润拐点」）。
    # 仅当数值缺失时，才回退到 chemical_spreads.margin_regime 标签。
    margin = row.get("double_ton_margin_cny")
    if margin is not None:
        try:
            margin_value = float(margin)
        except (TypeError, ValueError):
            margin_value = None
        if margin_value is not None:
            if margin_value >= cfg.high_profit_margin:
                return "high_profit"
            if margin_value <= cfg.deep_loss_margin:
                return "deep_loss"
            return None

    regime = row.get("margin_regime")
    if regime == "high_profit":
        return "high_profit"
    if regime == "deep_loss":
        return "deep_loss"
    return None


def _summarize_episode(
    group: list[dict[str, Any]],
    panorama: pl.DataFrame,
    cfg: HistoryConfig,
) -> dict[str, Any] | None:
    kind = _episode_kind(group[0], cfg)
    if kind is None:
        return None
    margins = _numbers(group, "double_ton_margin_cny")
    spots = _numbers(group, "soda_spot_price_cny")
    scissors = _numbers(group, "scissors_spread_yoy")
    if not margins:
        return None

    later = _following_window(panorama, group, cfg.follow_up_months)
    later_margins = _numbers(later, "double_ton_margin_cny")
    transition_note = _transition_note(
        sum(margins) / len(margins), later_margins, cfg.follow_up_months
    )

    return {
        "kind": kind,
        "label": "高利润状态期" if kind == "high_profit" else "深度亏损状态期",
        "start": str(group[0].get("report_month")),
        "end": str(group[-1].get("report_month")),
        "months_count": len(group),
        "margin_mean": round(sum(margins) / len(margins), 1),
        "margin_min": round(min(margins), 1),
        "margin_max": round(max(margins), 1),
        "spot_min": round(min(spots), 1) if spots else None,
        "spot_max": round(max(spots), 1) if spots else None,
        "scissors_first": scissors[0] if scissors else None,
        "scissors_last": scissors[-1] if scissors else None,
        "transition_note": transition_note,
    }


def _numbers(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _following_window(
    panorama: pl.DataFrame,
    group: list[dict[str, Any]],
    months: int,
) -> list[dict[str, Any]]:
    rows = panorama.sort("report_month").to_dicts()
    end_month = str(group[-1].get("report_month"))
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("report_month")) > end_month:
            out.append(row)
            if len(out) >= months:
                break
    return out


def _transition_note(
    episode_mean: float,
    later_margins: list[float],
    window_months: int,
) -> str | None:
    if not later_margins:
        return None
    later_mean = sum(later_margins) / len(later_margins)
    delta = later_mean - episode_mean
    if abs(delta) < 1.0:
        return f"后续 {len(later_margins)} 个月利润基本维持（均值 {later_mean:+.0f} 元/吨）"
    direction = "回升" if delta > 0 else "进一步回落/走弱"
    return f"后续 {len(later_margins)} 个月利润均值 {later_mean:+.0f} 元/吨（{direction} {delta:+.0f} 元/吨）"


__all__ = [
    "CORE_OUTPUT_COLUMN",
    "aggregate_capacity_by_month",
    "classify_flow_regime",
    "detect_regime_episodes",
    "latest_core_row",
    "merge_monthly_panorama",
]
