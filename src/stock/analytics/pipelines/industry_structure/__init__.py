"""申万行业结构分析产物管线。"""

from stock.analytics.pipelines.industry_structure.pipeline import (
    IndustryStructureRunResult,
    run_industry_structure,
)

__all__ = ["IndustryStructureRunResult", "run_industry_structure"]
