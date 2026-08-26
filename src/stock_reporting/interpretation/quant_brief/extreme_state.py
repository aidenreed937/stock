"""量化投研简报的极端状态窗口原语（可靠路线 L2）。

三类高可靠信号窗口：高温、冰点、拥挤。61 天实证依据见
docs/research/extreme_state_route_design.md：高温后 fwd5 0% 正、冰点背离后回归、拥挤=高波。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import QuantBriefConfig
from stock_reporting.interpretation.quant_brief.helpers import (
    _as_float,
    _composite_temperature,
    _mapping,
    _panel_rows,
    _value_text,
)


def evaluate_extreme_state(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
    industry_panel: pl.DataFrame,
) -> dict[str, Any]:
    """评估高温/冰点/拥挤三类极端状态窗口，输出纪律偏置与动作。

    窗口可并存；hot 优先于 frozen（同一时刻互斥保护）；crowded 只做行业回避、不改总仓。
    偏置叠加取最负，不突破硬闸门档位（由 position_policy 约束，本函数不消费）。
    """
    composite = _composite_temperature(market_scores)
    fast_slow = _mapping(market_scores.get("fast_slow"))
    fast = _as_float(fast_slow.get("fast_temperature"))
    divergence = _as_float(fast_slow.get("divergence"))

    hot = composite is not None and composite > config.extreme_hot_threshold
    ice_divergence = (
        divergence is not None
        and fast is not None
        and divergence <= -config.divergence_extreme_threshold
        and fast <= config.divergence_ice_fast_temperature
    )
    frozen = (composite is not None and composite < config.extreme_cold_threshold) or ice_divergence
    if hot and frozen:
        frozen = False

    crowded_names = _crowded_hard_industries(industry_panel, config)

    missing: list[str] = []
    if composite is None or fast is None or divergence is None:
        missing.append("temperature")

    windows: list[str] = []
    if hot:
        windows.append("hot_window")
    if frozen:
        windows.append("frozen_window")
    if crowded_names:
        windows.append("crowded_window")

    if hot:
        bias = config.extreme_bias_hot_pp
        rank = "hot"
    elif frozen:
        bias = config.extreme_bias_frozen_pp
        rank = "frozen"
    else:
        bias = 0.0
        rank = "crowded_only" if crowded_names else "normal"

    action_parts: list[str] = []
    if hot:
        action_parts.append(
            f"高温窗口：综合 {_value_text(composite)}，只减不加、不新开仓（偏置 {config.extreme_bias_hot_pp:+.0f}pp）。"
        )
    if frozen:
        action_parts.append(
            f"冰点窗口：综合 {_value_text(composite)}（或冰点背离），左侧分批、等快温回升确认"
            f"（偏置 {config.extreme_bias_frozen_pp:+.0f}pp）。"
        )
    if crowded_names:
        action_parts.append(
            f"拥挤窗口：{len(crowded_names)} 个行业达硬阈值（{'、'.join(crowded_names)}），一票否决回避，总仓不变。"
        )
    if not action_parts:
        action_parts.append("无极端状态窗口，按温度档位纪律执行。")

    return {
        "status": "ready" if not missing else "degraded",
        "rules_version": config.extreme_rules_version,
        "windows": windows,
        "hot_window": {
            "triggered": hot,
            "composite": composite,
            "threshold": config.extreme_hot_threshold,
        },
        "frozen_window": {
            "triggered": frozen,
            "composite": composite,
            "threshold": config.extreme_cold_threshold,
            "ice_divergence": ice_divergence,
        },
        "crowded_window": {
            "triggered": bool(crowded_names),
            "crowded_count": len(crowded_names),
            "crowded_industries": crowded_names,
        },
        "composite_window_rank": rank,
        "position_bias_pp": bias,
        "action": " ".join(action_parts),
        "missing": missing,
    }


def _crowded_hard_industries(
    panel: pl.DataFrame,
    config: QuantBriefConfig,
) -> list[str]:
    """按硬阈值（拥挤温度 >= hard 或 TCR >= hard）筛选拥挤行业。"""
    names: list[str] = []
    for row in _panel_rows(panel):
        if row.get("status") != "ok":
            continue
        crowding = _as_float(row.get("crowding_temperature"))
        tcr = _as_float(row.get("tcr"))
        if (crowding is not None and crowding >= config.industry_crowding_hard_temperature) or (
            tcr is not None and tcr >= config.industry_tcr_hard
        ):
            names.append(str(row.get("industry_name") or row.get("industry_code") or ""))
    return names


def extreme_state_summary(extreme_state: dict[str, Any]) -> str:
    """生成极端状态窗口的一行摘要文本（供 md 模板使用）。"""
    if not isinstance(extreme_state, dict) or not extreme_state:
        return "极端状态窗口缺失。"
    windows = extreme_state.get("windows")
    rank = extreme_state.get("composite_window_rank")
    windows_text = "、".join(windows) if windows else "无"
    return (
        f"极端状态窗口：{windows_text}（rank={rank}）；仓位偏置 "
        f"{_value_text(extreme_state.get('position_bias_pp'))}pp；{extreme_state.get('action', '')}"
    )


__all__ = ["evaluate_extreme_state", "extreme_state_summary"]
