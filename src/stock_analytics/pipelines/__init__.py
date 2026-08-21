"""业务决策管线包 (L3 Business Pipelines)。

聚合全市场温度计、申万行业结构与投资决策简报等端到端业务流水线。
"""

from __future__ import annotations

from stock_analytics.pipelines.industry_structure.pipeline import (
    IndustryStructureRunResult,
    run_industry_structure,
)
from stock_analytics.pipelines.investor_brief.pipeline import (
    InvestorBriefRunResult,
    run_investor_brief,
)
from stock_analytics.pipelines.market_aggregate.pipeline import (
    MarketAggregateRunResult,
    run_market_aggregate,
)
from stock_analytics.pipelines.market_temperature.pipeline import (
    MarketTemperatureRunResult,
    run_market_temperature,
)
from stock_analytics.pipelines.quant_brief.pipeline import (
    QuantBriefRunResult,
    run_quant_brief,
)
from stock_analytics.pipelines.stock_screen.pipeline import (
    StockScreenRunResult,
    run_stock_screen,
)

__all__ = [
    "IndustryStructureRunResult",
    "InvestorBriefRunResult",
    "MarketAggregateRunResult",
    "MarketTemperatureRunResult",
    "QuantBriefRunResult",
    "StockScreenRunResult",
    "run_industry_structure",
    "run_investor_brief",
    "run_market_aggregate",
    "run_market_temperature",
    "run_quant_brief",
    "run_stock_screen",
]
