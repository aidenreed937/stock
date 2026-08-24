"""全市场聚合行业维度人工报告片段。"""

from __future__ import annotations

from typing import Any


def render_industry_section(industry: Any, *, top_n: int = 10) -> str:
    """渲染盘中行业广度/强弱/成交切片。

    行业维度是全市场聚合摘要的切片，不是逐标的明细；覆盖率与映射口径
    一并展示，避免被误读为行业级实时监控。
    """
    if not _is_usable(industry):
        return "## 行业维度\n\n- 状态: 未启用或数据源不支持。\n"
    rows = industry.rows
    if not rows:
        return "## 行业维度\n\n- 状态: 暂无行业聚合数据。\n"
    visible = [row for row in rows if getattr(row, "industry", "") != "__UNKNOWN__"]
    unknown = next((row for row in rows if getattr(row, "industry", "") == "__UNKNOWN__"), None)
    shown = visible[:top_n]
    lines = [
        "## 行业维度（盘中切片）",
        "",
        f"- 映射覆盖: {industry.mapped_count}/{industry.reported_count} "
        f"（覆盖率 {_ratio(industry.mapped_count / industry.reported_count if industry.reported_count else 0)}）",
        f"- 行业数: {industry.industry_count} 个（有效，成员数≥配置阈值）；"
        f"映射原始行业 {industry.raw_industry_count} 个",
        f"- 口径: 与全市场聚合同一次腾讯抓取；强势涨跌阈值 ±{industry.strong_move_threshold_pct:.1f}%",
        "",
        "| 行业 | 成员 | 上涨/下跌/平盘 | 上涨占比 | 涨跌比 | 强势涨/跌 | 中位涨跌 | 加权涨跌 | 成交额 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in shown:
        lines.append(
            "| {industry} | {members} | {breadth} | {adv_share} | {ratio} | "
            "{strong} | {median} | {weighted} | {amount} |".format(
                industry=_industry_name(row.industry),
                members=row.member_count,
                breadth=(f"{row.advance_count} / {row.decline_count} / {row.flat_count}"),
                adv_share=_share(row.advance_share),
                ratio=_ratio(row.advance_decline_ratio),
                strong=f"{row.strong_up_count} / {row.strong_down_count}",
                median=_pct(row.median_pct_change),
                weighted=_pct(row.weighted_pct_change),
                amount=_money(row.amount_total_yuan),
            )
        )
    if unknown is not None and unknown.member_count:
        lines.extend(
            [
                "",
                f"- 未分类标的: {unknown.member_count} 只（本地 stock_basic 缺失行业字段）。",
            ]
        )
    if len(visible) > top_n:
        lines.append("")
        lines.append(f"- 已按成员数排序并展示前 {top_n} 个行业，共 {len(visible)} 个有效行业。")
    return "\n".join(lines) + "\n"


def _is_usable(industry: Any) -> bool:
    return industry is not None and getattr(industry, "is_usable", False)


def _industry_name(value: Any) -> str:
    text = str(value)
    return text if text != "__UNKNOWN__" else "未分类"


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


__all__ = ["render_industry_section"]
