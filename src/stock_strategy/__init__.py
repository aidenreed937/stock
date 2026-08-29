"""策略层核心组件导出。"""

from __future__ import annotations

from stock_strategy.application import (
    StrategyApplicationResult,
    run_strategy_application,
)
from stock_strategy.base import BaseStrategy
from stock_strategy.config import (
    IndicatorsConfig,
    RiskManagementConfig,
    RSIIndicatorConfig,
    SMAIndicatorConfig,
    StrategyConfig,
    load_strategy_config,
)
from stock_strategy.context import Context, Position
from stock_strategy.exceptions import StrategyError
from stock_strategy.macro_assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro_audit import (
    StabilityAuditResult,
    assert_stability_guardrails,
    run_full_stability_audit,
)
from stock_strategy.macro_live import inspect_live_signal
from stock_strategy.macro_report import (
    build_multi_strategy_comparison_report,
    compute_metrics,
)
from stock_strategy.macro_runner import MacroRiskRunner
from stock_strategy.pool import (
    STRATEGY_REGISTRY,
    DoubleSmaRsiStrategy,
    MACDCrossStrategy,
    MacroRiskV3Strategy,
    MacroRotationV4Strategy,
    MacroRotationV5Strategy,
    MacroRotationV6Strategy,
    create_strategy,
)
from stock_strategy.portfolio import (
    BacktestApplicationResult,
    BacktestResult,
    run_backtest_application,
    run_factor_backtest,
)
from stock_strategy.runner import SignalReport, StrategyRunner
from stock_strategy.signal import Signal, SignalDirection

__all__ = [
    "STRATEGY_REGISTRY",
    "BacktestApplicationResult",
    "BacktestResult",
    "BaseStrategy",
    "Context",
    "DoubleSmaRsiStrategy",
    "IndicatorsConfig",
    "MACDCrossStrategy",
    "MacroRiskRunner",
    "MacroRiskV3Strategy",
    "MacroRotationV4Strategy",
    "MacroRotationV5Strategy",
    "MacroRotationV6Strategy",
    "Position",
    "RSIIndicatorConfig",
    "RiskManagementConfig",
    "SMAIndicatorConfig",
    "Signal",
    "SignalDirection",
    "SignalReport",
    "StabilityAuditResult",
    "StrategyApplicationResult",
    "StrategyConfig",
    "StrategyError",
    "StrategyRunner",
    "assemble_macro_panel",
    "assert_stability_guardrails",
    "build_multi_strategy_comparison_report",
    "compute_metrics",
    "create_strategy",
    "inspect_live_signal",
    "load_price_panel",
    "load_strategy_config",
    "run_backtest_application",
    "run_factor_backtest",
    "run_full_stability_audit",
    "run_strategy_application",
]
