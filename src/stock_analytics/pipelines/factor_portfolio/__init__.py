"""因子组合分数产物管线。"""

from stock_analytics.pipelines.factor_portfolio.backtest_artifacts import (
    BacktestArtifactPayload,
    BacktestRunPaths,
    build_backtest_manifest,
    build_backtest_run_paths,
    load_latest_scores,
    write_backtest_artifacts,
)
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
    "BacktestArtifactPayload",
    "BacktestRunPaths",
    "FactorPortfolioConfig",
    "FactorPortfolioRunResult",
    "build_backtest_manifest",
    "build_backtest_run_paths",
    "load_factor_portfolio_config",
    "load_latest_scores",
    "run_factor_portfolio",
    "write_backtest_artifacts",
]
