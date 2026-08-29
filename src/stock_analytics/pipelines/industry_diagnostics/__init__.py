"""中观产业与行业深度诊断模块。"""

from stock_analytics.pipelines.industry_diagnostics.config import (
    DEFAULT_CONFIG_PATH,
    ArchetypeConfig,
    IndustryDiagnosticsConfig,
    IndustryThresholdsConfig,
    ScoreWeightsConfig,
    TechnicalsConfig,
    ValuationConfig,
    ValuationWeightsConfig,
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
from stock_analytics.pipelines.industry_diagnostics.value_chain import (
    load_value_chain_map,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "ArchetypeConfig",
    "IndustryConstituentsSnapshot",
    "IndustryDiagnosticsConfig",
    "IndustryDiagnosticsPipeline",
    "IndustryDiagnosticsResult",
    "IndustryFinancialsSnapshot",
    "IndustryScoreBreakdown",
    "IndustryTechnicalsSnapshot",
    "IndustryThresholdsConfig",
    "IndustryValuationSnapshot",
    "IndustryValueChainSnapshot",
    "ScoreWeightsConfig",
    "TechnicalsConfig",
    "ValuationConfig",
    "ValuationWeightsConfig",
    "VetoRulesConfig",
    "calculate_industry_scores",
    "load_industry_diagnostics_config",
    "load_value_chain_map",
    "run_industry_diagnostics",
]
