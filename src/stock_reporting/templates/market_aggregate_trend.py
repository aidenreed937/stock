"""全市场聚合短期趋势人工报告片段。"""

from __future__ import annotations

from typing import Any


def render_trend_section(trend: dict[str, Any] | None) -> str:
    """渲染盘中快照与前置交易日结构性指标对比。"""
    if not trend or trend.get("status") == "unavailable":
        reason = (trend or {}).get("reason") or "未生成短期历史对比。"
        return f"## 最近交易日短期趋势\n\n- 状态: 不可用\n- 原因: {reason}\n"

    rows = trend.get("rows") or []
    summary = trend.get("summary") or {}
    direction_key = summary.get("direction")
    direction = {
        "improving": "上涨扩散改善",
        "weakening": "上涨扩散转弱",
        "range_bound": "短线震荡或分化",
    }.get(direction_key if isinstance(direction_key, str) else "", "暂无法判断")
    comparison = summary.get("current_vs_history_average") or {}
    previous = summary.get("latest_vs_previous") or {}
    lines = [
        f"## 最近 {len(rows)} 个交易日短期趋势",
        "",
        "- 口径: 今日为腾讯实时快照；前置交易日为本地 Curated 日线聚合。",
        f"- 状态: {'可用' if trend.get('status') == 'available' else '部分可用'}",
        f"- 趋势判断: {direction}",
        f"- 当前上涨占比较前置日均值: {_signed_pp(comparison.get('advance_share_change_pp'))}",
        f"- 当前下跌占比较前置日均值: {_signed_pp(comparison.get('decline_share_change_pp'))}",
        f"- 当前强势上涨占比较前置日均值: {_signed_pp(comparison.get('strong_up_share_change_pp'))}",
        f"- 当前强势下跌占比较前置日均值: {_signed_pp(comparison.get('strong_down_share_change_pp'))}",
        f"- 当前涨跌幅中位数较前置日均值: {_signed_pp(comparison.get('median_pct_change_change_pp'))}",
        f"- 当前成交额加权涨跌幅较前置日均值: {_signed_pp(comparison.get('weighted_pct_change_change_pp'))}",
        f"- 当前成交额前 5% 集中度较前置日均值: {_signed_pp(comparison.get('amount_top_5pct_share_change_pp'))}",
        "- 成交额 / 流通市值换手率: 当前为盘中累计值，与前置完整交易日不直接比较；需积累同一盘中时点快照后再比较。",
        f"- 相比前一交易日上涨占比: {_signed_pp(previous.get('advance_share_change_pp'))}",
        "",
        "| 日期 | 口径 | 覆盖率 | 上涨 / 下跌 / 平盘 | 涨跌比 | 中位涨跌幅 | 加权涨跌幅 | 成交额（盘中累计） | 流通换手率（盘中累计） | 成交额前 5% 集中度 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        source = "腾讯实时" if row.get("source") == "tencent_realtime" else "本地日线"
        coverage = f"{float(row.get('coverage_ratio', 0)):.2%}"
        breadth = (
            f"{row.get('advance_count', 0)} / {row.get('decline_count', 0)} / "
            f"{row.get('flat_count', 0)}"
        )
        lines.append(
            "| {date} | {source} | {coverage} | {breadth} | {ratio} | {median} | "
            "{weighted} | {amount} | {turnover} | {concentration} |".format(
                date=row.get("date", "-"),
                source=source,
                coverage=coverage,
                breadth=breadth,
                ratio=_ratio(row.get("advance_decline_ratio")),
                median=_pct(row.get("median_pct_change")),
                weighted=_pct(row.get("weighted_pct_change")),
                amount=_money(row.get("amount_total_yuan")),
                turnover=_pct(row.get("free_float_turnover_pct")),
                concentration=_share(row.get("amount_top_5pct_share")),
            )
        )
    if trend.get("reason"):
        lines.extend(["", f"- 限制: {trend['reason']}"])
    return "\n".join(lines) + "\n"


def _signed_pp(value: Any) -> str:
    return "-" if value is None else f"{float(value):+.2f} 个百分点"


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2f}%"


def _share(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2%}"


def _ratio(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2f}"


def _money(value: Any) -> str:
    if value is None:
        return "-"
    value = float(value)
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}万亿"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}元"
