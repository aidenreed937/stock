"""PTA / 聚酯大炼化周期股分阶段量化交易门禁评估引擎。

配置源为品种级唯一维护文件 ``config/industry/chemicals/pta/trading_gates.yaml``，
遵循 A 类大宗标准化与期货品种门禁规则 (commodity_standard_gate)：
1. 左侧赔率建仓门禁 (加工费跌穿现金保本、破净分位、首选 alpha_leader 恒力石化);
2. 右侧胜率确认门禁 (装置集中检修、仓单连续去库、基差转升水、出口放量、加码 beta_elastic 桐昆股份);
3. 周期顶部一票否决逃顶门禁 (开工率高位钝化、加工费超额暴利、大炼化个位数低 PE 陷阱)。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl
import yaml

logger = logging.getLogger(__name__)

DEFAULT_GATES_CONFIG_PATH = Path("config/industry/chemicals/pta/trading_gates.yaml")


def load_trading_gates(config_path: Path | str | None = None) -> dict[str, Any]:
    """加载交易门禁配置。"""
    p = Path(config_path) if config_path else DEFAULT_GATES_CONFIG_PATH
    if not p.exists():
        logger.warning(f"交易门禁配置文件不存在: {p}")
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        # 兼容 profiles 结构
        if "profiles" in data and "commodity_standard_gate" in data["profiles"]:
            return dict(data["profiles"]["commodity_standard_gate"])
        return data
    except Exception as exc:
        logger.warning(f"加载交易门禁配置失败: {exc}")
        return {}


def evaluate_trading_gates(
    panorama_df: pl.DataFrame,
    company_panel: pl.DataFrame | None = None,
    gates_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行分阶段量化交易门禁评估。"""
    cfg = gates_config or load_trading_gates()
    if panorama_df.is_empty():
        return {
            "overall_regime": "neutral",
            "recommended_action": "wait_and_see",
            "active_gates": [],
            "gate_details": {},
        }

    latest_row = panorama_df.tail(1).to_dicts()[0]
    curr_margin_regime = str(latest_row.get("margin_regime", "neutral"))
    curr_flow_regime = str(latest_row.get("inventory_flow_regime", "neutral"))
    curr_basis_rate = latest_row.get("basis_rate_pct")
    curr_scissors = latest_row.get("scissors_spread_yoy")
    curr_export_yoy = latest_row.get("polyester_export_yoy")

    # 1. 评估左侧赔率门禁
    left_cfg = cfg.get("left_side_odds", {})
    left_rules = left_cfg.get("rules", {})
    margin_any = left_rules.get("margin_regime_any", ["deep_loss", "near_breakeven"])
    left_margin_triggered = curr_margin_regime in margin_any

    left_val_triggered = False
    if company_panel is not None and not company_panel.is_empty():
        # 检查 alpha_leader 是否破净或处于低 PB 分位
        hl = company_panel.filter(pl.col("symbol") == "600346.SH").sort("trade_date").tail(1)
        if not hl.is_empty():
            pb = hl.get_column("pb")[0]
            pb_pct = (
                hl.get_column("pb_percentile_10y")[0] if "pb_percentile_10y" in hl.columns else None
            )
            pb_max = float(left_rules.get("pb_absolute_max", 0.85))
            pct_max = float(left_rules.get("pb_percentile_10y_max", 0.15)) * 100.0
            if (pb is not None and pb <= pb_max) or (pb_pct is not None and pb_pct <= pct_max):
                left_val_triggered = True

    left_triggered = left_margin_triggered and (
        left_val_triggered or curr_margin_regime == "deep_loss"
    )

    # 2. 评估右侧胜率门禁
    right_cfg = cfg.get("right_side_confirmation", {})
    right_rules = right_cfg.get("rules", {})
    basis_ok = curr_basis_rate is not None and curr_basis_rate >= float(
        right_rules.get("basis_rate_min", 0.0)
    )
    destock_ok = curr_flow_regime in ["genuine_terminal_destocking", "active_destocking"]
    demand_ok = (curr_scissors is not None and curr_scissors > 0) or (
        curr_export_yoy is not None and curr_export_yoy >= 15.0
    )
    right_triggered = basis_ok and destock_ok and demand_ok

    # 3. 评估周期顶部一票否决逃顶门禁
    top_cfg = cfg.get("top_escape", {})
    top_rules = top_cfg.get("rules", {})
    high_profit_triggered = curr_margin_regime == "high_profit"
    passive_inv_triggered = curr_flow_regime == "passive_accumulation"

    pe_trap_triggered = False
    if company_panel is not None and not company_panel.is_empty():
        latest_cp = company_panel.sort("trade_date").group_by("symbol").last()
        pe_max = float(top_rules.get("pe_ttm_low_trap_max", 8.0))
        for r in latest_cp.iter_rows(named=True):
            pe = r.get("pe_ttm")
            if pe is not None and 0 < pe <= pe_max:
                pe_trap_triggered = True
                break

    top_signals = [high_profit_triggered, passive_inv_triggered, pe_trap_triggered]
    top_score = sum(1 for s in top_signals if s)
    top_triggered = top_score >= 2

    # 决策汇总
    active_gates: list[str] = []
    if top_triggered:
        overall = "top_escape"
        rec_action = "clear_position"
        active_gates.append("top_escape")
    elif right_triggered:
        overall = "right_side_bull"
        rec_action = "heavy_position_attack"
        active_gates.append("right_side_confirmation")
    elif left_triggered:
        overall = "left_side_bottom"
        rec_action = "light_position_build"
        active_gates.append("left_side_odds")
    else:
        overall = "neutral_monitoring"
        rec_action = "wait_and_see"

    return {
        "overall_regime": overall,
        "recommended_action": rec_action,
        "active_gates": active_gates,
        "latest_month": latest_row.get("report_month"),
        "gate_details": {
            "left_side_odds": {
                "triggered": left_triggered,
                "margin_triggered": left_margin_triggered,
                "valuation_triggered": left_val_triggered,
                "target": "600346.SH (恒力石化)",
                "max_position_pct": 30.0,
            },
            "right_side_confirmation": {
                "triggered": right_triggered,
                "basis_confirmed": basis_ok,
                "destocking_confirmed": destock_ok,
                "demand_confirmed": demand_ok,
                "target": "601233.SH (桐昆股份)",
                "max_position_pct": 80.0,
            },
            "top_escape": {
                "triggered": top_triggered,
                "high_profit": high_profit_triggered,
                "passive_accumulation": passive_inv_triggered,
                "pe_trap": pe_trap_triggered,
                "action": "clear_position",
            },
        },
    }
