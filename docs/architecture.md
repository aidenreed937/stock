# 项目数据与系统架构设计文档

本文档详细说明了金融股票数据分析脚手架的分层架构设计、数据管道流转机制与系统设计原则。

## 1. 系统总体架构

系统采用高内聚、低耦合的分层架构，核心数据流向如下：

```
[外部 API / 数据源] (TuShare / LiXinger / Yahoo Finance / FRED)
        │
        ▼
 [1. Fetcher 抓取层] ──(Raw Data)──► [RAW 原始归档层 (data/raw/)]
                                     (Hive-style 时间分区: year=YYYY/month=MM)
                                                │
                                       (Raw Polars DataFrame)
                                                │
                                                ▼
                                     [2. Cleaner 清洗层] ➔ [3. Normalizer 标准化层]
                                                                  │
                                                (Standard DataFrame + Data Lineage)
                                                                  │
                                                                  ▼
 [5. Analytics 分析层] ◄──(Zero-Copy)──► [4. Curated 精炼存储层 (data/curated/)]
(Polars SMA/EMA/RSI)                       (DuckDB + Parquet)
        │
        ▼
 [6. Strategy 策略与风控层] (基于 YAML 强类型配置驱动)
```

---

## 2. 核心分层详解

### 2.1 配置驱动层 (`src/stock/config` & `config/`)
- **环境配置 (`settings.py`)**：基于 `pydantic-settings` 管理全局环境（日志级别、存储基准路径、API Key）。不进 Git 的敏感密钥在 `.env` 中维护。
- **业务/策略配置 (`loader.py` & `models/config.py`)**：策略参数与指标周期从 `config/*.yaml` 动态读取，通过 Pydantic 转换为强类型 `StrategyConfig` 对象，彻底解耦硬编码。

### 2.2 数据 ETL 管道层 (`src/stock/data/`)
- **Fetcher (`fetcher/`)**：专注网络请求、重试与接口协议适配，输出原始数据帧。
- **Cleaner (`cleaner/`)**：对原始数据执行合法性校验（如 `high >= low`、价格 `> 0`）、空值处理与去重。
- **Normalizer (`normalizer/`)**：将异构列名（如 `ts_code`/`code`/`vol`）映射为统一标准规范字段，统一日期类型 (`pl.Date`) 与排序。
- **Pipeline (`pipeline.py`)**：编排上述三者与存储层，提供一键同步函数 `sync_daily_bars()`。

### 2.3 存储引擎层 (`src/stock/data/storage/`)
- 基于 **DuckDB + Parquet** 列式持久化。
- 提供本地高效 SQL 检索接口，数据零拷贝接入 `Polars` 向量化分析引擎。

### 2.4 分析计算层 (`src/stock/analytics/`)
- 基于 `Polars` 向量化表达计算指标（如 `calculate_sma`, `calculate_rsi`），极大提升分析性能。

---

## 3. 核心数据流动原则

系统中的数据流转严格遵循以下 5 大设计原则：

1. **单向不可逆原则 (Unidirectional Data Flow)**：数据仅沿着 `Fetcher ➔ Cleaner ➔ Normalizer ➔ Storage ➔ Analytics ➔ Strategy` 单向流动，禁止跨层反向依赖。
2. **门禁契约与脏数据拦截 (Schema-First & Quality Gate)**：数据进入 `Storage` 前必须在 `Cleaner` 与 `Normalizer` 完备通过合法性校验与标准 Schema 转换，确保库内无脏数据。
3. **数据不可变性 (Immutability)**：基础行情 OHLCV 列在后续流转中只读；分析层指标通过追加派生列的方式生成新视图。
4. **零拷贝与高效传输 (Zero-Copy Transfer)**：全程以 Polars / Apache Arrow 内存结构传递，存储层与分析层之间实现零拷贝数据对接。
5. **无状态与依赖注入 (Stateless & Injectable Flow)**：Cleaner 与 Normalizer 均为纯无状态转换模块；Pipeline 管道通过依赖注入管理数据流，便于单元测试与隔离验证。

---

## 4. 质量保障与硬约束

- **编码标准**：通过 `.editorconfig` 约定缩进与换行，全局字符集使用 UTF-8。
- **静态检查**：Ruff 拦截格式与代码规范，Mypy 在 `strict` 模式及 Pydantic 插件下校验类型。
- **自动化流**：通过 `pre-commit` 门禁与 GitHub Actions CI 实现云与端双重质检拦截。
