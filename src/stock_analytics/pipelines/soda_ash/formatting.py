"""纯碱研报共享格式工具（数值/百分比/中文标签映射）。"""

from __future__ import annotations

from typing import Any

FLOW_REGIME_CN: dict[str, str] = {
    "speculative_transfer_risk": "疑似投机移库 (囤货预警)",
    "genuine_terminal_destocking": "真实刚需去库 (健康)",
    "passive_accumulation": "被动累库胀库 (承压)",
    "active_destocking": "主动减产去库 (筑底)",
    "balanced_neutral": "产销紧平衡 (中性)",
    "neutral": "中性平稳",
    "--": "--",
}

PROCESS_TYPE_CN: dict[str, str] = {
    "natural_alkali": "天然碱法",
    "solvay_process": "氨碱法",
    "solvay_and_hou": "氨碱+联碱",
    "hou_process": "联碱法",
}


def _flow_cn(value: Any) -> str:
    if value is None:
        return "--"
    return FLOW_REGIME_CN.get(str(value), str(value))


def _flow_comment(value: Any) -> str:
    if value == "speculative_transfer_risk":
        return "\n  - ⚠️ **中游蓄水池预警**: 厂库虽显性去化，但期货深度升水且仓单逆势累积，疑似货物流向中游社会仓储与套利盘。"
    if value == "genuine_terminal_destocking":
        return "\n  - 💡 **去库健康**: 生产端顺畅去化且基差稳健，下游刚需正常接单消耗。"
    if value == "passive_accumulation":
        return "\n  - ⚠️ **累库承压**: 样本厂库增加且出货率低于 97%，下游拿货谨慎。"
    return ""


def _process_cn(value: Any) -> str:
    if value is None:
        return "--"
    return PROCESS_TYPE_CN.get(str(value), str(value))


def _fmt_pct(val: Any) -> str:
    if val is None:
        return "--"
    try:
        return f"{float(val):+.1f}%"
    except (ValueError, TypeError):
        return "--"


def _fmt_val(val: Any, prec: int = 1) -> str:
    if val is None:
        return "--"
    try:
        return f"{float(val):.{prec}f}"
    except (ValueError, TypeError):
        return "--"


def _fmt_amt(val: Any, *, signed: bool = False) -> str:
    if val is None:
        return "--"
    try:
        number = float(val) / 1e8
    except (ValueError, TypeError):
        return "--"
    return f"{number:+.2f}" if signed else f"{number:.1f}"


def _fmt_imp(val: Any) -> str:
    if val is None:
        return "--"
    try:
        return f"{float(val) / 1e4:+.0f}"
    except (ValueError, TypeError):
        return "--"


def _fmt_share(val: Any) -> str:
    if val is None:
        return "--"
    try:
        return f"{float(val) * 100:.1f}%"
    except (ValueError, TypeError):
        return "--"


__all__ = [
    "FLOW_REGIME_CN",
    "PROCESS_TYPE_CN",
    "_flow_cn",
    "_flow_comment",
    "_fmt_amt",
    "_fmt_imp",
    "_fmt_pct",
    "_fmt_share",
    "_fmt_val",
    "_process_cn",
]
