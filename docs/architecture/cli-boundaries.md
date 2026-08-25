# CLI 领域边界

`stock_cli` 是应用入口层，不是领域实现层。CLI 命令只负责参数解析、调用公开 Facade、输出结果和转换错误码。

## 领域映射

| CLI 领域 | 命令 | 领域实现归属 |
| --- | --- | --- |
| 数据工程 | `sync`、`backfill`、`audit` | `stock_data.pipeline`、`stock_data.governance` |
| 分析管线 | `market-temperature`、`market-context`、`industry-structure`、`multi-date`、`features` | `stock_analytics.pipelines`、`stock_analytics.features`、`stock_analytics.marts` |
| 研究诊断 | `diagnose`、`industry-diagnose`、`stock-screen`、`scan-watchlist`、`thesis-review` | `stock_analytics.pipelines` |
| 报告复盘 | `daily-review`、`investor-brief`、`quant-brief` | `stock_analytics.pipelines`、`stock_reporting` |
| 实时监控 | `realtime`、`market-aggregate` | `stock_analytics.realtime`、`stock_data.fetcher.realtime` |
| 运维 | `artifact-ops` | `stock_analytics.pipelines.artifact_*`、`stock_data.governance` |

## 依赖规则

允许：

```text
stock_cli → 领域包级 Facade → 领域内部实现
```

禁止 CLI 直接：

- 读取 `data/` 下的 JSON、Parquet 或目录结构；
- 使用 `DataCatalog`、`FeatureStore`、`DomainMartBuilder`；
- 导入 `pipeline.py`、`scoring.py`、`artifacts.py` 等内部实现；
- 计算指标、评分、风险、仓位或业务 Context；
- 直接拼装报告业务字段。

## 兼容迁移策略

保留现有 `python -m stock_cli.<command>` 路径作为兼容适配器；实际业务入口下沉到 `stock_data`、`stock_analytics` 或 `stock_reporting` 的包级 Facade。迁移完成后再考虑物理移动 CLI 文件，不在第一阶段破坏 Makefile、Skill 和用户脚本。

## 当前迁移状态

- 已完成：`daily_review` → `stock_analytics.pipelines.daily_review`。
- 当前批次：`features` → `stock_analytics.pipelines.features`；`multi_date` 的日期解析、Mart 刷新、产物生成、一致性校验和 latest 发布 → `stock_analytics.pipelines.multi_date`。
- 后续批次：`backfill`、`audit`、`sync`、`realtime` 和 `artifact_ops`。
