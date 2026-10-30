"""精对苯二甲酸 (PTA) 全景基本面对账与周期量化管线包。"""

from stock_analytics.pipelines.pta.config import PtaConfig, load_pta_config
from stock_analytics.pipelines.pta.gates import evaluate_trading_gates, load_trading_gates
from stock_analytics.pipelines.pta.panorama import (
    FLOW_REGIME_CN,
    aggregate_capacity_by_month,
    classify_flow_regime,
    classify_margin_regime,
    detect_regime_episodes,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.pta.pipeline import (
    PtaPipeline,
    PtaRunResult,
    load_latest_pta_panorama,
    run_pta_pipeline,
)
from stock_analytics.pipelines.pta.projections import (
    CompanyFinancialContext,
    PtaCompanyProjectionEngine,
    PtaProjectionResult,
    SegmentResult,
    build_financial_context,
)
from stock_analytics.pipelines.pta.report import render_markdown

__all__ = [
    "FLOW_REGIME_CN",
    "CompanyFinancialContext",
    "PtaCompanyProjectionEngine",
    "PtaConfig",
    "PtaPipeline",
    "PtaProjectionResult",
    "PtaRunResult",
    "SegmentResult",
    "aggregate_capacity_by_month",
    "build_financial_context",
    "classify_flow_regime",
    "classify_margin_regime",
    "detect_regime_episodes",
    "evaluate_trading_gates",
    "load_latest_pta_panorama",
    "load_pta_config",
    "load_trading_gates",
    "merge_monthly_panorama",
    "render_markdown",
    "run_pta_pipeline",
]
