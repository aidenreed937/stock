"""钛白粉全景对账：月度合并、衍生指标、寡头蓄水池状态机与历史拐点检测。

纯 Polars 计算（不读写物理目录），便于单元测试锁定行为。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.tio2.config import HistoryConfig, RegimeThresholds

_MISSING = "--"


def aggregate_capacity_by_month(projects: list[dict[str, Any]]) -> dict[str, float]:
    """计算各月份生效的新增/退出有效产能增量 (万吨/年)。"""
    inc_by_month: dict[str, float] = {}
    for p in projects:
        start_date = p.get("actual_start") or p.get("expected_start")
        cap = p.get("capacity_w_tons")
        if start_date and cap is not None:
            month = str(start_date)[:7]
            inc_by_month[month] = inc_by_month.get(month, 0.0) + float(cap)
    return inc_by_month


def classify_flow_regime(
    export_yoy: float | None,
    delta_spot_price: float | None,
    op_r: float | None,
    t: RegimeThresholds,
) -> str:
    """判定单月寡头与中游蓄水池流动状态。"""
    if export_yoy is None and delta_spot_price is None and op_r is None:
        return _MISSING

    # 1. 装置实质检修/低开工主动去库
    if op_r is not None and op_r < t.active_destocking_operating_rate:
        return "active_destocking"

    # 2. 海外强劲泄洪/外需拉动终端真去库 (海关出口 YoY >= 15%)
    if export_yoy is not None and export_yoy >= t.destocking_export_yoy:
        return "genuine_terminal_destocking"

    # 3. 外需收缩 -> 被动累库 (delta_spot 仅作信号参考，不再重复分支)
    if export_yoy is not None and export_yoy < t.passive_export_yoy:
        return "passive_accumulation"

    # 4. 现货提价但外需平稳 -> 主动补库
    if delta_spot_price is not None and delta_spot_price > 0:
        return "active_restocking"

    return "neutral"


def merge_monthly_panorama(
    *,
    customs_df: pl.DataFrame,
    spot_df: pl.DataFrame,
    spreads_df: pl.DataFrame | None = None,
    industry_df: pl.DataFrame | None = None,
    weekly_survey_df: pl.DataFrame | None = None,
    monthly_survey_df: pl.DataFrame | None = None,
    ma20_df: pl.DataFrame | None = None,
    cap_increment: dict[str, float] | None = None,
    regime: RegimeThresholds | None = None,
    margin_fallback: dict[str, float] | None = None,
) -> pl.DataFrame:
    """按月份合并形成钛白粉全景事实表，并追加衍生指标与蓄水池状态机。"""
    cap_inc = cap_increment or {}
    thresholds = regime or RegimeThresholds()

    # 收集全部月份
    month_sets: set[str] = set()
    for f in (customs_df, spot_df, spreads_df, industry_df):
        if f is not None and not f.is_empty() and "report_month" in f.columns:
            month_sets.update(f.get_column("report_month").drop_nulls().to_list())

    if not month_sets:
        return pl.DataFrame()

    base = pl.DataFrame({"report_month": sorted(month_sets)})

    # 合并各维度 (周度/月度调研与 MA20 信号按月末/月末信号左连)
    for frame in (
        customs_df,
        spot_df,
        spreads_df,
        industry_df,
        weekly_survey_df,
        monthly_survey_df,
        ma20_df,
    ):
        if frame is not None and not frame.is_empty():
            base = base.join(frame, on="report_month", how="left")

    # 产能扩张时序
    # 口径说明：cum_cap_expansion 为“计划累计新增产能”，同时计入已投产 (actual_start) 与在建/拟建 (expected_start) 项目。
    months = base.get_column("report_month").to_list()
    cum_cap = 0.0
    cum_caps: list[float] = []
    monthly_incs: list[float] = []
    for m in months:
        inc = cap_inc.get(m, 0.0)
        cum_cap += inc
        monthly_incs.append(inc)
        cum_caps.append(cum_cap)

    base = base.with_columns(
        pl.Series("cap_increment_w_tons", monthly_incs),
        pl.Series("cum_cap_expansion_w_tons", cum_caps),
    )

    # 现货月度环比变动
    base_cols = base.columns
    if "tio2_spot_price_cny" in base_cols:
        base = base.with_columns(
            (pl.col("tio2_spot_price_cny") - pl.col("tio2_spot_price_cny").shift(1)).alias(
                "delta_spot_price_cny"
            )
        )
    else:
        base = base.with_columns(pl.lit(None).cast(pl.Float64).alias("delta_spot_price_cny"))

    # 如果有理论价差，保留利润状态；如果没有，按配置驱动的综合成本线推导毛利档位
    # (margin_fallback 由管线从 company_projections.yaml 中周期成本线 + tio2/cost_models.yaml 利润带装配)
    if "tio2_margin_cny" not in base.columns:
        if "tio2_spot_price_cny" in base.columns and margin_fallback:
            cost_line = float(margin_fallback.get("cost_line_cny", 14000.0))
            high_th = float(margin_fallback.get("high_profit", 2000.0))
            prof_th = float(margin_fallback.get("profitable", 500.0))
            near_th = float(margin_fallback.get("near_breakeven", -500.0))
            base = base.with_columns(
                (pl.col("tio2_spot_price_cny") - cost_line).alias("tio2_margin_cny"),
                pl.when(pl.col("tio2_spot_price_cny") - cost_line > high_th)
                .then(pl.lit("high_profit"))
                .when(pl.col("tio2_spot_price_cny") - cost_line > prof_th)
                .then(pl.lit("profitable"))
                .when(pl.col("tio2_spot_price_cny") - cost_line > near_th)
                .then(pl.lit("near_breakeven"))
                .otherwise(pl.lit("deep_loss"))
                .alias("margin_regime"),
            )
        else:
            base = base.with_columns(
                pl.lit(None).cast(pl.Float64).alias("tio2_margin_cny"),
                pl.lit(None).cast(pl.String).alias("margin_regime"),
            )

    # 供需剪刀差 proxy：出口增速 (外需)
    if "export_qty_yoy" in base.columns:
        base = base.with_columns(pl.col("export_qty_yoy").alias("scissors_spread_yoy"))

    # 蓄水池状态机判定
    regimes = [
        classify_flow_regime(
            export_yoy=r.get("export_qty_yoy"),
            delta_spot_price=r.get("delta_spot_price_cny"),
            op_r=None,
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
    """从全景表自动识别历史高利润/深度亏损拐点期（数据驱动）。"""
    cfg = history or HistoryConfig()
    if panorama.is_empty() or "tio2_margin_cny" not in panorama.columns:
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
    regime = row.get("margin_regime")
    if regime == "high_profit":
        return "high_profit"
    if regime == "deep_loss":
        return "deep_loss"
    margin = row.get("tio2_margin_cny")
    if margin is not None:
        try:
            val = float(margin)
            if val >= cfg.high_profit_margin:
                return "high_profit"
            if val <= cfg.deep_loss_margin:
                return "deep_loss"
        except (TypeError, ValueError):
            pass
    return None


def _summarize_episode(
    group: list[dict[str, Any]],
    panorama: pl.DataFrame,
    cfg: HistoryConfig,
) -> dict[str, Any] | None:
    if not group:
        return None
    start_month = str(group[0]["report_month"])
    end_month = str(group[-1]["report_month"])
    kind = _episode_kind(group[0], cfg)
    if kind is None:
        return None

    margins = [float(r["tio2_margin_cny"]) for r in group if r.get("tio2_margin_cny") is not None]
    margin_mean = sum(margins) / len(margins) if margins else None
    prices = [
        float(r["tio2_spot_price_cny"]) for r in group if r.get("tio2_spot_price_cny") is not None
    ]
    price_min = min(prices) if prices else None
    price_max = max(prices) if prices else None

    return {
        "start_month": start_month,
        "end_month": end_month,
        "kind": kind,
        "duration_months": len(group),
        "margin_mean": round(margin_mean, 2) if margin_mean is not None else None,
        "price_min": round(price_min, 2) if price_min is not None else None,
        "price_max": round(price_max, 2) if price_max is not None else None,
    }
