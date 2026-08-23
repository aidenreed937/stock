"""个股深度诊断与全景体检模块。"""

from stock_analytics.pipelines.stock_diagnostics.pipeline import run_stock_diagnostics
from stock_analytics.pipelines.stock_diagnostics.types import (
    CapitalFlowSnapshot,
    FinancialsSnapshot,
    MarketContextSnapshot,
    ScreenSnapshot,
    StockDiagnosticsResult,
    TechnicalsSnapshot,
    ValuationSnapshot,
)

__all__ = [
    "CapitalFlowSnapshot",
    "FinancialsSnapshot",
    "MarketContextSnapshot",
    "ScreenSnapshot",
    "StockDiagnosticsResult",
    "TechnicalsSnapshot",
    "ValuationSnapshot",
    "run_stock_diagnostics",
]
