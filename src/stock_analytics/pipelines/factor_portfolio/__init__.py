"""因子组合分数产物管线。"""

from stock_analytics.pipelines.factor_portfolio.config import (
    DEFAULT_CONFIG_PATH,
    FactorPortfolioConfig,
    load_factor_portfolio_config,
)
from stock_analytics.pipelines.factor_portfolio.pipeline import (
    FactorPortfolioRunResult,
    run_factor_portfolio,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "FactorPortfolioConfig",
    "FactorPortfolioRunResult",
    "load_factor_portfolio_config",
    "run_factor_portfolio",
]
