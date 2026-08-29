"""中观产业与行业深度诊断模块。"""

from stock_analytics.pipelines.industry_diagnostics.config import (
    DEFAULT_CONFIG_PATH,
    IndustryDiagnosticsConfig,
    ScoreWeightsConfig,
    TechnicalsConfig,
    ValuationConfig,
    VetoRulesConfig,
    load_industry_diagnostics_config,
)
from stock_analytics.pipelines.industry_diagnostics.pipeline import (
    IndustryDiagnosticsPipeline,
    run_industry_diagnostics,
)
from stock_analytics.pipelines.industry_diagnostics.scoring import (
    calculate_industry_scores,
)
from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryConstituentsSnapshot,
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
    IndustryScoreBreakdown,
    IndustryTechnicalsSnapshot,
    IndustryValuationSnapshot,
    IndustryValueChainSnapshot,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "IndustryConstituentsSnapshot",
    "IndustryDiagnosticsConfig",
    "IndustryDiagnosticsPipeline",
    "IndustryDiagnosticsResult",
    "IndustryFinancialsSnapshot",
    "IndustryScoreBreakdown",
    "IndustryTechnicalsSnapshot",
    "IndustryValuationSnapshot",
    "IndustryValueChainSnapshot",
    "ScoreWeightsConfig",
    "TechnicalsConfig",
    "ValuationConfig",
    "VetoRulesConfig",
    "calculate_industry_scores",
    "load_industry_diagnostics_config",
    "run_industry_diagnostics",
]
