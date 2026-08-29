"""申万行业结构分析产物管线。"""

from stock_analytics.pipelines.industry_structure.config import (
    DEFAULT_CONFIG_PATH,
    DatasetConfig,
    FundamentalBlendConfig,
    IndustryStructureConfig,
    IndustryThresholdsConfig,
    ScoreWeights,
    load_industry_structure_config,
)
from stock_analytics.pipelines.industry_structure.factor_panel import (
    build_industry_factor_panel,
    load_latest_industry_factors,
    save_industry_factor_panel,
)
from stock_analytics.pipelines.industry_structure.pipeline import (
    IndustryStructurePipeline,
    IndustryStructureRunResult,
    run_industry_structure,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DatasetConfig",
    "FundamentalBlendConfig",
    "IndustryStructureConfig",
    "IndustryStructurePipeline",
    "IndustryStructureRunResult",
    "IndustryThresholdsConfig",
    "ScoreWeights",
    "build_industry_factor_panel",
    "load_industry_structure_config",
    "load_latest_industry_factors",
    "run_industry_structure",
    "save_industry_factor_panel",
]
