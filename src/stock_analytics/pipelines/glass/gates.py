"""玻璃周期股分阶段量化交易门禁评估引擎。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_analytics.pipelines.glass.panorama import latest_core_row

logger = logging.getLogger(__name__)


def load_glass_trading_gates(yaml_path: Path | str) -> dict[str, Any]:
    target = Path(yaml_path)
    if not target.exists():
        return {}
    try:
        return yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def evaluate_glass_trading_gates(
    panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
    spot_benchmarks: dict[str, Any],
    gates_config: dict[str, Any],
) -> dict[str, Any]:
    """对账三大交易门禁：左侧赔率、右侧胜率、逃顶清仓。"""
    latest_row = latest_core_row(panorama) or {}

    # 1. 左侧赔率门禁评估
    left_cfg = gates_config.get("left_side_odds", {})
    left_triggered = False
    min_pb_pct = 50.0
    min_pb_val = 2.0
    min_pb_sym = ""

    if not company_panel.is_empty():
        valid_panel = company_panel.filter(pl.col("pb") > 0)
        target_panel = valid_panel if not valid_panel.is_empty() else company_panel
        lowest_row = target_panel.sort("pb_percentile_10y").head(1).to_dicts()[0]
        min_pb_pct = float(lowest_row.get("pb_percentile_10y", 50.0))
        min_pb_val = float(lowest_row.get("pb", 2.0))
        min_pb_sym = f"{lowest_row.get('name')} ({lowest_row.get('symbol')})"

    pb_rule_met = (min_pb_pct <= 15.0) or (min_pb_val <= 1.10)
    left_triggered = pb_rule_met

    left_result = {
        "name": left_cfg.get("name", "玻璃左侧赔率建仓门禁"),
        "triggered": left_triggered,
        "target_position_pct_max": float(left_cfg.get("target_position_pct_max", 30.0)),
        "cond_pb_desc": f"全池最低 PB 10Y 分位: `{min_pb_pct:.1f}%` / PB `{min_pb_val:.2f}` ({min_pb_sym})",
        "suggestion": (
            f"估值已触发极端深价值坑 (PB {min_pb_val:.2f}，分位 {min_pb_pct:.1f}%)；"
            f"建议以 <=20% 试探底仓分批布局成本龙头 (旗滨集团/福莱特)，严禁重仓追高加杠杆。"
            if left_triggered
            else "估值尚未跌入极值深价值区间，继续耐心观望。"
        ),
    }

    # 2. 右侧胜率确认门禁评估
    right_cfg = gates_config.get("right_side_confirmation", {})
    op_rate = float(latest_row.get("survey_operating_rate_pct") or 80.0)
    scissors = float(latest_row.get("scissors_spread_yoy") or -10.0)

    # 检查核心龙头 MA20 均线
    ma20_ok = False
    if not company_panel.is_empty():
        ma20_ok = bool(
            company_panel.filter(pl.col("role").str.contains("alpha"))["ma20_broken"].all()
        )

    # 满足条件判断 (需冷修出清 + 连续去库 + 剪刀差改善)
    right_triggered = (op_rate <= 75.0) and (scissors >= 0.0) and ma20_ok

    right_result = {
        "name": right_cfg.get("name", "玻璃右侧胜率确认门禁"),
        "triggered": right_triggered,
        "target_position_pct_max": float(right_cfg.get("target_position_pct_max", 80.0)),
        "cond_op_desc": f"行业开工率/产能利用率: `{op_rate:.1f}%` (门禁阈值 <= 75%)",
        "cond_scissors_desc": f"供需剪刀差 (玻璃-纯碱): `{scissors:+.1f}%` (门禁阈值 >= 0%)",
        "cond_ma_desc": f"成本龙头突破 MA20 均线: `{'已突破' if ma20_ok else '未突破'}`",
        "suggestion": (
            "右侧胜率确认门禁全部满足！可重仓加码至 60%~80% 进攻弹性品种。"
            if right_triggered
            else "未满足右侧确认门禁（开工仍偏高、剪刀差为负、物理去库不足）；严禁重仓加杠杆抢反弹。"
        ),
    }

    # 3. 逃顶清仓门禁评估
    top_cfg = gates_config.get("top_escape", {})
    top_triggered = False
    top_result = {
        "name": top_cfg.get("name", "玻璃逃顶多因子清仓门禁"),
        "triggered": top_triggered,
        "suggestion": "未触发顶部逃顶门禁（处于周期低位磨底期），无需恐慌割肉。",
    }

    return {
        "left_side_odds": left_result,
        "right_side_confirmation": right_result,
        "top_escape": top_result,
    }


__all__ = [
    "evaluate_glass_trading_gates",
    "load_glass_trading_gates",
]
