"""投资者简报产物管线。"""

from stock.analytics.pipelines.investor_brief.pipeline import (
    InvestorBriefRunResult,
    run_investor_brief,
)

__all__ = ["InvestorBriefRunResult", "run_investor_brief"]
