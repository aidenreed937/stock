"""行业结构配置兼容门面。"""

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
