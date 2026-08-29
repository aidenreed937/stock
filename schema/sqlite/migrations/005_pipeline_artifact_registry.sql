-- ====================================================================
-- Migration 005: 分析产物运行索引、数据血统、指标快照与生命周期表
-- ====================================================================

-- 5.1 管线运行主表 (替代 run_index.json)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,                       -- 运行唯一标识 (如 'run_20260829T110000_a1b2c3d4')
    pipeline_name TEXT NOT NULL,                  -- 管线名称 (如 'market_temperature', 'macro_risk')
    as_of_date DATE NOT NULL,                     -- 业务日期 (YYYY-MM-DD)
    run_class TEXT NOT NULL DEFAULT 'official',  -- 'official' | 'backfill' | 'experiment'
    status TEXT NOT NULL DEFAULT 'succeeded',    -- 'succeeded' | 'failed' | 'stale'
    is_latest INTEGER NOT NULL DEFAULT 0,        -- 是否为当前 latest 软链指向 (0/1)
    is_pinned INTEGER NOT NULL DEFAULT 0,        -- 是否锁定保护 (不可清理, 0/1)
    git_commit TEXT,                             -- 生成时的 Git 提交哈希
    artifact_root TEXT NOT NULL,                 -- 物理根目录路径
    duration_ms INTEGER DEFAULT 0,               -- 运行耗时 (毫秒)
    generated_at TIMESTAMP NOT NULL,             -- 产物生成时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5.2 上游数据血统与依赖水位表 (用于上游变更影响面反查)
CREATE TABLE IF NOT EXISTS run_watermarks (
    run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    data_source TEXT NOT NULL,                   -- 数据源 (如 'tushare', 'lixinger', 'fred')
    dataset_name TEXT NOT NULL,                  -- 数据集 (如 'daily_bars', 'macro_risk')
    upstream_watermark DATE,                     -- 消费的上游最大数据日期
    upstream_synced_at TIMESTAMP,                -- 上游数据同步时间
    PRIMARY KEY (run_id, data_source, dataset_name)
);

-- 5.3 核心量化指标快照表 (用于跨天时序分析与多版本 Run Diff)
CREATE TABLE IF NOT EXISTS run_metrics (
    run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,                    -- 指标键 (如 'temperature_score', 'panic_index')
    metric_value REAL NOT NULL,                  -- 指标数值
    PRIMARY KEY (run_id, metric_key)
);

-- 5.4 产物物理文件清单表 (用于完整性校验与安全清理)
CREATE TABLE IF NOT EXISTS run_files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    file_type TEXT NOT NULL,                     -- 'REPORT_MD' | 'CHART_PNG' | 'PANEL_PARQUET' | 'MANIFEST_JSON' | 'SUMMARY_JSON'
    rel_path TEXT NOT NULL,                      -- 相对产物目录路径
    file_size_bytes INTEGER NOT NULL,            -- 文件字节大小
    sha256_hash TEXT                             -- 文件校验哈希
);

CREATE INDEX IF NOT EXISTS idx_runs_pipe_date ON pipeline_runs(pipeline_name, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_watermarks_lookup ON run_watermarks(dataset_name, upstream_watermark);
CREATE INDEX IF NOT EXISTS idx_run_metrics_key ON run_metrics(metric_key, metric_value);
