"""钛白粉周期股分阶段量化交易门禁评估（数据驱动）。

配置源为品种级唯一维护文件 ``config/industry/chemicals/tio2/trading_gates.yaml``
（B 类通用模板见门面 ``cyclical_trading_gates.yaml`` 的 ``oligopoly_gate``，tio2 门禁以本文件为准），
严格匹配 B 类周期性中游寡头品种门禁评估：
1. 左侧赔率建仓门禁 (逢低布局一体化龙头龙佰集团);
2. 右侧胜率确认门禁 (龙头调价函提价 + 外需真去库 + 进攻弹性标的钛能化学);
3. 周期逃顶一票否决门禁 (寡头低 PE 陷阱与超额暴利警惕).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_analytics.pipelines.tio2.config import RegimeThresholds

_TIO2_PROFILE = "oligopoly_gate"


def load_trading_gates(path: Path | str) -> dict[str, Any]:
    """加载大宗/寡头化工周期股分阶段量化交易门禁配置。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        payload = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def evaluate_trading_gates(
    df: pl.DataFrame,
    company_panel: pl.DataFrame | None,
    gates_cfg: dict[str, Any],
    regime: RegimeThresholds | None = None,
    *,
    marginal_margin_cny: float | None = None,
    marginal_margin_desc: str | None = None,
) -> dict[str, Any]:
    """评估钛白粉当前所处的寡头量化交易门禁状态。

    ``marginal_margin_cny`` / ``marginal_margin_desc``：可选的公司边际口径
    （如钛能化学 current_spot 硫酸法单吨毛利），供左侧门禁的
    “边际产能微利/亏损”诊断使用；缺省时回退行业价差 regime 口径。
    """
    if df.is_empty() or not gates_cfg:
        return {}

    thresholds = regime or RegimeThresholds()
    latest_row = df.tail(1).to_dicts()[0]
    margin_regime = latest_row.get("margin_regime")
    flow_regime = latest_row.get("inventory_flow_regime")
    delta_spot = latest_row.get("delta_spot_price_cny")
    export_yoy = latest_row.get("export_qty_yoy")
    op_rate, op_rate_cadence = _resolve_operating_rate(df)
    destock_weeks = latest_row.get("consecutive_destock_weeks")
    destock_months = latest_row.get("consecutive_destock_months")
    monthly_survey_as_of = latest_row.get("monthly_survey_as_of")
    # 最新月（如 2026-09）尚无月频数据时，回看最近可得月频行
    if destock_months is None:
        for r in reversed(df.to_dicts()):
            value = r.get("consecutive_destock_months")
            if value is not None:
                destock_months = value
                monthly_survey_as_of = r.get("monthly_survey_as_of") or r.get("report_month")
                break
    ma20_break = latest_row.get("ma20_break")

    min_pb_10y, min_pb_abs, min_pb_sym, min_pe_ttm = _company_extremes(company_panel)

    gates = _resolve_oligopoly_gates(gates_cfg)

    left_status = _evaluate_left_side(
        latest_row,
        min_pb_10y,
        min_pb_abs,
        min_pb_sym,
        gates,
        marginal_margin_cny=marginal_margin_cny,
        marginal_margin_desc=marginal_margin_desc,
    )
    right_status = _evaluate_right_side(
        flow_regime,
        delta_spot,
        export_yoy,
        op_rate,
        op_rate_cadence,
        destock_weeks,
        destock_months,
        monthly_survey_as_of,
        ma20_break,
        min_pb_10y,
        gates,
        thresholds,
    )
    top_status = _evaluate_top_escape(
        margin_regime,
        flow_regime,
        export_yoy,
        op_rate,
        op_rate_cadence,
        min_pe_ttm,
        gates,
        thresholds,
    )

    return {
        "left_side_odds": left_status,
        "right_side_confirmation": right_status,
        "top_escape": top_status,
    }


def _resolve_oligopoly_gates(gates_cfg: dict[str, Any]) -> dict[str, Any]:
    if "left_side_odds" in gates_cfg:
        return gates_cfg
    profiles = gates_cfg.get("profiles", {})
    profile = profiles.get(_TIO2_PROFILE)
    if isinstance(profile, dict) and "left_side_odds" in profile:
        return profile
    fallback = gates_cfg.get("default_profile", "commodity_standard_gate")
    res = profiles.get(fallback, {})
    return res if isinstance(res, dict) else {}


