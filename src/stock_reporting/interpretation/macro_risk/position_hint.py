"""恐慌极值的位置风险提示（识别「假冰点」）。

依据：全样本复算 Panic>75 触发时距前120日高点回撤决定后验——回撤>30% 的 16 次
后60日胜率100%、均收益+19.95%；回撤<5% 的 3 次全败。阈值来自
config/reporting/macro_risk_thresholds.yaml 的 indices.panic。
"""

from __future__ import annotations

from typing import Any


def dd_position_hint(dd_from_high: float, cfg: dict[str, Any]) -> str:
    """按基准距前 120 交易日高点回撤生成恐慌极值的位置风险提示。"""
    panic_cfg = cfg.get("indices", {}).get("panic", {})
    dd_deep = float(panic_cfg.get("dd_confirm_deep", -0.20))
    dd_shallow = float(panic_cfg.get("dd_warn_shallow", -0.10))
    dd_pct = dd_from_high * 100.0
    if dd_from_high <= dd_deep:
        return (
            f"\n\n> ✅ **深底确认**：基准距前 120 日高点已回撤 {dd_pct:.0f}%，"
            "Panic 极值可信度高（历史同类后 60 日胜率近 100%、均收益约 +20%），"
            "左侧抄底符合「真冰点」特征。"
        )
    if dd_from_high > dd_shallow:
        return (
            f"\n\n> 🚨 **假冰点预警**：基准距前 120 日高点仅回撤 {dd_pct:.0f}%，"
            "Panic 极值可能由「60 日新高占比」等滞后指标虚高，"
            "属高位/中继恐慌而非深底，接飞刀风险显著偏高，"
            "按纪律执行但需知悉可能继续下探。"
        )
    return (
        f"\n\n> ⚠️ **中继风险**：基准距前 120 日高点回撤 {dd_pct:.0f}%，"
        "处中级调整区（历史同类后 60 日胜率约 60~67%），"
        "分批建仓优于一次性满仓。"
    )


__all__ = ["dd_position_hint"]
