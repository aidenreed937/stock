-- ====================================================================
-- Migration 003: 数据源断点续传水位与 API 频次配额表
-- ====================================================================

CREATE TABLE IF NOT EXISTS sync_watermarks (
    dataset_name TEXT NOT NULL,
    data_source TEXT NOT NULL,
    last_synced_date DATE NOT NULL,
    last_synced_at TIMESTAMP NOT NULL,
    row_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (dataset_name, data_source)
);

CREATE TABLE IF NOT EXISTS api_call_logs (
    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_ms INTEGER,
    points_spent INTEGER DEFAULT 0,
    status_code INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_logs_source_called ON api_call_logs(source, called_at);
