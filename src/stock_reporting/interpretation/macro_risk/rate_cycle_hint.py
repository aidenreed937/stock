"""利率周期风险提示（加息/降息档位判定与文案）。

定位：**风险提示层，不是策略门**——加息腿在 270100 深研线已被正交性否决
（`semi_ffr_defense_leg.md`：与剪刀差<0/DOI≥70 防守门 99% 重叠、独有 8 天无贡献），
其价值在信息披露而非交易信号。本模块把利率周期状态转化为投资者可读的风险提示，
供宏观日报（普通版/专业版）消费。

档位判定阈值来自 `ffr_cycle_factor_research.md` 实证（2026-09）：
- 加息期：FFR 6 个月累计变化 ≥ +0.25pp（或 score ≥ 60），宽基 fwd60 中位 -3.01%/胜率 32%；
- 降息期：FFR 6 个月累计变化 ≤ -0.25pp，宽基 fwd60 中位 +3.00%/胜率 73%；
- 平台期：|变化| < 0.25pp（停加/停降附近，幅度归零 = 信号最弱区，见研究 §5 拐点效应）。

不写死策略动作，只给状态 + 实证依据 + 一句话风险提示；具体仓位决策交给策略层。
"""

from __future__ import annotations

from datetime import date

_HIKE_PP = 0.25  # FFR 6 个月累计变化 ≥ +0.25pp = 加息期（方向池 hike 门同参）
_CUT_PP = -0.25  # ≤ -0.25pp = 降息期
_SCORE_HIKE = 60.0  # ffr_chg_6m_score ≥ 60 近似加息期（宏观 hike 闸门同参）


def rate_cycle_hint(
    ffr_chg_6m: float | None,
    ffr_chg_6m_score: float | None,
    observation_date: date | None = None,
) -> dict[str, str] | None:
    """根据利率周期特征生成风险提示 dict（None = 数据全缺，不渲染）。

    Args:
        ffr_chg_6m: FRED DFF 相对六个日历月前最近观测的变化（pp，加息为正/降息为负）。
        ffr_chg_6m_score: ffr_chg_6m 的 1250 日滚动历史分位（0-100）。
        observation_date: 本次提示实际使用的 FRED DFF 日频观测日期。

    Returns:
        含 status/icon/title/text 的提示 dict；两输入均缺失时返回 None。
    """
    if ffr_chg_6m is None and ffr_chg_6m_score is None:
        return None

    # 原始 pp 优先，缺失时用 score 近似（score≥60 即加息高分位区）
    if ffr_chg_6m is not None:
        if ffr_chg_6m >= _HIKE_PP:
            return _hint("加息周期中", "🔴", ffr_chg_6m, ffr_chg_6m_score, observation_date)
        if ffr_chg_6m <= _CUT_PP:
            return _hint("降息周期中", "🟢", ffr_chg_6m, ffr_chg_6m_score, observation_date)
        return _hint("利率平台期", "🟡", ffr_chg_6m, ffr_chg_6m_score, observation_date)

    if ffr_chg_6m_score is not None and ffr_chg_6m_score >= _SCORE_HIKE:
        return _hint("加息周期中", "🔴", None, ffr_chg_6m_score, observation_date)
    return _hint("利率平台期", "🟡", None, ffr_chg_6m_score, observation_date)


def _hint(
    status: str,
    icon: str,
    ffr_chg_6m: float | None,
    ffr_chg_6m_score: float | None,
    observation_date: date | None,
) -> dict[str, str]:
    texts = {
        "加息周期中": (
            "近 6 个月美联储政策利率累计上升，历史加息期 A 股 fwd60 中位 -3.01%/胜率 32%"
            "（vs 降息期 +3.00%/73%），成长/科技估值承压；注意加息尾部最痛（2018、2023H2）。"
        ),
        "降息周期中": (
            "近 6 个月美联储政策利率累计下降，历史降息期 A 股 fwd60 中位 +3.00%/胜率 73%，"
            "流动性宽松对权益友好；但停降 = 宽松利多出尽，停降后 60 日普遍弱于降息实行期。"
        ),
        "利率平台期": (
            "6 个月利率变化趋零（停加/停降附近），幅度归零处为信号最弱区——市场交易的是"
            "边际方向变化而非方向本身；历史停加后普遍修复（2019-01 +38.1%），停降后偏弱"
            "（2019-11 -2.7% / 2025-01 -5.6%），属拐点观察区。"
        ),
    }
    detail: list[str] = []
    if ffr_chg_6m is not None:
        detail.append(f"FFR 6M {ffr_chg_6m:+.2f}pp")
    if ffr_chg_6m_score is not None:
        detail.append(f"分位 {ffr_chg_6m_score:.1f}")
    if observation_date is not None:
        detail.append(f"FRED 截至 {observation_date.isoformat()}")
    return {
        "status": status,
        "icon": icon,
        "text": texts[status],
        "detail": "；".join(detail),
    }


__all__ = ["rate_cycle_hint"]
