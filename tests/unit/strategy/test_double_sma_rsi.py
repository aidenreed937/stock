from datetime import date, timedelta

import polars as pl

from stock_strategy.config import load_strategy_config
from stock_strategy.pool.double_sma_rsi import DoubleSmaRsiStrategy
from stock_strategy.runner import StrategyRunner


def _bars(symbol: str = "TEST.SH") -> pl.DataFrame:
    start = date(2026, 1, 1)
    prices = [10.0] * 20 + [9.0, 11.0]
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(prices),
            "trade_date": [start + timedelta(days=i) for i in range(len(prices))],
            "close": prices,
        }
    )


def test_double_sma_rsi_uses_configured_weight() -> None:
    config = load_strategy_config("config/strategy/double_sma_rsi.yaml")
    signals = DoubleSmaRsiStrategy(config).on_bar(_bars())
    assert all(
        signal.target_weight == config.risk_management.max_position_per_symbol
        for signal in signals
        if signal.target_weight
    )


def test_strategy_runner_report_contains_config_identity() -> None:
    config = load_strategy_config("config/strategy/double_sma_rsi.yaml")
    report = StrategyRunner(config, "tushare").run(_bars())
    assert report.strategy_name == config.name
    assert report.strategy_version == config.version
    assert report.data_source == "tushare"
