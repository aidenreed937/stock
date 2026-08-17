"""行业结构主线分类、结构雷达与节奏评估器。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stock_reporting.interpretation.industry_structure.helpers import (
    _as_float,
    _industry_list,
    _industry_name,
    _panel_rows,
    _top_rows,
    evaluate_breadth_comment,
    has_fund_flow_pressure,
    has_weak_fundamental,
    is_fund_flow_confirmed,
    is_high_dividend,
)

if TYPE_CHECKING:
    import polars as pl


def evaluate_one_line_summary(scores: dict[str, Any]) -> str:
    """生成行业结构一句话结论。"""
    top = scores.get("top_structure", [])
    crowded = scores.get("crowded_risk", [])
    lagging = scores.get("lagging_or_weak", [])
    if not top:
        return "行业结构暂不可判定，需要先补齐核心行情事实。"
    top_names = _names(top[:3])
    crowded_names = _names(crowded[:3])
    lagging_names = _names(lagging[:3])
    return (
        f"结构领先: {top_names}；拥挤观察: {crowded_names}；"
        f"落后方向: {lagging_names}。须与市场温度交叉验证。"
    )


def evaluate_key_takeaways(industry_panel: pl.DataFrame, scores: dict[str, Any]) -> list[str]:
    """生成行业结构核心研判摘要。"""
    rows = _panel_rows(industry_panel)
    health = scores.get("structure_health", {})
    lines: list[str] = []
    if isinstance(health, dict) and health:
        total = int(health.get("scored_industry_count", 0) or 0)
        pos20 = int(health.get("positive_return_20d_count", 0) or 0)
        pos60 = int(health.get("positive_return_60d_count", 0) or 0)
        lines.append(
            f"- 扩散状态: 20日上涨行业 {pos20}/{total}，60日上涨行业 {pos60}/{total}；"
            f"{evaluate_breadth_comment(pos20, pos60, total)}"
        )
        top_negative = health.get("top_negative_60d_count")
        top_limit = health.get("top_limit")
        if top_negative is not None and top_limit:
            lines.append(
                f"- 中期确认: 结构分前{top_limit}行业中60日仍为负 {top_negative} 个；"
                "领先名单需要再看60日收益是否转正。"
            )

    top_structure = scores.get("top_structure", [])
    top_momentum = scores.get("top_momentum", [])
    if isinstance(top_structure, list) and isinstance(top_momentum, list):
        structure_names = {
            _industry_name(row) for row in top_structure[:5] if isinstance(row, dict)
        }
        momentum_names = {_industry_name(row) for row in top_momentum[:5] if isinstance(row, dict)}
        overlap = sorted(name for name in structure_names & momentum_names if name)
        if overlap:
            lines.append(f"- 结构和动量共振: {'、'.join(overlap)}。")
        elif structure_names and momentum_names:
            lines.append(
                "- 结构和动量分离: 结构分领先与动量主线不重合，"
                "说明交易主线和综合质量最优方向不是同一批行业。"
            )

    if rows:
        tcr_top = _top_rows(rows, "tcr", limit=3)
        if tcr_top:
            lines.append(
                "- 成交集中: "
                f"{_industry_list(tcr_top, (('TCR', 'tcr', '%'),), limit=3)}；"
                "TCR高表示成交占比高，需要观察是否抱团松动。"
            )
        lines.extend(_fund_flow_takeaway_lines(rows))
        weak = _top_rows(
            [
                row
                for row in rows
                if (_as_float(row.get("return_20d")) or 0.0) < 0
                and (_as_float(row.get("return_60d")) or 0.0) < 0
            ],
            "return_20d",
            limit=3,
            descending=False,
        )
        if weak:
            weak_text = _industry_list(
                weak,
                (("20日", "return_20d", "%"), ("60日", "return_60d", "%")),
                limit=3,
            )
            lines.append(f"- 弱势拖累: {weak_text}。")
    return lines or ["- 行业关键判断暂不可用。"]


def evaluate_structure_radar(industry_panel: pl.DataFrame, scores: dict[str, Any]) -> list[str]:
    """生成行业结构雷达多维观察段落。"""
    rows = _panel_rows(industry_panel)
    if not rows:
        return ["- 行业面板为空，结构雷达不可用。"]

    positive_60d = _top_rows(
        [row for row in rows if (_as_float(row.get("return_60d")) or 0.0) > 0],
        "return_60d",
        limit=6,
    )
    tcr_top = _top_rows(rows, "tcr", limit=5)
    fund_flow_top = _top_rows(
        [row for row in rows if is_fund_flow_confirmed(row)],
        "fund_flow_score",
        limit=5,
    )
    top_structure = _top_rows(rows, "structure_score", limit=10)
    unconfirmed = [row for row in top_structure if (_as_float(row.get("return_60d")) or 0.0) < 0]
    weak_fundamental = [row for row in top_structure if has_weak_fundamental(row)]
    crowded = scores.get("crowded_risk")
    crowded_rows = crowded if isinstance(crowded, list) else []
    tmt_rows = _top_rows(
        [row for row in rows if _industry_name(row) in {"电子", "通信", "计算机", "传媒"}],
        "tcr",
        limit=4,
    )
    return_metrics = (("20日", "return_20d", "%"), ("60日", "return_60d", "%"))
    tcr_metrics = (("TCR", "tcr", "%"),)
    fund_flow_metrics = (
        ("资金分", "fund_flow_score", ""),
        ("20日净流入", "money_net_inflow_share_20d", "%"),
    )
    crowded_metrics = (("20日", "return_20d", "%"), ("TCR", "tcr", "%"))
    fundamental_metrics = (("基本面分", "fundamental_score", ""),)

    lines = [
        f"- 60日正收益行业: {_industry_list(positive_60d, (('60日', 'return_60d', '%'),))}",
        f"- 成交集中 Top: {_industry_list(tcr_top, tcr_metrics)}",
        f"- 资金确认 Top: {_industry_list(fund_flow_top, fund_flow_metrics)}",
        f"- 拥挤风险: {_industry_list(crowded_rows, crowded_metrics)}",
        (f"- 结构领先但60日未确认: {_industry_list(unconfirmed, return_metrics)}"),
        (f"- 结构领先但基本面确认不足: {_industry_list(weak_fundamental, fundamental_metrics)}"),
    ]
    if tmt_rows:
        tmt_tcr = sum(_as_float(row.get("tcr")) or 0.0 for row in tmt_rows)
        lines.append(
            "- 电子/TMT成交集中: "
            f"{_industry_list(tmt_rows, tcr_metrics)}；TMT合计TCR {tmt_tcr:.2f}%。"
        )
    return lines


def evaluate_theme_types(industry_panel: pl.DataFrame) -> list[str]:
    """生成行业主线类型分类与说明。"""
    rows = _panel_rows(industry_panel)
    if not rows:
        return ["- 行业面板为空，主线类型不可用。"]

    low_valuation_improving = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("return_60d")) or 0.0) > 0
            and (_as_float(row.get("valuation_score")) or 0.0) >= 60
            and (_as_float(row.get("fundamental_score")) or 0.0) >= 50
            and (_as_float(row.get("crowding_temperature")) or 0.0) < 70
        ],
        "structure_score",
        limit=3,
    )
    high_beta_strong = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("momentum_score")) or 0.0) >= 70
            and (_as_float(row.get("crowding_temperature")) or 0.0) >= 80
        ],
        "momentum_score",
        limit=3,
    )
    crowded_valuation = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("tcr")) or 0.0) >= 5
            and max(
                _as_float(row.get("pe_percentile_5y")) or 0.0,
                _as_float(row.get("pb_percentile_5y")) or 0.0,
            )
            >= 80
        ],
        "tcr",
        limit=4,
    )
    defensive_crowding = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("pb_percentile_5y")) or 100.0) <= 30
            and is_high_dividend(row)
            and (_as_float(row.get("crowding_temperature")) or 0.0) >= 80
        ],
        "crowding_temperature",
        limit=3,
    )
    pure_momentum = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("momentum_score")) or 0.0) >= 70 and has_weak_fundamental(row)
        ],
        "momentum_score",
        limit=3,
    )
    weak_prosperity = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("fundamental_score")) or 100.0) < 30
            or "景气承压" in str(row.get("tags") or "")
        ],
        "crowding_temperature",
        limit=4,
    )
    high_beta_metrics = (
        ("动量分", "momentum_score", ""),
        ("拥挤温度", "crowding_temperature", ""),
    )
    crowded_valuation_metrics = (
        ("TCR", "tcr", "%"),
        ("PE分位", "pe_percentile_5y", ""),
        ("PB分位", "pb_percentile_5y", ""),
    )
    defensive_metrics = (
        ("股息率", "dividend_yield", "%"),
        ("拥挤温度", "crowding_temperature", ""),
    )
    pure_momentum_metrics = (
        ("动量分", "momentum_score", ""),
        ("基本面分", "fundamental_score", ""),
    )
    weak_prosperity_metrics = (
        ("基本面分", "fundamental_score", ""),
        ("拥挤温度", "crowding_temperature", ""),
    )

    return [
        (
            "- 低估改善、不拥挤、中期正收益: "
            f"{_industry_list(low_valuation_improving, (('结构分', 'structure_score', ''),))}"
        ),
        (f"- 高博弈强趋势: {_industry_list(high_beta_strong, high_beta_metrics)}"),
        (
            "- 成交主战场/高估值集中: "
            f"{_industry_list(crowded_valuation, crowded_valuation_metrics)}"
        ),
        (f"- 防御抱团: {_industry_list(defensive_crowding, defensive_metrics)}"),
        (f"- 纯动量/基本面确认不足: {_industry_list(pure_momentum, pure_momentum_metrics)}"),
        (f"- 景气承压: {_industry_list(weak_prosperity, weak_prosperity_metrics)}"),
    ]


def evaluate_short_term_rhythm(industry_panel: pl.DataFrame) -> list[str]:
    """生成行业短线节奏与轮动观察段落。"""
    rows = _panel_rows(industry_panel)
    if not rows:
        return ["- 行业面板为空，短线节奏不可用。"]
    accelerating = _top_rows(
        [row for row in rows if (_as_float(row.get("return_5d")) or 0.0) >= 3],
        "return_5d",
        limit=5,
    )
    pullback = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("return_20d")) or 0.0) >= 5
            and (_as_float(row.get("return_5d")) or 0.0) < 0
        ],
        "return_20d",
        limit=5,
    )
    weak = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("return_5d")) or 0.0) < 0
            and (_as_float(row.get("return_20d")) or 0.0) < 0
        ],
        "return_5d",
        limit=5,
        descending=False,
    )
    rhythm_metrics = (("5日", "return_5d", "%"), ("20日", "return_20d", "%"))
    return [
        f"- 5日仍在上行: {_industry_list(accelerating, rhythm_metrics)}",
        f"- 20日强但5日回落: {_industry_list(pullback, rhythm_metrics)}",
        f"- 5日和20日都偏弱: {_industry_list(weak, rhythm_metrics)}",
    ]


def _fund_flow_takeaway_lines(rows: list[dict[str, Any]]) -> list[str]:
    fund_flow_metrics = (
        ("资金分", "fund_flow_score", ""),
        ("20日净流入", "money_net_inflow_share_20d", "%"),
    )
    fund_flow_top = _top_rows(
        [row for row in rows if is_fund_flow_confirmed(row)],
        "fund_flow_score",
        limit=3,
    )
    fund_flow_pressure = _top_rows(
        [row for row in rows if has_fund_flow_pressure(row)],
        "fund_flow_score",
        limit=3,
        descending=False,
    )
    lines = []
    if fund_flow_top:
        lines.append(f"- 资金确认: {_industry_list(fund_flow_top, fund_flow_metrics)}。")
    if fund_flow_pressure:
        lines.append(f"- 资金流出压力: {_industry_list(fund_flow_pressure, fund_flow_metrics)}。")
    return lines


def _names(rows: list[dict[str, Any]]) -> str:
    names = [str(row.get("industry_name") or row.get("industry_code")) for row in rows]
    return "、".join(names) if names else "无"
