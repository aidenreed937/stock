# 金融数据仓库与多数据源采集存储架构指南

本文档详细说明了金融股票分析系统中 **RAW + Curated 两层数据存储架构**、**时间分区归档规范**、**数据血统（Data Lineage）追踪** 及 **TuShare 多接口并发限频管理机制**。

---

## 1. 数据架构总体概览 (Architecture Overview)

系统采用标准的 **Data Lakehouse 两层存储架构**，实现采集、清洗、存储与策略分析的完全解耦：

```text
                  ┌─────────────────────────────────────────┐
                  │ 外部数据源 (TuShare / AKShare / Mock)     │
                  └────────────────────┬────────────────────┘
                                       │ (1. Fetcher 接口拉取)
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │ 1. RAW 原始归档层 (data/raw/)             │
                  │ Hive-style 时间分区: year=YYYY/month=MM   │
                  └────────────────────┬────────────────────┘
                                       │ (2. 离线缓存优先 / ETL 重放)
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │ 2. Cleaner 清洗 ➔ Normalizer 标准化       │
                  │    数据质量拦截 + 注入 data_source 血统     │
                  └────────────────────┬────────────────────┘
                                       │ (3. Curated 精炼落盘)
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │ 3. Curated 精炼存储层 (data/curated/)    │
                  │    DuckDB SQL 索引 + 标准化 Parquet       │
                  └────────────────────┬────────────────────┘
                                       │ (4. 零拷贝分析对接)
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │ 4. Analytics 分析层 ➔ Strategy 策略层    │
                  └─────────────────────────────────────────┘
```

---

## 2. `data/` 目录结构与分层规范 (Directory Specification)

项目根目录下的 `data/` 统一划分为 3 个核心主目录：

| 目录名称 | 分层定位 | 存储规范 / 路径结构 | 说明与核心作用 |
| :--- | :--- | :--- | :--- |
| **`data/raw/`** | **原始归档层**<br>(Raw Landing Zone) | `data/raw/{data_source}/{endpoint}/year=YYYY/month=MM/{endpoint}_{YYYYMMDD}.parquet` | 原汁原味保留 API 响应列与格式，按交易日合集保存全市场行情。<br>**主要作用：防重复请求、节省积分、支持本地离线重洗。** |
| **`data/curated/`** | **精炼生产层**<br>(Curated Zone) | `data/curated/parquet/daily_{symbol}.parquet`<br>`data/curated/market_data.duckdb` | 规范化 Schema（统一列名、统一类型），注入 `data_source` 与 `updated_at` 血统。<br>**主要作用：供策略回测与分析引擎直接使用。** |
| **`data/cache/`** | **临时缓存层**<br>(Transient Zone) | `data/cache/*.parquet` | 存储运行过程中的密集型计算中间结果（如长周期特征矩阵），可随时安全清空。 |

---

## 3. RAW 层时间分区设计规范 (Time Partitioning Rules)

### 3.1 路径与文件名规范
- **文件路径**：`data/raw/{data_source}/{endpoint}/year={YYYY}/month={MM}/{endpoint}_{YYYYMMDD}.parquet`
- **目录样例**：`data/raw/tushare/daily/year=2026/month=08/daily_20260812.parquet`

### 3.2 命名与设计原理
1. **`daily` (前缀)**：标识 API 接口名（如 `daily` - 日线行情, `income` - 利润表, `daily_basic` - 每日指标）。
2. **`20260812` (中间日期)**：数据的**业务交易日 (Trade Date)**。固定 8 位补零保证文件按文件名正序排列时天然等于按时间先后升序排列。
3. **小文件防爆与高性能**：按月（`month=MM`）划分子目录，避免因按天划分导致生成上万个嵌套小文件夹，同时兼顾 Polars / DuckDB 谓词下推与分区裁剪开销。

---

## 4. RAW 与 Curated 层的分工与对比

| 对比维度 | RAW 原始层 (`data/raw/`) | Curated 精炼层 (`data/curated/`) |
| :--- | :--- | :--- |
| **组织维度** | **按交易日维度** (Batch by Trade Date) | **按股票标的维度** (Partitioned by Symbol) |
| **单文件内容** | 包含单交易日 + 全市场 5000+ 股票的原始响应合集。 | 包含单只股票 + 跨越过去数年（2020~2026）的全部历史 K 线。 |
| **Schema 列名** | API 原始异构列名（如 `ts_code`, `vol`）。 | 统一规范列名（`symbol`, `trade_date`, `open`, `high`, `low`, `close`, `volume`）。 |
| **元数据追踪** | 无 | 注入 `data_source`（数据源）与 `updated_at`（入库时间戳）。 |
| **适用场景** | 盘后批量增量采集、网络断网离线重洗。 | 策略回测、指标计算、高频量化分析。 |

---

## 5. TuShare 接口管理与并发限频配置

在 `.env` 或环境变量中可独立配置 TuShare 的并发与限频参数：

```ini
# .env 配置文件
TUSHARE_TOKEN=your_tushare_token
TUSHARE_URL=http://api.tushare.pro

# 每分钟最大请求次数（根据积分等级调整）
TUSHARE_RATE_LIMIT_PER_MIN=200

# 多 Worker 线程池并发采集线程数
TUSHARE_MAX_WORKERS=4
```

- **滑动窗口限频器 (RateLimiter)**：线程安全监控近 60 秒内的请求频次，触发限制时自动平滑休眠，防止 429 报错。
- **多 Worker 并发切片合并 (slicer.py)**：自动将多代码请求切分为每 50 只一组，利用 `ThreadPoolExecutor` 并行提取并合并为 Polars 数据帧。

---

## 6. 常用操作指令 (Cheat Sheet)

```bash
# 1. 运行完整代码规范检查、类型检查与单元测试
make check

# 2. 手动初始化数据目录结构
uv run python -c "from stock.config.settings import settings; settings.setup_directories()"

# 3. 执行主项目入口与 YAML 驱动测试
make run
```
