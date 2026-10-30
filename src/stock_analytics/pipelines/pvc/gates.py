"""聚氯乙烯 (PVC) 周期股分阶段量化交易门禁自动评估模块。

基于 ``config/industry/chemicals/pvc/trading_gates.yaml``：
1. 左侧赔率建仓门禁 (left_side_odds): 电石法现金成本击穿深度 + 深度破净安全边际；
2. 右侧胜率确认门禁 (right_side_confirmation): 装置实质冷修 + 基差平水修复 + 仓单去库 + 外需验证；
3. 逃顶一票否决门禁 (top_escape): 开工饱和钝化 + 静态个位数低 PE 陷阱 + 被动累库。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_GATES_PATH = Path("config/industry/chemicals/pvc/trading_gates.yaml")


@dataclass(frozen=True, slots=True)
class PVCGateRuleEvaluation:
    """单条门禁规则评估明细。"""

    rule_key: str
    rule_desc: str
    threshold: Any
    actual_value: Any
    passed: bool


@dataclass(frozen=True, slots=True)
class PVCGateStageResult:
    """单个门禁阶段 (左侧/右侧/逃顶) 判定结果。"""

    stage_name: str
    stage_title: str
    is_triggered: bool
    confidence_pct: float
    target_position_pct_max: float | None
    action_directive: str
    preferred_targets: list[str]
    rule_evaluations: list[PVCGateRuleEvaluation]


@dataclass(frozen=True, slots=True)
class PVCTradingGatesSummary:
    """PVC 完整三门禁综合诊断结果。"""

    as_of_date: str
    current_stance: str
    overall_action_advice: str
    left_side: PVCGateStageResult
    right_side: PVCGateStageResult
    top_escape: PVCGateStageResult
    target_role_mapping: dict[str, list[dict[str, str]]]


def load_pvc_trading_gates_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """读取 PVC 声明式门禁配置。"""
    p = Path(config_path or DEFAULT_GATES_PATH)
    if not p.exists():
        logger.warning("PVC 交易门禁配置文件不存在: %s", p)
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("解析 PVC 交易门禁异常: %s", exc)
        return {}


def evaluate_pvc_trading_gates(
    spot_price_cny: float,
    cash_cost_cny: float = 5100.0,
    operating_rate_pct: float | None = None,
    destocking_weeks: int = 0,
    basis_rate_pct: float | None = None,
    warehouse_w_tons: float | None = None,
    export_vol_yoy_pct: float | None = None,
    min_pb_10y_pct: float | None = None,
    min_pb_abs: float | None = None,
    pe_ttm_low: float | None = None,
    config_path: Path | str | None = None,
    as_of_date_str: str = "",
) -> PVCTradingGatesSummary:
    """执行 PVC 三门禁量化诊断。"""
    cfg = load_pvc_trading_gates_config(config_path)

    # 1. 左侧赔率门禁
    left_rules: list[PVCGateRuleEvaluation] = []

    # 现金成本击穿: 现货 <= 5100 元/吨
    is_cash_drain = spot_price_cny <= cash_cost_cny
    left_rules.append(
        PVCGateRuleEvaluation(
            rule_key="cash_cost_drain",
            rule_desc="现货跌破边际电石法现金成本 (5100元/吨)",
            threshold=f"<= {cash_cost_cny:.0f}",
            actual_value=f"{spot_price_cny:.0f}",
            passed=is_cash_drain,
        )
    )

    # PB 分位 <= 15% 或 PB < 0.85
    is_low_pb = (min_pb_10y_pct is not None and min_pb_10y_pct <= 15.0) or (
        min_pb_abs is not None and min_pb_abs < 0.85
    )
    left_rules.append(
        PVCGateRuleEvaluation(
            rule_key="pb_percentile_10y",
            rule_desc="标的 PB 处于历史 15% 极值低位或深度破净 (<0.85)",
            threshold="<= 15% 或 < 0.85",
            actual_value=f"{min_pb_abs:.2f} (分位 {min_pb_10y_pct:.1f}%)" if min_pb_abs else "N/A",
            passed=is_low_pb,
        )
    )

    left_passed = is_cash_drain and is_low_pb
    left_stage = PVCGateStageResult(
        stage_name="left_side_odds",
        stage_title="聚氯乙烯左侧赔率建仓门禁",
        is_triggered=left_passed,
        confidence_pct=100.0 if left_passed else (50.0 if (is_cash_drain or is_low_pb) else 0.0),
        target_position_pct_max=30.0,
        action_directive="建立 20%~30% 底仓，优先配置成本阿尔法抗亏龙头，严禁重仓追高",
        preferred_targets=["002092.SZ (中泰化学)", "600075.SH (新疆天业)"],
        rule_evaluations=left_rules,
    )

    # 2. 右侧胜率确认门禁
    right_rules: list[PVCGateRuleEvaluation] = []

    # 开工率 <= 75%
    is_reduced_op = operating_rate_pct is not None and operating_rate_pct <= 75.0
    right_rules.append(
        PVCGateRuleEvaluation(
            rule_key="operating_rate_max",
            rule_desc="行业周度开工率受环保或亏损跌破 75% 减产警戒线",
            threshold="<= 75.0%",
            actual_value=f"{operating_rate_pct:.1f}%" if operating_rate_pct else "N/A",
            passed=is_reduced_op,
        )
    )

    # 仓单或厂库去库 >= 3 周
    is_destocking = destocking_weeks >= 3
    right_rules.append(
        PVCGateRuleEvaluation(
            rule_key="destocking_weeks",
            rule_desc="显性仓单或企业厂库连续去化 >= 3 周",
            threshold=">= 3 周",
            actual_value=f"{destocking_weeks} 周",
            passed=is_destocking,
        )
    )

    # 基差平水或转正
    is_basis_repaired = basis_rate_pct is not None and basis_rate_pct >= 0.0
    right_rules.append(
        PVCGateRuleEvaluation(
            rule_key="basis_rate_min",
            rule_desc="期货主力基差平水或转正 (现货升水修复)",
            threshold=">= 0.0%",
            actual_value=f"{basis_rate_pct:+.2f}%" if basis_rate_pct is not None else "N/A",
            passed=is_basis_repaired,
        )
    )

    # 需求端验证 (出口同比 > 15%)
    is_demand_confirmed = export_vol_yoy_pct is not None and export_vol_yoy_pct >= 15.0
    right_rules.append(
        PVCGateRuleEvaluation(
            rule_key="export_volume_yoy",
            rule_desc="海关月度出口同比增速超 15% (海外泄洪)",
            threshold=">= 15.0%",
            actual_value=f"{export_vol_yoy_pct:+.1f}%" if export_vol_yoy_pct is not None else "N/A",
            passed=is_demand_confirmed,
        )
    )

    right_passed = is_reduced_op and is_destocking and is_basis_repaired
    right_stage = PVCGateStageResult(
        stage_name="right_side_confirmation",
        stage_title="聚氯乙烯右侧胜率确认门禁",
        is_triggered=right_passed,
        confidence_pct=round(sum(1 for r in right_rules if r.passed) / len(right_rules) * 100.0, 1),
        target_position_pct_max=80.0,
        action_directive="右侧实质反转确认，加码至 70%~80% 重仓进攻，切换至高贝塔破净弹性标的",
        preferred_targets=["600409.SH (三友化工)", "600618.SH (氯碱化工)"],
        rule_evaluations=right_rules,
    )

    # 3. 逃顶一票否决门禁
    top_rules: list[PVCGateRuleEvaluation] = []
    is_op_high = operating_rate_pct is not None and operating_rate_pct >= 86.0
    top_rules.append(
        PVCGateRuleEvaluation(
            rule_key="operating_rate_top",
            rule_desc="行业开工率超 86% 且高位钝化 (弹性打满)",
            threshold=">= 86.0%",
            actual_value=f"{operating_rate_pct:.1f}%" if operating_rate_pct else "N/A",
            passed=is_op_high,
        )
    )

    is_low_pe_trap = pe_ttm_low is not None and 0 < pe_ttm_low <= 8.0
    top_rules.append(
        PVCGateRuleEvaluation(
            rule_key="pe_ttm_low_trap",
            rule_desc="静态 PE(TTM) 降至 8 倍个位数 (周期低 PE 见顶陷阱)",
            threshold="<= 8.0x",
            actual_value=f"{pe_ttm_low:.1f}x" if pe_ttm_low else "N/A",
            passed=is_low_pe_trap,
        )
    )

    is_overhang_high = warehouse_w_tons is not None and warehouse_w_tons >= 60.0
    top_rules.append(
        PVCGateRuleEvaluation(
            rule_key="inventory_accumulation",
            rule_desc="显性库存突破 60 万吨严重被动累库红线",
            threshold=">= 60 万吨",
            actual_value=f"{warehouse_w_tons:.1f} 万吨" if warehouse_w_tons else "N/A",
            passed=is_overhang_high,
        )
    )

    top_passed = is_op_high and is_low_pe_trap
    top_stage = PVCGateStageResult(
        stage_name="top_escape",
        stage_title="聚氯乙烯逃顶一票否决门禁",
        is_triggered=top_passed,
        confidence_pct=100.0 if top_passed else 0.0,
        target_position_pct_max=0.0,
        action_directive="触发顶部逃顶一票否决，警惕景气钝化，清仓离场",
        preferred_targets=[],
        rule_evaluations=top_rules,
    )

    # 综合定调
    if top_passed:
        stance = "CLEAR_POSITION"
        advice = "触发周期顶部逃顶门禁，超额利润见顶钝化，建议清仓离场。"
    elif right_passed:
        stance = "OVERWEIGHT_RIGHT"
        advice = (
            "满足右侧胜率确认门禁，实质减产去库与基差修复共振，建议加码重仓配置三友化工/氯碱化工。"
        )
    elif left_passed:
        stance = "OVERWEIGHT_LEFT"
        advice = "满足左侧赔率建仓门禁，市价击穿边际电石现金底线，建议建立 20%~30% 底仓，布局抗亏龙头中泰化学/新疆天业。"
    else:
        stance = "NEUTRAL_WATCH"
        advice = "未满足核心买入门禁，建议保持中性跟踪观察。"

    target_mapping = cfg.get("target_universe_mapping", {})

    return PVCTradingGatesSummary(
        as_of_date=as_of_date_str,
        current_stance=stance,
        overall_action_advice=advice,
        left_side=left_stage,
        right_side=right_stage,
        top_escape=top_stage,
        target_role_mapping=target_mapping,
    )
