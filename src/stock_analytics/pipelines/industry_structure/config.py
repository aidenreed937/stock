"""申万行业结构分析管线配置。"""

from __future__ import annotations

from stock_core.config.analytics_industry_structure import (
    DEFAULT_CONFIG_PATH,
    DatasetConfig,
    FundamentalBlendConfig,
    IndustryStructureConfig,
    IndustryThresholdsConfig,
    ScoreWeights,
    load_industry_structure_config,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DatasetConfig",
    "FundamentalBlendConfig",
    "IndustryStructureConfig",
    "IndustryThresholdsConfig",
    "ScoreWeights",
    "load_industry_structure_config",
]
