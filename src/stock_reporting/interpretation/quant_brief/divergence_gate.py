"""量化投研简报的快慢温度背离闸门（Phase 3）。"""

from __future__ import annotations

from typing import Any

from stock_reporting.interpretation.quant_brief.config import QuantBriefConfig
from stock_reporting.interpretation.quant_brief.helpers import (
    _as_float,
    _gate,
    _mapping,
    _value_text,
)


def evaluate_divergence_gate(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
) -> dict[str, str]:
    """评估快慢温度背离：深度背离且短线偏热为派发观察，短线冰点为底部窗口。

    门限与 scoring_risk 的 Phase 3 背离风控保持一致（61 天样本校准）：
    深度背离 |背离| >= divergence_extreme_threshold；快温度上/下沿随配置。
    冷侧只作观察窗口、不改变仓位档位（前向验证见 diagnose_temperature_divergence_gates）。
    """
    fast_slow = _mapping(market_scores.get("fast_slow"))
    fast = _as_float(fast_slow.get("fast_temperature"))
    slow = _as_float(fast_slow.get("slow_temperature"))
    divergence = _as_float(fast_slow.get("divergence"))
    if fast is None or slow is None or divergence is None:
        return _gate(
            "fast_slow_divergence",
            "快慢温度背离",
            "insufficient",
            "none",
            "快慢温度或背离事实不足。",
            "补齐市场温度快慢产物后再判断短线与慢变量的脱节程度。",
            "-",
        )
    facts = f"快温度 {_value_text(fast)}；慢温度 {_value_text(slow)}；背离 {divergence:+.2f}。"
    if (
        divergence >= config.divergence_extreme_threshold
        and fast >= config.divergence_hot_fast_temperature
    ):
        return _gate(
            "fast_slow_divergence",
            "快慢温度背离",
            "watch",
            "watch",
            "快慢深度背离且短线偏热，短线资金情绪与慢变量脱节，派发警惕窗口。",
            "收紧止盈，不追高短线热点；等待背离收敛或慢变量跟涨。",
            facts,
        )
    if (
        divergence <= -config.divergence_extreme_threshold
        and fast <= config.divergence_ice_fast_temperature
    ):
        return _gate(
            "fast_slow_divergence",
            "快慢温度背离",
            "clear",
            "none",
            "快慢深度背离且短线冰点，慢变量温和，底部反攻窗口观察。",
            "左侧布局可选低估值方向，等待短线温度回升确认。",
            facts,
        )
    return _gate(
        "fast_slow_divergence",
        "快慢温度背离",
        "clear",
        "none",
        "快慢温度未出现深度背离，综合温度读数相对可靠。",
        "按综合温度档位和其余闸门执行。",
        facts,
    )


__all__ = ["evaluate_divergence_gate"]
