# 系统架构文档目录 (Architecture Directory)

本项目量化投研系统采用 **2-Tier（RAW / Curated）数据流湖仓一体架构**，实现了从多源异构数据获取、数据清洗、统一标准化、Hive 分桶持久化到因子计算与策略回测的完整闭环。

---

## 架构导航索引

| 文档 | 说明 | 关键涉及类/模块 |
| :--- | :--- | :--- |
| **[1. 核心数据管道与 6 大类](file:///Users/mac/workspace/personal/finance/stock/docs/architecture/data_pipeline.md)** | 数据从采集到落盘的 2-Tier ETL 全生命周期与 6 大核心类职责详解 | `DailySyncEngine`, `Fetcher`, `MarketDataPipeline`, `Cleaner`, `Normalizer`, `ParquetPartitionWriter` |
| **[2. 数据存储与分区架构](file:///Users/mac/workspace/personal/finance/stock/docs/data_architecture.md)** | RAW/Curated 存储分层、Hive 年月分区结构、DuckDB 统一查询与 Schema 规范 | `PartitionStore`, `RawDataStorage`, `DuckDBMarketStore`, `DataCatalog` |
| **[3. 数据管道实操指南](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-pipeline/SKILL.md)** | 历史回填、每日增量、Crontab 调度波次、多维对账审计与 CLI 命令速查 | `stock.cli.sync`, `stock.cli.backfill`, `stock.cli.audit` |
| **[4. 系统总体设计概述](file:///Users/mac/workspace/personal/finance/stock/docs/architecture/overview.md)** | 系统总体分层设计、模块交互与依赖关系 | `src/stock/` 各子系统 |

---

## 核心设计理念

1. **2-Tier 存储分层**：
   - **`data/raw/`**：100% 原始 API 响应快照（追加写、保留源端所有字段），确保任何清洗逻辑变更都可纯本地重新精炼。
   - **`data/curated/`**：黄金事实表（`pl.Date` 类型统一、主键去重、时序排布、注入统一数据血统），为策略回测与因子计算的唯一消费标准。
2. **契约驱动与零 Schema 漂移**：
   - 注册表集中声明主键与核心字段；
   - 系统血统元数据（`SYSTEM_METADATA_COLUMNS`）与业务指标字段严格解耦；
   - 存储层具备 Fail-Closed 快速失败防污染门禁。
3. **无状态增量与波次调度**：
   - 拒绝常驻后台守护进程，采用无状态 CLI 任务引擎 `DailySyncEngine`；
   - 自动水位感知（Watermark）与断点自愈；
   - 顺应上游数据源发布节奏（17:15, 18:15, 09:15）三波次调度。
