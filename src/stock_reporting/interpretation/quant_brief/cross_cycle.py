"""量化投研简报的跨周期胜率/赔率矩阵（方案 A）。

S=胜率环境（当下介入的确定性），O=赔率环境（上行空间与下行保护）。
轨迹修正来自市场温度历史索引，避免当日截面孤立化。
设计说明见 docs/research/cross_cycle_odds_matrix_design.md。
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import (
    CrossCycleConfig,
    QuantBriefConfig,
)
from stock_reporting.interpretation.quant_brief.helpers import (
    _as_float,
    _breadth,
    _dimension_temperatures,
    _fact_observation,
    _mapping,
    _value_text,
)
from stock_reporting.interpretation.quant_brief.odds_scores import (
    calculate_odds_parts,
    calculate_win_parts,
)

_EXTREME = "extreme"
_SYNCHRONIZED = "synchronized"


def evaluate_cross_cycle(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    *,
    market_facts: pl.DataFrame | None = None,
    history: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """评估跨周期胜率/赔率矩阵并输出象限与仓位微调。

    ``history`` 为市场温度历史索引（``index/history.parquet``），缺失时轨迹修正降级，
    S/O 当日截面部分不受影响。
    """
    matrix = config.cross_cycle
    fast_slow = _mapping(market_scores.get("fast_slow"))
    dimensions = _dimension_temperatures(market_scores)
    external = _mapping(market_scores.get("external_risk"))
    breadth = _breadth(industry_scores)
    health = _mapping(industry_scores.get("structure_health"))

    fast = _as_float(fast_slow.get("fast_temperature"))
    slow = _as_float(fast_slow.get("slow_temperature"))
    divergence = _as_float(fast_slow.get("divergence"))
    div_level = str(fast_slow.get("divergence_level") or "")
    short_5d = _short_term_temperature(market_scores, 5)
    short_10d = _short_term_temperature(market_scores, 10)
    width = _fact_observation(market_facts, "above_ma60_share")
    width_value = _as_float(width.get("value_float")) if width else None
    fund = _fact_observation(market_facts, "main_money_net_inflow_share_20d_cum")
    fund_value = _as_float(fund.get("value_float")) if fund else None
    transmission = str(external.get("transmission_status") or "")
    background_pressure = _as_float(external.get("background_pressure"))
    composite = _as_float(_mapping(market_scores.get("composite")).get("temperature"))
    macro_liquidity = dimensions.get("macro_liquidity")
    valuation = dimensions.get("valuation")
    diffusion_60d = _as_float(breadth.get("positive_60d_share"))
    crowded_share = _as_float(health.get("crowded_industry_share"))

    missing: list[str] = []
    if not div_level or fast is None or slow is None or divergence is None:
        missing.append("fast_slow")
    if valuation is None or macro_liquidity is None or short_5d is None:
        missing.append("temperature")
    if diffusion_60d is None:
        missing.append("diffusion_60d")
    if not transmission or background_pressure is None:
        missing.append("external_risk")

    win_parts, win_raw = calculate_win_parts(
        matrix, div_level, fast, short_5d, width_value, fund_value, transmission
    )
    odds_parts, odds_raw = calculate_odds_parts(
        matrix, slow, valuation, diffusion_60d, crowded_share, macro_liquidity, background_pressure
    )
    trajectory, win_adj, odds_adj = _build_trajectory(
        matrix, history, str(market_scores.get("as_of_date") or "")
    )
    win_score = win_raw + win_adj
    odds_score = odds_raw + odds_adj
    win_level = _level(win_score, matrix.win_level_high, matrix.win_level_low)
    odds_level = _level(odds_score, matrix.odds_level_high, matrix.odds_level_low)
    quadrature, quadrature_label, adjustment_pp, adjustment_note = _quadrature(
        matrix, win_level, odds_level
    )

    return {
        "status": "ready" if not missing else "degraded",
        "rules_version": matrix.rules_version,
        "table": {
            "long": {
                "role": "赔率",
                "slow_temperature": slow,
                "diffusion_60d_share": diffusion_60d,
            },
            "medium": {
                "composite": composite,
                "divergence": divergence,
                "divergence_level": div_level or None,
            },
            "short": {
                "short_term_5d": short_5d,
                "short_term_10d": short_10d,
                "external": transmission or None,
            },
        },
        "win_raw": win_raw,
        "win_adj": win_adj,
        "win_score": win_score,
        "win_level": win_level,
        "win_parts": win_parts,
        "odds_raw": odds_raw,
        "odds_adj": odds_adj,
        "odds_score": odds_score,
        "odds_level": odds_level,
        "odds_parts": odds_parts,
        "quadrature": quadrature,
        "quadrature_label": quadrature_label,
        "position_adjustment_pp": adjustment_pp,
        "adjustment_note": adjustment_note,
        "trajectory": trajectory or None,
        "upgrade_triggers": [
            f"60日扩散回升至 {matrix.diffusion_low_threshold:.0f}% 以上（赔率打开）",
            "冰点背离后确认回升（高赔率窗口）",
        ],
        "missing": missing,
    }


def _short_term_temperature(market_scores: dict[str, Any], window: int) -> float | None:
    short_term = market_scores.get("short_term")
    if not isinstance(short_term, list):
        return None
    for item in short_term:
        if isinstance(item, dict) and _as_float(item.get("window")) == window:
            return _as_float(item.get("temperature"))
    return None


def _build_trajectory(
    matrix: CrossCycleConfig,
    history: pl.DataFrame | None,
    as_of_date: str,
) -> tuple[dict[str, Any], float, float]:
    """从历史索引计算背离迁移与温度方向，返回 (轨迹, 胜率修正, 赔率修正)。

    60 日扩散斜率因行业结构无历史序列，暂以慢温度 5 日变化代理（待 cycle_review 数据接入）。
    """
    if history is None or history.is_empty() or not as_of_date:
        return {}, 0.0, 0.0
    frame = history
    if "is_latest_for_date" in frame.columns:
        frame = frame.filter(pl.col("is_latest_for_date"))
    rows = (
        frame.select("as_of_date", "divergence_level", "composite_temperature", "slow_temperature")
        .sort("as_of_date")
        .to_dicts()
    )
    rows = [row for row in rows if str(row["as_of_date"])[:10] <= as_of_date]
    if len(rows) < 2:
        return {}, 0.0, 0.0
    today = rows[-1]
    prev = rows[-2]
    today_level = str(today.get("divergence_level") or "")
    prev_level = str(prev.get("divergence_level") or "")

    win_adj = 0.0
    if prev_level == _EXTREME and today_level == _SYNCHRONIZED:
        win_adj += matrix.trajectory_convergence_bonus
        transition = "extreme->synchronized 收敛确认"
    elif prev_level == _SYNCHRONIZED and today_level == _EXTREME:
        win_adj += matrix.trajectory_deterioration_penalty
        transition = "synchronized->extreme 恶化"
    else:
        transition = f"{prev_level or '-'}->{today_level or '-'}"

    window = max(2, int(matrix.composite_trend_window))
    recent = [row for row in rows[-window:] if row.get("composite_temperature") is not None]
    composites = [
        value
        for value in (_as_float(row.get("composite_temperature")) for row in recent)
        if value is not None
    ]
    direction = "insufficient"
    if len(composites) >= 2:
        if all(b > a for a, b in pairwise(composites)):
            win_adj += matrix.trajectory_rising_bonus
            direction = "up"
        elif all(b < a for a, b in pairwise(composites)):
            win_adj += matrix.trajectory_falling_penalty
            direction = "down"
        else:
            direction = "flat"

    odds_adj = 0.0
    slow_recent = [row for row in rows[-window:] if row.get("slow_temperature") is not None]
    slowness = [
        value
        for value in (_as_float(row.get("slow_temperature")) for row in slow_recent)
        if value is not None
    ]
    slow_delta = 0.0
    if len(slowness) >= 2:
        slow_delta = slowness[-1] - slowness[0]
        if slow_delta >= 0.5:
            odds_adj += matrix.trajectory_rising_bonus
        elif slow_delta <= -0.5:
            odds_adj += matrix.trajectory_falling_penalty

    return (
        {
            "divergence_transition": transition,
            "d5_composite_direction": direction,
            "slow_5d_delta_pp": round(slow_delta, 2),
            "prev_divergence_level": prev_level,
            "today_divergence_level": today_level,
        },
        win_adj,
        odds_adj,
    )


def _level(score: float, high_threshold: float, low_threshold: float) -> str:
    if score >= high_threshold:
        return "高"
    if score <= low_threshold:
        return "低"
    return "中"


def _quadrature(
    matrix: CrossCycleConfig,
    win_level: str,
    odds_level: str,
) -> tuple[str, str, float, str]:
    """按 S/O 档位判定象限与仓位微调。"""
    if odds_level == "高" and win_level == "高":
        return (
            "core",
            "O 高+S 高：底部确认共振",
            matrix.adj_core_pp,
            "核心仓上限，正常配置，可到档位上限",
        )
    if odds_level == "高" and win_level == "低":
        return "left", "O 高+S 低：左侧/冰点窗口", matrix.adj_left_pp, "试错仓/分批，等确认再加"
    if odds_level == "低" and win_level == "高":
        return (
            "band",
            "O 低+S 高：短线强、中期未确认",
            matrix.adj_band_pp,
            "只做确认后波段，不按趋势反转配置",
        )
    if odds_level == "低" and win_level == "低":
        return (
            "avoid",
            "O 低+S 低：高位+方向未确认",
            matrix.adj_avoid_pp,
            "回避或大幅降仓，现金等待",
        )
    return "standard", "O 中或 S 中：标准档", 0.0, "按当前仓位档位执行"


def _score_text(score: float | None) -> str:
    return "-" if score is None else f"{score:.2f}"


def cross_cycle_summary(cross_cycle: dict[str, Any]) -> str:
    """生成矩阵的一行摘要文本（供 md 模板使用）。"""
    if not isinstance(cross_cycle, dict) or not cross_cycle:
        return "跨周期矩阵缺失。"
    return (
        f"胜率环境 {cross_cycle.get('win_level', '不可判定')}（"
        f"原始 {_score_text(cross_cycle.get('win_raw'))} → 修正后 {_score_text(cross_cycle.get('win_score'))}）；"
        f"赔率环境 {cross_cycle.get('odds_level', '不可判定')}（"
        f"原始 {_score_text(cross_cycle.get('odds_raw'))} → 修正后 {_score_text(cross_cycle.get('odds_score'))}）；"
        f"象限 {cross_cycle.get('quadrature_label', '-')}；仓位微调 {_value_text(cross_cycle.get('position_adjustment_pp'))}pp。"
    )


__all__ = [
    "cross_cycle_summary",
    "evaluate_cross_cycle",
]