def _company_extremes(
    company_panel: pl.DataFrame | None,
) -> tuple[float | None, float | None, str, float | None]:
    if company_panel is None or company_panel.is_empty():
        return None, None, "", None
    latest = company_panel.sort("trade_date").group_by("symbol").last()
    candidates = [
        (str(r["symbol"]), str(r["company_name"]), r["pb_percentile_10y"], r["pb"], r.get("pe_ttm"))
        for r in latest.iter_rows(named=True)
        if r.get("pb_percentile_10y") is not None
    ]
    if not candidates:
        return None, None, "", None
    candidates.sort(key=lambda item: float(item[2]))
    sym, name, pb10y, pb, pe = candidates[0]
    return (
        float(pb10y),
        (float(pb) if pb is not None else None),
        f"{name} ({sym})",
        (float(pe) if pe is not None else None),
    )


def _resolve_operating_rate(df: pl.DataFrame) -> tuple[float | None, str]:
    """最新可得开工率：优先周度调研，缺失时回退最近月频调研并标注数据月。"""
    if df.is_empty():
        return None, "周度/月度调研"
    latest_row = df.tail(1).to_dicts()[0]
    weekly = latest_row.get("operating_rate_pct")
    if weekly is not None:
        return float(weekly), "周度调研"
    for r in reversed(df.to_dicts()):
        monthly = r.get("operating_rate_pct_monthly")
        if monthly is not None:
            return float(monthly), f"月度调研({r.get('report_month')})"
    return None, "周度/月度调研"


def _evaluate_left_side(
    latest_row: dict[str, Any],
    min_pb_10y: float | None,
    min_pb_abs: float | None,
    min_pb_sym: str,
    gates: dict[str, Any],
    *,
    marginal_margin_cny: float | None = None,
    marginal_margin_desc: str | None = None,
) -> dict[str, Any]:
    left_cfg = gates.get("left_side_odds", {})
    rules = left_cfg.get("rules", {})

    # B 类寡头左侧核心条件：挂牌价止跌 + 海外边际装置停产。
    # 对应数据源（挂牌价序列/海外装置动态）尚未接入 → 显式“数据缺失-未确认”，不作已满足/已证伪处理。
    cond_listing: bool | None = None
    listing_min = rules.get("leader_listing_price_stable_months_min", 2)
    cond_listing_desc = f"寡头挂牌价止跌 ≥{listing_min} 个月: 数据未接入-未确认"

    cond_marginal: bool | None = None
    cond_marginal_desc = "海外高能耗边际装置失血停产: 数据未接入-未确认"

    # 边际产能微利/亏损（诊断条件）：优先公司边际口径（钛能化学 current_spot 硫酸法单吨毛利，
    # 随 100ppi 酸价序列校准，2026-09 已深度为负）；缺省回退行业价差 regime 口径。
    if marginal_margin_cny is not None:
        cond_loss = marginal_margin_cny < 0
        cond_loss_desc = marginal_margin_desc or (
            f"边际产能硫酸法单吨毛利: {marginal_margin_cny:.0f} 元/吨 "
            f"({'深度亏损/跌破现金保本' if cond_loss else '盈亏线上方'})"
        )
    else:
        margin_regime = latest_row.get("margin_regime")
        cond_loss = margin_regime in ("deep_loss", "near_breakeven")
        cond_loss_desc = f"边际产能微利/亏损状态: {margin_regime or '未知'} (诊断参考)"

    pb_th = float(rules.get("pb_percentile_10y_max", 0.20))
    cond_pb = False
    cond_pb_desc = (
        f"10Y PB 分位: {min_pb_10y}% ({min_pb_sym})"
        if min_pb_10y is not None
        else "10Y PB 分位: 数据缺失"
    )
    if min_pb_10y is not None and min_pb_10y <= pb_th * 100.0:
        cond_pb = True
    elif min_pb_abs is not None and min_pb_abs < 1.0:
        cond_pb = True
        cond_pb_desc += " (绝对破净 PB < 1.0)"

    confirmed = [c for c in (cond_listing, cond_marginal) if c is not None]
    triggered = bool(confirmed) and all(confirmed) and cond_pb
    return {
        "name": left_cfg.get("name", "寡头品左侧赔率建仓门禁"),
        "triggered": triggered,
        "cond_listing": cond_listing,
        "cond_listing_desc": cond_listing_desc,
        "cond_marginal": cond_marginal,
        "cond_marginal_desc": cond_marginal_desc,
        "cond_loss": cond_loss,
        "cond_loss_desc": cond_loss_desc,
        "marginal_margin_cny": marginal_margin_cny,
        "cond_pb": cond_pb,
        "cond_pb_desc": cond_pb_desc,
        "data_gaps": ["leader_listing_price_stable_months", "marginal_producer_loss"],
        "action": f"建议布局底仓 (上限 {left_cfg.get('target_position_pct_max', 35.0)}%)，首选一体化抗亏龙头 (龙佰集团)"
        if triggered
        else "左侧核心条件 (挂牌价止跌/边际装置停产) 数据未接入-未确认，暂不触发",
    }


