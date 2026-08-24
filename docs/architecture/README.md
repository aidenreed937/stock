# 系统架构文档目录

本目录提供项目架构和数据工程文档的导航。稳定包边界见 [`../architecture.md`](../architecture.md)，领域操作流程由 `.agents/skills/` 维护。

---

## 架构导航索引

| 文档 | 说明 | 关键涉及类/模块 |
| :--- | :--- | :--- |
| **[1. 核心数据管道](data_pipeline.md)** | 从采集到 Curated 的 ETL 阶段和关键类 | `DailySyncEngine`, `MarketDataPipeline`, `GenericCleaner`, `GenericNormalizer`, `ParquetPartitionWriter` |
| **[2. 数据存储与分区架构](../data_architecture.md)** | RAW/Curated 存储分层、分区和 `DataCatalog` | `PartitionStore`, `RawDataStorage`, `DuckDBMarketStore`, `DataCatalog` |
| **[3. 数据管道 Skill](../../.agents/skills/data-pipeline/SKILL.md)** | 回填、同步、质量与审计工作流 | `stock_cli.sync`, `stock_cli.backfill`, `stock_cli.audit` |
| **[4. 系统架构概览](overview.md)** | 当前源码包、依赖方向与数据生命周期 | `src/stock_*` |
| **[5. 领域职责地图](domain-responsibilities.md)** | 顶级领域、Analytics 分层、业务域和外部调用入口 | `src/stock_*` |
| **[6. Analytics 分层边界](analytics-boundaries.md)** | 依赖方向、公共导入和拆分门禁 | `src/stock_analytics/`, `scripts/lint_analytics_boundaries.py` |

---

## 核心设计理念

1. **RAW/Curated 存储分层**：
   - **`data/raw/`**：100% 原始 API 响应快照（追加写、保留源端所有字段），确保任何清洗逻辑变更都可纯本地重新精炼。
   - **`data/curated/`**：黄金事实表（`pl.Date` 类型统一、主键去重、时序排布、注入统一数据血统），为策略和分析的唯一事实消费标准。
2. **契约驱动与零 Schema 漂移**：
   - 注册表集中声明主键与核心字段；
   - 系统血统元数据（`SYSTEM_METADATA_COLUMNS`）与业务指标字段严格解耦；
   - 存储层具备 Fail-Closed 快速失败防污染门禁。
3. **无状态增量与波次调度**：
   - 拒绝常驻后台守护进程，采用无状态 CLI 任务引擎 `DailySyncEngine`；
   - 自动水位感知（Watermark）与断点自愈；
   - 顺应上游数据源发布节奏（17:15, 18:15, 09:15）三波次调度。
