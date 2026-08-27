"""因子准入评估产物管线。"""

from stock_analytics.pipelines.factor_research.config import DEFAULT_CONFIG_PATH
from stock_analytics.pipelines.factor_research.pipeline import (
    FactorResearchRunResult,
    run_factor_research,
)

__all__ = ["DEFAULT_CONFIG_PATH", "FactorResearchRunResult", "run_factor_research"]