def _evaluate_right_side(
    flow_regime: str | None,
    delta_spot: float | None,
    export_yoy: float | None,
    op_rate: float | None,
    op_rate_cadence: str,
    destock_weeks: float | None,
    destock_months: float | None,
    monthly_survey_as_of: str | None,
    ma20_break: bool | None,
    min_pb_10y: float | None,
    gates: dict[str, Any],
    thresholds: RegimeThresholds,
) -> dict[str, Any]:
    right_cfg = gates.get("right_side_confirmation", {})
    rules = right_cfg.get("rules", {})

    # 已接入数据源（代理指标）：现货环比代理“调价函提价”，周度厂库/海关出口代理“去库”。
    cond_hike = delta_spot is not None and delta_spot > 0
    cond_hike_desc = (
        f"现货/调价函提价 (现货环比代理): 环比 +{delta_spot:.1f} 元/吨"
        if cond_hike
        else f"现货/调价函提价 (现货环比代理): 环比 {delta_spot or 0:.1f} 元/吨 (未提价)"
    )

    # 去库：优先周度厂库连续去库周数；缺失时回退月频厂库连续去库月数（代理）；
    # 再回退月频出口/状态机代理
    destock_min = int(rules.get("destocking_weeks_min", 2))
    export_threshold = float(
        rules.get("demand_validation", {}).get(
            "export_volume_yoy_min", thresholds.destocking_export_yoy
        )
    )
    if destock_weeks is not None:
        cond_destock = destock_weeks >= destock_min
        cond_destock_desc = f"厂库连续去库: {destock_weeks:.0f} 周 (≥{destock_min})"
    elif destock_months is not None:
        cond_destock = destock_months >= destock_min
        cond_destock_desc = (
            f"厂库连续去库（月频代理，数据截至 {monthly_survey_as_of or '最新可得'}）: "
            f"{destock_months:.0f} 个月 (≥{destock_min})"
        )
    elif flow_regime == "genuine_terminal_destocking" or (
        export_yoy is not None and export_yoy >= export_threshold
    ):
        cond_destock = True
        cond_destock_desc = f"海关出口/终端真去库 (周度厂库缺失-月频代理): {export_yoy:.1f}%"
    else:
        cond_destock = False
        cond_destock_desc = (
            f"去库确认: 周度厂库未接入 / 出口 {export_yoy if export_yoy is not None else '--'}%"
        )

    # 开工率：周度调研优先，缺失时回退月频产能利用率（代理）
    op_rate_max = float(rules.get("operating_rate_max", 0.80))
    if op_rate is not None:
        cond_operating_rate = op_rate < op_rate_max * 100.0
        cond_operating_rate_desc = (
            f"全行业开工率: {op_rate:.1f}% ({op_rate_cadence}, <{op_rate_max:.0%})"
        )
    else:
        cond_operating_rate = None
        cond_operating_rate_desc = f"全行业开工率 <{op_rate_max:.0%}: 数据未接入-未确认"

    # MA20：日频行情已接入，缺失时显式“未确认”
    if ma20_break is not None:
        cond_ma = bool(ma20_break)
        cond_ma_desc = f"MA20 突破 (收盘>20日均线): {'是' if cond_ma else '否'}"
    else:
        cond_ma = None
        cond_ma_desc = "MA20 放量突破: 行情特征未接入-未确认"

    # 协同检修/不可抗力：仍无数据源 → 显式“未确认”，不参与触发
    cond_maintenance: bool | None = None
    cond_maintenance_desc = "寡头协同检修/不可抗力: 数据未接入-未确认"

    data_gaps = []
    if op_rate is None:
        data_gaps.append("operating_rate_max")
    if destock_weeks is None and destock_months is None:
        data_gaps.append("destocking_weeks_min")
    if ma20_break is None:
        data_gaps.append("technical_ma_break")
    data_gaps.append("oligopoly_coordinated_maintenance")
    data_gaps.append("leader_listing_price_hike")

    confirmed = [cond_hike, cond_destock, cond_operating_rate, cond_ma, cond_maintenance]
    triggered = all(c is True for c in confirmed)
    return {
        "name": right_cfg.get("name", "寡头品右侧胜率确认门禁"),
        "triggered": triggered,
        "cond_hike": cond_hike,
        "cond_hike_desc": cond_hike_desc,
        "cond_destock": cond_destock,
        "cond_destock_desc": cond_destock_desc,
        "cond_ma": cond_ma,
        "cond_ma_desc": cond_ma_desc,
        "cond_operating_rate": cond_operating_rate,
        "cond_operating_rate_desc": cond_operating_rate_desc,
        "cond_maintenance": cond_maintenance,
        "cond_maintenance_desc": cond_maintenance_desc,
        "data_gaps": data_gaps,
        "action": f"重仓进攻 (仓位上限 {right_cfg.get('target_position_pct_max', 85.0)}%)，加码高弹性标的 (钛能化学)"
        if triggered
        else "右侧胜率条件未齐 (协同检修/挂牌价提价数据未接入-未确认)，暂不触发",
    }


