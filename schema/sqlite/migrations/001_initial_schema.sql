-- ====================================================================
-- Migration 001: 交易账户、持仓快照、交易流水与 14:50 信号告警审计表
-- ====================================================================

-- 1.1 交易账户表
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    strategy_key TEXT NOT NULL,
    total_capital REAL NOT NULL,
    cash_available REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 1.2 当前持仓快照表
CREATE TABLE IF NOT EXISTS positions (
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    shares INTEGER NOT NULL DEFAULT 0,
    cost_price REAL NOT NULL,
    latest_price REAL,
    market_value REAL,
    weight REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, symbol)
);

-- 1.3 订单委托与成交历史流水表 (Audit Trail)
CREATE TABLE IF NOT EXISTS trade_orders (
    order_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    order_time TIMESTAMP NOT NULL,
    direction TEXT NOT NULL,
    target_weight REAL NOT NULL,
    target_shares INTEGER NOT NULL,
    filled_shares INTEGER NOT NULL,
    filled_price REAL NOT NULL,
    commission REAL NOT NULL DEFAULT 0,
    slippage_cost REAL NOT NULL DEFAULT 0,
    reason TEXT,
    status TEXT NOT NULL
);

-- 1.4 策略信号生成历史表 (含幂等去重哈希)
CREATE TABLE IF NOT EXISTS signal_history (
    signal_id TEXT PRIMARY KEY,
    strategy_key TEXT NOT NULL,
    trade_date DATE NOT NULL,
    generated_at TIMESTAMP NOT NULL,
    signal_hash TEXT NOT NULL,
    has_rebalance INTEGER NOT NULL,
    benchmark_symbol TEXT NOT NULL,
    benchmark_price REAL NOT NULL,
    benchmark_ma20 REAL NOT NULL,
    panic_index REAL NOT NULL,
    overheat_index REAL NOT NULL,
    instructions_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_key, trade_date, signal_hash)
);

-- 1.5 Webhook 消息通知推送日志表
CREATE TABLE IF NOT EXISTS notification_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT REFERENCES signal_history(signal_id) ON DELETE SET NULL,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    is_alert INTEGER NOT NULL,
    sent_status TEXT NOT NULL,
    http_code INTEGER,
    response_body TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_id);
CREATE INDEX IF NOT EXISTS idx_orders_account_date ON trade_orders(account_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_signals_strategy_date ON signal_history(strategy_key, trade_date);
