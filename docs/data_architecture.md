# 金融数据仓库与多数据源采集存储架构指南

本文档详细说明了金融股票分析系统中 **RAW + Curated 两层数据存储架构**、**时间分区归档规范**、**数据血统（Data Lineage）追踪** 及 **TuShare 多接口并发限频管理机制**。

---

## 1. 数据架构总体概览 (Architecture Overview)

系统采用标准的 **Data Lakehouse 两层存储架构**，实现采集、清洗、存储与策略分析的完全解耦：

```text
                  ┌─────────────────────────────────────────┐
                  │ 外部数据源 (TuShare / LiXinger / Yahoo Finance / FRED) │
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
                  │    按数据源隔离 + 标准化 Parquet          │
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
| **`data/raw/`** | **原始归档层**<br>(Raw Landing Zone) | `data/raw/{data_source}/market={market}/{dataset}/[year=YYYY/month=MM/]data.parquet` | 原汁原味保留 API 响应列与格式，按 `market={market}` 路径与 Curated 层 100% 镜像对称。<br>**主要作用：防重复请求、节省积分、支持本地离线重洗。** |
| **`data/curated/`** | **精炼生产层**<br>(Curated Zone) | `data/curated/{data_source}/market={market}/{dataset}/[year=YYYY/month=MM/]data.parquet` | 遵循 [Schema v2 规范](file:///Users/mac/workspace/personal/finance/stock/docs/standards/schema_v2_spec.md)（统一列名、`pl.Date` 类型与 SI 元/股计量单位），按 `market={market}` 隔离并注入 `data_source`、`updated_at` 与 `schema_version="v2"` 血统。<br>**主要作用：供策略回测与分析引擎直接使用。** |
| **`data/cache/`** | **临时缓存层**<br>(Transient Zone) | `data/cache/*.parquet` | 存储运行过程中的密集型计算中间结果（如长周期特征矩阵），可随时安全清空。 |

---

## 3. RAW 层时间分区设计规范 (Time Partitioning Rules)

### 3.1 路径与文件名规范
- **文件路径**：`data/raw/{data_source}/market={market}/{dataset}/year={YYYY}/month={MM}/data.parquet`
- **目录样例**：`data/raw/tushare/market=CN/stock_daily_bar/year=2026/month=08/data.parquet`

### 3.2 命名与设计原理
1. **`stock_daily_bar` (数据集目录)**：标识项目标准数据集名，和上游 API 名解耦。
2. **`year=YYYY/month=MM` (业务日期分区)**：按业务日期落入月份分区，文件名固定为 `data.parquet`。
3. **小文件防爆与高性能**：按月（`month=MM`）划分子目录，避免因按天划分导致生成上万个嵌套小文件夹，同时兼顾 Polars / DuckDB 谓词下推与分区裁剪开销。

---

## 4. RAW 与 Curated 层的分工与对比

| 对比维度 | RAW 原始层 (`data/raw/`) | Curated 精炼层 (`data/curated/`) |
| :--- | :--- | :--- |
| **组织维度** | **按交易日维度** (Batch by Trade Date) | **按数据源 + 交易日维度** (Partitioned by Source and Trade Date) |
| **单文件内容** | 包含单交易日 + 全市场 5000+ 股票的原始响应合集。 | 包含一个数据源、一个数据集和一个业务日期的标准化行情快照。 |
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

## 6. 全市场历史数据回填器 (HistoricalBackfiller)

- **严格交易日历对齐**：必须要求 Fetcher 提供 `fetch_trade_cal` 接口获取精确开市交易日，严禁粗暴按周一至周五推算（若缺乏日历接口则主动抛出 `DataFetchError` 拦截）。
- **断点续传与无损跳过**：回填前自动检索 `data/raw/` 时间分区，若已存在当天的 RAW 文件且未开启 `force_refresh` 则自动跳过，保障任务随时中断与恢复。
- **数据源隔离与 fail-closed 校验**：Curated 默认按 `data_source` 建目录；写入前校验 `data_source`、`DatasetKey.provider`、`daily_bar` 契约和已有文件 schema。来源或 schema 不一致时拒绝写入，不使用隐式列合并。
- **命令行快捷调用**：
  ```bash
  make backfill START=2026-08-01 END=2026-08-12
  ```

---

## 7. 常用操作指令 (Cheat Sheet)

```bash
# 1. 运行完整代码规范检查、类型检查与单元测试
make check

# 2. 手动初始化数据目录结构
uv run python -c "from stock.config.settings import settings; settings.setup_directories()"

# 3. 运行历史数据回填任务
make backfill START=2026-08-01 END=2026-08-12

# 4. 执行主项目入口与 YAML 驱动测试
make run
```

---

## 7. 数据字段数值单位规约 (Data Field Units Specification)

在处理 TuShare API 在线数据与本地 DuckDB Curated 数据仓库时，需特别注意数值单位的归一化映射：

| 数据集 | 字段名称 (`Field`) | 在线 API 原始单位 | 本地 DuckDB 归档单位 | 换算公式 / 阈值比较说明 |
| :--- | :--- | :--- | :--- | :--- |
| `daily_basic` | `circ_mv` (流通市值) | 万元 | **元 (Yuan)** | $15\text{ 亿元} = 15 \times 10^8 = 1.5 \times 10^9\text{ 元}$ |
| `daily_basic` | `total_mv` (总市值) | 万元 | **元 (Yuan)** | $15\text{ 亿元} = 1.5 \times 10^9\text{ 元}$ |
| `stock_daily_bar` | `amount` (成交额) | 元 / 千元 | **元 (Yuan)** | $3000\text{ 万元} = 3 \times 10^7\text{ 元}$ |

> [!CAUTION]
> **开发规约避坑提醒**：在编写策略或初筛过滤逻辑（如 `UniverseFilter`）时，所有基于 DuckDB 本地库的市值比较必须统一换算为**元（RMB）**作为基准，禁止直接套用 TuShare 在线 API 的“万元”口径（会导致市值阈值被误降 $10000$ 倍而失效）。
