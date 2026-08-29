-- ====================================================================
-- Migration 002: 策略回测运行实验与参数敏感性追踪版本库
-- ====================================================================

CREATE TABLE IF NOT EXISTS backtest_experiments (
    experiment_id TEXT PRIMARY KEY,
    strategy_class TEXT NOT NULL,
    benchmark_symbol TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    trading_days INTEGER NOT NULL,
    params_json TEXT NOT NULL,
    friction_json TEXT NOT NULL,
    total_return REAL NOT NULL,
    cagr REAL NOT NULL,
    max_drawdown REAL NOT NULL,
    annual_volatility REAL NOT NULL,
    sharpe_ratio REAL NOT NULL,
    calmar_ratio REAL NOT NULL,
    total_turnover REAL NOT NULL,
    annual_trades REAL NOT NULL,
    run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_exp_strategy_sharpe ON backtest_experiments(strategy_class, sharpe_ratio DESC);
