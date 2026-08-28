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
        from stock_reporting.templates.industry_diagnostics_report import (
            render_industry_diagnostics_report,
        )

        return render_industry_diagnostics_report(self)
