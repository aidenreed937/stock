"""业务决策管线包 (L3 Business Pipelines)。

聚合全市场温度计、申万行业结构与投资决策简报等端到端业务流水线。
"""

from __future__ import annotations

from stock.analytics.pipelines.industry_structure.pipeline import (
    IndustryStructureRunResult,
    run_industry_structure,
)
from stock.analytics.pipelines.investor_brief.pipeline import (
    InvestorBriefRunResult,
    run_investor_brief,
)
from stock.analytics.pipelines.market_temperature.pipeline import (
    MarketTemperatureRunResult,
    run_market_temperature,
)

__all__ = [
    "IndustryStructureRunResult",
    "InvestorBriefRunResult",
    "MarketTemperatureRunResult",
    "run_industry_structure",
    "run_investor_brief",
    "run_market_temperature",
]
