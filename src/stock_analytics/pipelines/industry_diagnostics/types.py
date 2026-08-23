"""中观产业与行业深度诊断领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IndustryTechnicalsSnapshot:
    """行业行情与技术形态快照。"""

    close: float
    pct_chg: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    rsi14: float | None = None
    trend_description: str = "震荡整理"


@dataclass(frozen=True, slots=True)
class IndustryValuationSnapshot:
    """行业整体估值与历史分位数快照。"""

    pe_ttm: float | None = None
    pe_percentile_5y: float | None = None
    pe_percentile_10y: float | None = None
    pb: float | None = None
    pb_percentile_5y: float | None = None
    dv_ttm: float | None = None
    treasury_10y_yield: float | None = None
    dividend_spread_10y: float | None = None
    valuation_status: str = "估值中性"


@dataclass(frozen=True, slots=True)
class IndustryFinancialsSnapshot:
    """行业整体财务质量与周期阶段快照。"""

    report_date: str | None = None
    roe_avg: float | None = None
    revenue_yoy: float | None = None
    netprofit_yoy: float | None = None
    gross_margin: float | None = None
    cycle_stage: str = "成熟平稳期"


@dataclass(frozen=True, slots=True)
class IndustryConstituentsSnapshot:
    """行业成份股与核心龙头梯队快照。"""

    total_count: int = 0
    top_market_cap_leaders: list[dict[str, Any]] = field(default_factory=list)
    top_roe_leaders: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IndustryValueChainSnapshot:
    """产业链上下游传导图谱快照。"""

    upstream: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)
    cost_sensitivity: str = ""
    high_frequency_indicators: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IndustryDiagnosticsResult:
    """行业全景深度诊断聚合结果。"""

    industry_code: str
    industry_name: str
    level: str  # 申万一级 / 申万二级
    as_of_date: str
    technicals: IndustryTechnicalsSnapshot
    valuation: IndustryValuationSnapshot
    financials: IndustryFinancialsSnapshot
    constituents: IndustryConstituentsSnapshot
    value_chain: IndustryValueChainSnapshot

    def to_dict(self) -> dict[str, Any]:
        """序列化为紧凑字典。"""
        return asdict(self)

    def to_markdown(self) -> str:
        """渲染为结构化 Markdown 研报。"""
        tech = self.technicals
        val = self.valuation
        fin = self.financials
        const = self.constituents
        chain = self.value_chain

        pe_str = f"{val.pe_ttm:.2f}" if val.pe_ttm is not None else "--"
        pe_5y_str = f"{val.pe_percentile_5y:.1f}%" if val.pe_percentile_5y is not None else "--"
        pe_10y_str = f"{val.pe_percentile_10y:.1f}%" if val.pe_percentile_10y is not None else "--"
        pb_str = f"{val.pb:.2f}" if val.pb is not None else "--"
        pb_5y_str = f"{val.pb_percentile_5y:.1f}%" if val.pb_percentile_5y is not None else "--"
        dv_str = f"{val.dv_ttm:.2f}%" if val.dv_ttm is not None else "--"
        spread_str = (
            f"{val.dividend_spread_10y:+.2f}% (10Y国债 {val.treasury_10y_yield:.2f}%)"
            if val.dividend_spread_10y is not None and val.treasury_10y_yield is not None
            else "--"
        )

        ma20_str = f"{tech.ma20:.2f}" if tech.ma20 is not None else "--"
        ma60_str = f"{tech.ma60:.2f}" if tech.ma60 is not None else "--"
        rsi_str = f"{tech.rsi14:.1f}" if tech.rsi14 is not None else "--"
        pct_str = f"{tech.pct_chg:+.2f}%" if tech.pct_chg is not None else "--"

        roe_str = f"{fin.roe_avg:.2f}%" if fin.roe_avg is not None else "--"
        np_yoy_str = f"{fin.netprofit_yoy:.2f}%" if fin.netprofit_yoy is not None else "--"
        rev_yoy_str = f"{fin.revenue_yoy:.2f}%" if fin.revenue_yoy is not None else "--"
        margin_str = f"{fin.gross_margin:.2f}%" if fin.gross_margin is not None else "--"

        lines = [
            f"# 中观产业深度量化诊断报告: {self.industry_name} ({self.industry_code})",
            "",
            f"- **所属层级**: {self.level}",
            f"- **基准日期**: {self.as_of_date}",
            f"- **周期与估值定调**: 【{fin.cycle_stage}】 | 【{val.valuation_status}】",
            "",
            "## 1. 行业行情与技术形态 (Technicals)",
            f"- **指数最新收盘**: {tech.close:.2f} (日涨跌幅: {pct_str})",
            f"- **均线系统**: MA20 = {ma20_str} | MA60 = {ma60_str}",
            f"- **动量与趋势**: RSI(14) = {rsi_str} | 形态: {tech.trend_description}",
            "",
            "## 2. 行业估值水位与股息利差 (Valuation)",
            f"- **PE (TTM)**: {pe_str} (近5年分位: {pe_5y_str} | 近10年分位: {pe_10y_str})",
            f"- **PB**: {pb_str} (近5年分位: {pb_5y_str})",
            f"- **整体股息率 (TTM)**: {dv_str} | **超额利差安全垫**: {spread_str}",
            "",
            "## 3. 行业整体基本面与财务质量 (Financials)",
            f"- **最新财报期**: {fin.report_date or '--'}",
            f"- **行业整体 ROE**: {roe_str}",
            f"- **营收同比 / 净利同比**: {rev_yoy_str} / {np_yoy_str}",
            f"- **综合毛利率**: {margin_str}",
            "",
            "## 4. 行业成份股格局与核心龙头梯队 (Market Structure)",
            f"- **成份股总数**: {const.total_count} 家",
        ]

        if const.top_market_cap_leaders:
            lines.append("- **核心市值龙头 Top 5**:")
            for item in const.top_market_cap_leaders:
                lines.append(
                    f"  - {item.get('name', '')} ({item.get('symbol', '')}): 市值 {item.get('total_mv_billion', 0):.1f} 亿 | PE: {item.get('pe_ttm', '--')} | ROE: {item.get('roe', '--')}%"
                )

        lines.extend(
            [
                "",
                "## 5. 产业链上下游传导与高频监测图谱 (Value Chain)",
                f"- **上游成本端**: {', '.join(chain.upstream) if chain.upstream else '待补充'}",
                f"- **下游应用端**: {', '.join(chain.downstream) if chain.downstream else '待补充'}",
                f"- **成本传导机制**: {chain.cost_sensitivity or '成本波动直接影响中游加工毛利'}",
            ]
        )

        if chain.high_frequency_indicators:
            lines.append("- **建议使用 GrokSearch-rs MCP 联网核验的高频微观指标**:")
            for ind in chain.high_frequency_indicators:
                lines.append(f"  - **{ind.get('name', '')}** (权威信源: {ind.get('source', '')})")

        lines.append("")
        return "\n".join(lines)
