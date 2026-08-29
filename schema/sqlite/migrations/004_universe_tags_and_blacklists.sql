-- ====================================================================
-- Migration 004: 标的元数据、多维特征标签与排雷风控黑名单表
-- ====================================================================

-- 4.1 标的基础元数据表
CREATE TABLE IF NOT EXISTS symbols_meta (
    symbol TEXT PRIMARY KEY,             -- 标的代码 (如 '510880.SH', '000300.SH', '600519.SH')
    name TEXT NOT NULL,                  -- 标的名称 (如 '红利ETF', '沪深300', '贵州茅台')
    asset_type TEXT NOT NULL,            -- 'STOCK' | 'ETF' | 'INDEX'
    exchange TEXT NOT NULL DEFAULT '',   -- 'SSE' | 'SZSE' | 'BSE'
    is_active INTEGER NOT NULL DEFAULT 1,-- 是否在市/有效 (0/1)
    base_date DATE,                      -- 基准/上市日期
    description TEXT DEFAULT '',         -- 标的描述
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4.2 标的多维特征标签表 (多对多)
CREATE TABLE IF NOT EXISTS symbol_tags (
    symbol TEXT NOT NULL REFERENCES symbols_meta(symbol) ON DELETE CASCADE,
    tag_name TEXT NOT NULL,              -- 标签名 (如 '核心宽基', '高股息', '中字头', '防守资产', '成长进攻')
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, tag_name)
);

-- 4.3 排雷与风控黑名单表
CREATE TABLE IF NOT EXISTS risk_blacklists (
    blacklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL REFERENCES symbols_meta(symbol) ON DELETE CASCADE,
    reason TEXT NOT NULL,                -- 拉黑原因 (如 '立案调查', 'ST退市风险', '股权质押率超标', '流动性枯竭')
    severity TEXT NOT NULL DEFAULT 'CRITICAL', -- 'CRITICAL' (强制禁买) | 'WARNING' (预警)
    start_date DATE NOT NULL,            -- 拉黑生效起始日
    end_date DATE,                       -- 解除日期 (NULL 表示长期有效)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_symbol_tags_tag ON symbol_tags(tag_name);
CREATE INDEX IF NOT EXISTS idx_blacklists_symbol ON risk_blacklists(symbol);
CREATE INDEX IF NOT EXISTS idx_blacklists_active ON risk_blacklists(symbol, start_date, end_date);