def _evaluate_top_escape(
    margin_regime: str | None,
    flow_regime: str | None,
    export_yoy: float | None,
    op_rate: float | None,
    op_rate_cadence: str,
    pe_ttm: float | None,
    gates: dict[str, Any],
    thresholds: RegimeThresholds,
) -> dict[str, Any]:
    top_cfg = gates.get("top_escape", {})
    rules = top_cfg.get("rules", {})

    pe_trap_max = float(rules.get("pe_ttm_low_trap_max", 14.0))

    cond_profit = margin_regime == "high_profit"
    cond_profit_desc = f"超额暴利区间: {'满足 (high_profit)' if cond_profit else '否'}"

    passive_yoy = float(thresholds.passive_export_yoy)
    cond_accum = (flow_regime == "passive_accumulation") or (
        export_yoy is not None and export_yoy < passive_yoy
    )
    cond_accum_desc = f"被动累库/外需收缩: {'是' if cond_accum else '否'}"

    cond_pe = pe_ttm is not None and 0 < pe_ttm <= pe_trap_max
    cond_pe_desc = (
        f"周期低 PE 见顶陷阱 (PE <= {pe_trap_max}x): {pe_ttm:.1f}x"
        if cond_pe
        else f"低 PE 陷阱: {pe_ttm or '--'}x (未进入)"
    )

    # 开工率：周度调研优先，缺失时回退月频产能利用率（代理）
    op_rate_min = float(rules.get("operating_rate_min", 0.92))
    if op_rate is not None:
        cond_operating_rate = op_rate > op_rate_min * 100.0
        cond_operating_rate_desc = (
            f"全球装置负荷: {op_rate:.1f}% ({op_rate_cadence}, > {op_rate_min:.0%})"
        )
    else:
        cond_operating_rate = None
        cond_operating_rate_desc = f"全球装置负荷 >{op_rate_min:.0%}: 数据未接入-未确认"

    match_count = sum(
        1 for c in (cond_profit, cond_accum, cond_pe, cond_operating_rate) if c is True
    )
    # 框架口径：满足 2 项减半离场，满足 3 项一票否决清仓（与 README/门面语义对齐）
    if match_count >= 3:
        position_action = "clear_position"
        action = "触发一票否决清仓逃顶"
    elif match_count == 2:
        position_action = "halve_position"
        action = "触发减半离场 (满足 2 项，待第 3 项确认后一票否决)"
    else:
        position_action = "hold"
        action = "未触发逃顶门禁"
    triggered = match_count >= 2

    return {
        "name": top_cfg.get("name", "寡头品逃顶一票否决门禁"),
        "triggered": triggered,
        "match_count": match_count,
        "cond_profit": cond_profit,
        "cond_profit_desc": cond_profit_desc,
        "cond_accum": cond_accum,
        "cond_accum_desc": cond_accum_desc,
        "cond_pe": cond_pe,
        "cond_pe_desc": cond_pe_desc,
        "cond_operating_rate": cond_operating_rate,
        "cond_operating_rate_desc": cond_operating_rate_desc,
        "data_gaps": ["operating_rate_min"] if op_rate is None else [],
        "position_action": position_action,
        "action": action,
    }
