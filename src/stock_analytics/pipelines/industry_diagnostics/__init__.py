"""中观产业与行业深度诊断模块。"""

from stock_analytics.pipelines.industry_diagnostics.pipeline import (
    run_industry_diagnostics,
)
from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryConstituentsSnapshot,
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
    IndustryTechnicalsSnapshot,
    IndustryValuationSnapshot,
    IndustryValueChainSnapshot,
)

__all__ = [
    "IndustryConstituentsSnapshot",
    "IndustryDiagnosticsResult",
    "IndustryFinancialsSnapshot",
    "IndustryTechnicalsSnapshot",
    "IndustryValuationSnapshot",
    "IndustryValueChainSnapshot",
    "run_industry_diagnostics",
]
