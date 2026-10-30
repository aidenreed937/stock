"""大宗化工周期股分阶段量化交易门禁评估（数据驱动）。

逻辑移植自工作区既有实现（``scripts/soda_ash_mvp_pipeline.py`` 第 6 节），
配置源为品种级唯一维护文件 ``config/industry/chemicals/soda_ash/trading_gates.yaml``：
按 commodity_standard_gate 画像评估左侧赔率 / 右侧胜率 / 逃顶三门禁
（A 类通用模板见门面 ``cyclical_trading_gates.yaml``，纯碱门禁以本文件为准）。

口径说明（与 trading_gates.yaml 注释一一对应）：

- 全景表为月频，右侧「连续去库」按期（月）计数，下限取
  ``right_side_confirmation.rules.destocking_weeks_min``；
- 逃顶门禁为多因子投票制：命中 ``top_escape.rules.trigger_match_count_min`` 即
  清仓、命中 ``warning_match_count_min`` 仅预警，并非单条件一票否决；
- 左侧赔率门禁的估值条件按「个股或行业 PB」口径取全标的池最小值，同时单独对账
  门禁指定角色（``preferred_target_role``）自身估值，避免出现「用 beta 标的的低 PB
  触发、却建议买入 alpha 龙头」的口径矛盾。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_analytics.pipelines.soda_ash.panorama import latest_core_row

_DEFAULT_PROFILE = "commodity_standard_gate"


@dataclass(frozen=True, slots=True)
class _ValuationExtremes:
    """标的池估值极值与均线状态（区分全池口径与门禁指定角色口径）。"""

    universe_min_pb_10y: float | None = None
    universe_min_pb_abs: float | None = None
    universe_symbol: str = ""
    role_min_pb_10y: float | None = None
    role_min_pb_abs: float | None = None
    role_symbol: str = ""
    min_pe_ttm: float | None = None
    ma20_break: bool | None = None


def load_trading_gates(path: Path | str) -> dict[str, Any]:
    """加载大宗化工周期股分阶段量化交易门禁配置。"""
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
    spot_benchmark: dict[str, Any] | None,
    gates_cfg: dict[str, Any],
) -> dict[str, Any]:
    """评估周期股当前所处的量化交易门禁状态。"""
    if df.is_empty() or not gates_cfg:
        return {}

    latest_row = latest_core_row(df)
    if latest_row is None:
        return {}

    margin_regime = latest_row.get("margin_regime")
    op_rate = latest_row.get("survey_operating_rate_pct")
    flow_regime = latest_row.get("inventory_flow_regime")
    scissors_spread_yoy = latest_row.get("scissors_spread_yoy")
    export_qty_yoy = latest_row.get("export_qty_yoy")

    # 统计历史连续去库期数
    consecutive_destock = _count_consecutive_destock(df)

    basis_rate = None
    if spot_benchmark:
        basis_rate = spot_benchmark.get("basis_rate_pct")
    if basis_rate is None and "basis_rate_month_end" in latest_row:
        basis_rate = latest_row.get("basis_rate_month_end")

    gates = _resolve_gates(gates_cfg)
    right_rules = gates.get("right_side_confirmation", {}).get("rules", {})
    left_rules = gates.get("left_side_odds", {}).get("rules", {})
    target_mapping = gates_cfg.get("target_universe_mapping", {})

    right_symbols = _role_symbols(target_mapping, right_rules.get("preferred_target_role"))
    left_symbols = _role_symbols(target_mapping, left_rules.get("preferred_target_role"))

    ext = _company_extremes(
        company_panel,
        ma20_symbols=right_symbols or ["600328.SH", "000707.SZ", "000683.SZ"],
        role_symbols=left_symbols,
    )

    left_status = _evaluate_left_side(latest_row, ext, gates)
    right_status = _evaluate_right_side(
        op_rate=op_rate,
        flow_regime=flow_regime,
        consecutive_destock=consecutive_destock,
        basis_rate=basis_rate,
        scissors_spread_yoy=scissors_spread_yoy,
        export_qty_yoy=export_qty_yoy,
        min_pb_10y=ext.universe_min_pb_10y,
        ma20_break=ext.ma20_break,
        report_month=latest_row.get("report_month"),
        margin_regime=margin_regime,
        gates=gates,
    )
    top_status = _evaluate_top_escape(
        op_rate=op_rate,
        margin_regime=margin_regime,
        flow_regime=flow_regime,
        min_pe_ttm=ext.min_pe_ttm,
        min_pb_10y=ext.universe_min_pb_10y,
        scissors_spread_yoy=scissors_spread_yoy,
        export_qty_yoy=export_qty_yoy,
        gates=gates,
    )

    return {
        "as_of_month": latest_row.get("report_month"),
        "left_side_odds": left_status,
        "right_side_confirmation": right_status,
        "top_escape": top_status,
    }


def _role_symbols(target_mapping: dict[str, Any], role: Any) -> list[str]:
    if not isinstance(role, str) or not role:
        return []
    return [
        str(item["symbol"])
        for item in target_mapping.get(role, [])
        if isinstance(item, dict) and "symbol" in item
    ]


def _resolve_gates(gates_cfg: dict[str, Any]) -> dict[str, Any]:
    if "left_side_odds" in gates_cfg:
        return gates_cfg
    profiles = gates_cfg.get("profiles", {})
    default_pname = gates_cfg.get("default_profile", _DEFAULT_PROFILE)
    profile = profiles.get(default_pname, gates_cfg.get("gates", {}))
    if isinstance(profile, dict) and "left_side_odds" in profile:
        return profile
    fallback = gates_cfg.get("gates", {})
    return fallback if isinstance(fallback, dict) else {}


def _count_consecutive_destock(df: pl.DataFrame) -> int:
    """统计最近连续去库期数（厂库下降 或 交易所仓单下降 视为去库）。"""
    count = 0
    frame = df.sort("report_month") if "report_month" in df.columns else df
    for row in reversed(frame.to_dicts()):
        deltas = [
            float(value)
            for value in (
                row.get("delta_factory_inv_w_tons"),
                row.get("delta_warehouse_receipt"),
            )
            if value is not None
        ]
        if not deltas or min(deltas) >= 0:
            break
        count += 1
    return count


def _company_extremes(
    company_panel: pl.DataFrame | None,
    ma20_symbols: list[str] | None = None,
    role_symbols: list[str] | None = None,
) -> _ValuationExtremes:
    """提取标的池估值极值、门禁指定角色估值极值与 MA20 突破状态。"""
    if company_panel is None or company_panel.is_empty():
        return _ValuationExtremes()

    latest = company_panel.sort("trade_date").group_by("symbol").last()
    candidates = [
        (
            str(r["symbol"]),
            str(r.get("company_name", r["symbol"])),
            r.get("pb_percentile_10y"),
            r.get("pb"),
            r.get("pe_ttm"),
        )
        for r in latest.iter_rows(named=True)
        if r.get("pb_percentile_10y") is not None
    ]

    universe_min_pb_10y, universe_min_pb_abs, universe_symbol = _cheapest_pb(candidates)

    role_candidates = (
        [item for item in candidates if item[0] in set(role_symbols)] if role_symbols else []
    )
    role_min_pb_10y, role_min_pb_abs, role_symbol = _cheapest_pb(role_candidates)

    min_pe_ttm = None
    positive_pes = [
        float(item[4]) for item in candidates if item[4] is not None and float(item[4]) > 0
    ]
    if positive_pes:
        min_pe_ttm = min(positive_pes)

    return _ValuationExtremes(
        universe_min_pb_10y=universe_min_pb_10y,
        universe_min_pb_abs=universe_min_pb_abs,
        universe_symbol=universe_symbol,
        role_min_pb_10y=role_min_pb_10y,
        role_min_pb_abs=role_min_pb_abs,
        role_symbol=role_symbol,
        min_pe_ttm=min_pe_ttm,
        ma20_break=_detect_ma20_break(company_panel, ma20_symbols),
    )


def _cheapest_pb(
    candidates: list[tuple[str, str, Any, Any, Any]],
) -> tuple[float | None, float | None, str]:
    """返回候选池中 PB 10Y 分位最低的 (分位, 绝对 PB, 展示名)。"""
    if not candidates:
        return None, None, ""
    ordered = sorted(candidates, key=lambda item: float(item[2]))
    sym, name, pb10y, pb, _ = ordered[0]
    return float(pb10y), (float(pb) if pb is not None else None), f"{name} ({sym})"


def _detect_ma20_break(
    company_panel: pl.DataFrame,
    target_symbols: list[str] | None,
) -> bool | None:
    """判定标的池是否出现收盘价站上 MA20（放量确认待成交量接入后补充）。"""
    if "ma20_break" in company_panel.columns:
        val = company_panel.get_column("ma20_break").tail(1).item()
        return bool(val) if val is not None else None
    if "close" not in company_panel.columns or "symbol" not in company_panel.columns:
        return None

    syms = target_symbols or ["600328.SH", "000707.SZ", "000683.SZ"]
    sub = company_panel.filter(pl.col("symbol").is_in(syms)).sort(["symbol", "trade_date"])
    breaks: list[bool] = []
    for _sym, group in sub.group_by("symbol", maintain_order=True):
        if group.height < 20:
            continue
        closes = [c for c in group.get_column("close").to_list() if c is not None]
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20.0
            breaks.append(closes[-1] > ma20)
    return any(breaks) if breaks else None


def _evaluate_left_side(
    latest_row: dict[str, Any],
    ext: _ValuationExtremes,
    gates: dict[str, Any],
) -> dict[str, Any]:
    left_cfg = gates.get("left_side_odds", {})
    left_rules = left_cfg.get("rules", {})
    margin_regime = latest_row.get("margin_regime")

    allowed_margins = left_rules.get("margin_regime_any", ["deep_loss", "near_breakeven"])
    cond_margin = margin_regime in allowed_margins
    pb_thresh = float(left_rules.get("pb_percentile_10y_max", 0.15))
    pb_thresh_pct = pb_thresh * 100.0 if pb_thresh <= 1.0 else pb_thresh
    pb_abs_thresh = float(left_rules.get("pb_absolute_max", 0.85))

    cond_pb = _pb_qualifies(
        ext.universe_min_pb_10y, ext.universe_min_pb_abs, pb_thresh_pct, pb_abs_thresh
    )
    cond_role_pb = _pb_qualifies(
        ext.role_min_pb_10y, ext.role_min_pb_abs, pb_thresh_pct, pb_abs_thresh
    )
    triggered = cond_margin and cond_pb

    if triggered and cond_role_pb:
        suggestion = (
            f"满足左侧赔率建仓门禁，建议建立 20%~30% 底仓，优先布局 {ext.role_symbol}，"
            "严禁重仓或加杠杆"
        )
    elif triggered:
        suggestion = (
            f"估值条件由 {ext.universe_symbol} 触发，但门禁指定角色 "
            f"{ext.role_symbol or '--'} 自身 PB 未达 <={pb_thresh_pct:.0f}% 分位或破净 "
            f"{pb_abs_thresh:.2f}；建议仅以 20% 以内试探底仓参与，严禁重仓或加杠杆"
        )
    else:
        suggestion = "未满足左侧建仓门禁"

    report_month = latest_row.get("report_month")
    month_int: int | None = None
    if report_month:
        try:
            month_int = int(str(report_month).split("-")[1])
        except (IndexError, ValueError):
            month_int = None

    seasonal_guidance = left_rules.get("seasonal_guidance", {})
    optimal_months = [int(m) for m in seasonal_guidance.get("optimal_entry_window", [])]
    cond_seasonal_desc = None
    if month_int is not None and optimal_months:
        if month_int in optimal_months:
            cond_seasonal_desc = (
                f"季节性建仓窗口: `{month_int}月`（处于春季复工补库黄金窗口，胜率较高）"
            )
        else:
            cond_seasonal_desc = (
                f"季节性建仓窗口: `{month_int}月`（非春季最优窗口，建议控制试探底仓节奏）"
            )

    return {
        "name": left_cfg.get("name", "纯碱左侧赔率建仓门禁"),
        "triggered": triggered,
        "target_position_pct_max": left_cfg.get("target_position_pct_max", 30.0),
        "cond_margin_desc": f"理论利润状态: `{margin_regime}`",
        "cond_pb_desc": (
            f"全池最低 PB 10Y 分位: `{ext.universe_min_pb_10y:.1f}%` ({ext.universe_symbol})"
            if ext.universe_min_pb_10y is not None
            else "--"
        ),
        "cond_role_pb_desc": _role_pb_desc(ext, pb_thresh_pct, pb_abs_thresh, cond_role_pb),
        "cond_seasonal_desc": cond_seasonal_desc,
        "suggestion": suggestion,
    }


def _pb_qualifies(
    min_pb_10y: float | None,
    min_pb_abs: float | None,
    pb_thresh_pct: float,
    pb_abs_thresh: float,
) -> bool:
    return (min_pb_10y is not None and min_pb_10y <= pb_thresh_pct) or (
        min_pb_abs is not None and min_pb_abs <= pb_abs_thresh
    )


def _role_pb_desc(
    ext: _ValuationExtremes,
    pb_thresh_pct: float,
    pb_abs_thresh: float,
    qualified: bool,
) -> str:
    if ext.role_min_pb_10y is None:
        return "门禁指定角色估值: 数据未接入"
    verdict = "满足" if qualified else "未满足"
    return (
        f"门禁指定角色 ({ext.role_symbol}) 最低 PB 10Y 分位: "
        f"`{ext.role_min_pb_10y:.1f}%` / PB `{_fmt_opt(ext.role_min_pb_abs)}` → "
        f"{verdict}（阈值 <={pb_thresh_pct:.0f}% 或 PB<={pb_abs_thresh:.2f}）"
    )


def _fmt_opt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "--"


def _evaluate_right_side(
    *,
    op_rate: Any,
    flow_regime: Any,
    consecutive_destock: int,
    basis_rate: Any,
    scissors_spread_yoy: Any,
    export_qty_yoy: Any,
    min_pb_10y: float | None,
    ma20_break: bool | None,
    report_month: Any = None,
    margin_regime: Any = None,
    gates: dict[str, Any],
) -> dict[str, Any]:
    right_cfg = gates.get("right_side_confirmation", {})
    right_rules = right_cfg.get("rules", {})

    # 1. 开工率收缩
    raw_op_thresh = float(right_rules.get("operating_rate_max", 0.78))
    op_thresh = raw_op_thresh * 100.0 if raw_op_thresh <= 1.0 else raw_op_thresh
    cond_op = op_rate is not None and float(op_rate) <= op_thresh

    # 2. 真实去库确认：状态机判定为去库 且 连续去库期数达标
    destock_periods_min = int(right_rules.get("destocking_weeks_min", 3))
    is_flow_destock = flow_regime in ("genuine_terminal_destocking", "destocking")
    cond_destock = is_flow_destock and consecutive_destock >= destock_periods_min

    # 3. 基差转正
    raw_basis_min = float(right_rules.get("basis_rate_min", 0.0))
    cond_basis = basis_rate is not None and float(basis_rate) >= raw_basis_min

    # 4. 真实需求共振 (供需剪刀差转正 或 海关出口高速增长)
    demand_rules = right_rules.get("demand_validation", {})
    scissors_min = float(demand_rules.get("scissors_spread_yoy_min", 0.0))
    export_min = float(demand_rules.get("export_volume_yoy_min", 15.0))
    cond_scissors = scissors_spread_yoy is not None and float(scissors_spread_yoy) >= scissors_min
    cond_export = export_qty_yoy is not None and float(export_qty_yoy) >= export_min
    if demand_rules:
        cond_demand: bool = cond_scissors or cond_export
    else:
        cond_demand = True

    # 5. 估值天花板防护 (杜绝高位追多)
    raw_ceiling = right_rules.get("valuation_ceiling_pb_10y_max")
    if raw_ceiling is not None and min_pb_10y is not None:
        ceiling_pct = (
            float(raw_ceiling) * 100.0 if float(raw_ceiling) <= 1.0 else float(raw_ceiling)
        )
        cond_valuation = min_pb_10y <= ceiling_pct
    else:
        cond_valuation = True

    # 6. MA20 突破
    cond_ma = ma20_break is True

    # 7. 季节性过滤器与检修真伪检验 (Seasonal Filters)
    month_int: int | None = None
    if report_month:
        try:
            month_int = int(str(report_month).split("-")[1])
        except (IndexError, ValueError):
            month_int = None

    seasonal_cfg = right_rules.get("seasonal_filters", {})
    blackout_months = [int(m) for m in seasonal_cfg.get("blackout_months", [])]
    turnaround_cfg = seasonal_cfg.get("turnaround_inspection", {})
    turnaround_months = [int(m) for m in turnaround_cfg.get("months", [])]
    require_margin_loss = bool(turnaround_cfg.get("require_margin_loss", False))

    cond_seasonal = True
    cond_seasonal_desc = None
    seasonal_veto_reason = None

    if month_int is not None and seasonal_cfg:
        if month_int in blackout_months:
            cond_seasonal = False
            seasonal_veto_reason = f"处于淡季被动累库黑洞期 ({month_int}月)，一票否决右侧追高"
            cond_seasonal_desc = (
                f"季节性窗口: `{month_int}月` → **未通过** (淡季被动累库黑洞期，一票否决)"
            )
        elif month_int in turnaround_months:
            if require_margin_loss and margin_regime not in ("deep_loss", "near_breakeven"):
                cond_seasonal = False
                seasonal_veto_reason = f"处于检修月份 ({month_int}月) 但毛利处于 {margin_regime} 未亏损，判定为例行检修而非出清减产"
                cond_seasonal_desc = f"季节性检修检验: `{month_int}月` → **未通过** (毛利 `{margin_regime}` 未击穿成本，判定为常规例行检修)"
            else:
                cond_seasonal_desc = f"季节性检修检验: `{month_int}月` → **通过** (毛利 `{margin_regime}` 击穿成本，认可出清降负)"
        else:
            cond_seasonal_desc = f"季节性窗口: `{month_int}月` → **通过** (常规交易窗口)"

    triggered = bool(
        cond_op
        and cond_destock
        and cond_basis
        and cond_demand
        and cond_valuation
        and cond_ma
        and cond_seasonal
    )

    demand_desc_parts = []
    if scissors_spread_yoy is not None:
        demand_desc_parts.append(f"剪刀差 {float(scissors_spread_yoy):+.1f}%")
    if export_qty_yoy is not None:
        demand_desc_parts.append(f"出口同比 {float(export_qty_yoy):+.1f}%")
    demand_desc = " / ".join(demand_desc_parts) if demand_desc_parts else "数据未接入"

    ma_desc = (
        "MA20 突破: 已突破"
        if ma20_break is True
        else ("MA20 突破: 未突破" if ma20_break is False else "MA20 突破: 未确认/待行情")
    )

    if triggered:
        suggestion = (
            "各项指标全部共振并通过季节性验证，触发右侧胜率确认门禁，可加码至 70%~80% 重仓进攻，"
            "切换至高弹性破净标的（中盐化工、双环科技）"
        )
    elif seasonal_veto_reason:
        suggestion = f"因季节性规则拦截（{seasonal_veto_reason}），严禁重仓追高或抢跑买入"
    else:
        suggestion = (
            "未满足右侧确认门禁（装置尚未实质冷修、去库期数不足、基差未转正或未突破均线），"
            "严禁重仓追高或加杠杆抢反弹"
        )

    return {
        "name": right_cfg.get("name", "纯碱右侧胜率确认门禁"),
        "triggered": triggered,
        "target_position_pct_max": right_cfg.get("target_position_pct_max", 80.0),
        "cond_op_desc": (
            f"周度开工率: `{float(op_rate):.1f}%` (门禁阈值 <= {op_thresh:.0f}%)"
            if op_rate is not None
            else "--"
        ),
        "cond_destock_desc": (
            f"中游蓄水池: `{flow_regime}` (连续去库 {consecutive_destock} 期，"
            f"需 >= {destock_periods_min} 期)"
        ),
        "cond_basis_desc": (
            f"期现基差率: `{float(basis_rate):+.2f}%`" if basis_rate is not None else "--"
        ),
        "cond_demand_desc": f"需求共振校验: {demand_desc}",
        "cond_ma_desc": ma_desc,
        "cond_seasonal_desc": cond_seasonal_desc,
        "suggestion": suggestion,
    }


def _evaluate_top_escape(
    *,
    op_rate: Any,
    margin_regime: Any,
    flow_regime: Any,
    min_pe_ttm: float | None,
    min_pb_10y: float | None,
    scissors_spread_yoy: Any,
    export_qty_yoy: Any,
    gates: dict[str, Any],
) -> dict[str, Any]:
    top_cfg = gates.get("top_escape", {})
    top_rules = top_cfg.get("rules", {})

    # 1. 开工高位打满钝化
    raw_op_min = float(top_rules.get("operating_rate_min", 0.88))
    op_min_thresh = raw_op_min * 100.0 if raw_op_min <= 1.0 else raw_op_min
    top_op = op_rate is not None and float(op_rate) >= op_min_thresh

    # 2. 理论超额暴利
    top_margin = margin_regime == top_rules.get("spread_margin_regime", "high_profit")

    # 3. 中游逆势被动累库
    top_flow = flow_regime == top_rules.get("inventory_flow_regime", "passive_accumulation")

    # 4. 周期低 PE 见顶陷阱 (静态 PE 降至个位数诱多)
    pe_trap_max = float(top_rules.get("pe_ttm_low_trap_max", 8.0))
    top_pe = min_pe_ttm is not None and (0.0 < min_pe_ttm <= pe_trap_max)

    # 5. 期现挤仓与需求背离陷阱 (高 PB + 内外需双弱转负)
    div_cfg = top_rules.get("squeeze_trap_divergence", {})
    raw_pb_div = float(div_cfg.get("pb_percentile_10y_min", 0.60))
    pb_div_pct = raw_pb_div * 100.0 if raw_pb_div <= 1.0 else raw_pb_div
    pb_high = min_pb_10y is not None and min_pb_10y >= pb_div_pct
    scissors_max = float(div_cfg.get("scissors_spread_yoy_max", 0.0))
    export_max = float(div_cfg.get("export_volume_yoy_max", 0.0))
    scissors_neg = scissors_spread_yoy is not None and float(scissors_spread_yoy) <= scissors_max
    export_neg = export_qty_yoy is not None and float(export_qty_yoy) <= export_max
    top_divergence = pb_high and (scissors_neg or export_neg)

    flags = [bool(top_op), bool(top_margin), bool(top_flow), bool(top_pe), bool(top_divergence)]
    match_count = sum(flags)
    trigger_min = int(top_rules.get("trigger_match_count_min", 3))
    warning_min = int(top_rules.get("warning_match_count_min", 2))
    triggered = match_count >= trigger_min
    warning = match_count >= warning_min

    def _flag(value: bool) -> str:
        return "是" if value else "否"

    return {
        "name": top_cfg.get("name", "纯碱逃顶一票否决门禁"),
        "triggered": triggered,
        "warning": warning,
        "match_count": match_count,
        "trigger_match_count_min": trigger_min,
        "warning_match_count_min": warning_min,
        "cond_op_desc": (
            f"行业开工负荷打满: {_flag(bool(top_op))} (开工率 "
            f"{float(op_rate):.1f}%，阈值 >= {op_min_thresh:.0f}%)"
            if op_rate is not None
            else f"行业开工负荷打满: {_flag(bool(top_op))} (开工率数据未接入)"
        ),
        "cond_margin_desc": f"理论利润超额暴利: {_flag(bool(top_margin))} (状态 `{margin_regime}`)",
        "cond_flow_desc": f"中游逆势被动累库: {_flag(bool(top_flow))} (状态 `{flow_regime}`)",
        "cond_pe_desc": (
            f"静态低 PE 见顶陷阱: {_flag(bool(top_pe))} "
            f"(最低 PE-TTM {_fmt_opt(min_pe_ttm)}，阈值 <= {pe_trap_max:.0f}x)"
        ),
        "cond_divergence_desc": (
            f"高估值 + 内外需背离: {_flag(bool(top_divergence))} "
            f"(全池最低 PB 10Y 分位 {_fmt_opt(min_pb_10y)}%，阈值 >= {pb_div_pct:.0f}%)"
        ),
        "suggestion": (
            "⚠️ 触发逃顶多因子清仓门禁，坚决清仓离场，不参与最后一棒博弈"
            if triggered
            else (
                "⚠️ 触发顶部减半预警，建议降低仓位至 50% 以下"
                if warning
                else "未触发顶部逃顶门禁（处于周期低位/磨底期），无需恐慌割肉"
            )
        ),
    }


__all__ = ["evaluate_trading_gates", "load_trading_gates"]
