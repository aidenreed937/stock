# Analytics 分层边界

本文只定义 `stock_analytics` 的依赖方向、公共导入和可机器检查的拆分规则。领域职责、业务域归属和新需求落点见 [`domain-responsibilities.md`](domain-responsibilities.md)。

## 依赖方向

生产代码遵循以下方向（箭头表示“依赖”）：

```text
metrics   ─┐
features  ─┼──> primitives
marts     ─┘

pipelines ───> metrics / features / marts / reporting
```

禁止以下依赖：

- `primitives` 读取 `DataCatalog`、`FeatureStore` 或写物理文件；
- `metrics` 依赖 `features` 或直接写入 `FeatureStore`；
- `features` 依赖 `pipelines`；
- `pipelines` 直接遍历 `data/` 下的 Parquet 物理目录；
- `stock_cli`、`stock_strategy` 直接导入 `pipeline.py`、`scoring.py` 等实现模块。

## 公共 API 规则

外部消费者只从包级门面导入：

```python
from stock_analytics.api import AnalyticsContext, compute_features, compute_metrics
from stock_analytics.features import FeatureStore
from stock_analytics.metrics import MetricEngine
from stock_analytics.pipelines.market_temperature import run_market_temperature
from stock_analytics.primitives import calculate_rsi
```

其中 `stock_analytics.api` 是 metrics/features 的统一外部调用入口；
`marts` 和 `pipelines` 仍分别通过各自的包级门面提供领域 Mart 构建与业务流程编排。
外部消费者不应因此直接导入 `metrics`、`features` 或 `marts` 下的内部实现模块。

`pipeline.py`、`facts.py`、`scoring.py`、`panel.py` 等实现文件可以保留兼容导出，但不作为新的外部依赖入口。拆分大文件时应优先保留这些兼容门面，再逐步迁移调用方。

## 大管线拆分约束

市场温度计按事实主题拆分为基本面、情绪、宏观和通用事实工具；行业结构按面板构建、批量聚合、评分和诊断拆分。每个拆分模块必须满足：

- 不改变原有事实 Schema、metric ID、score key 和日期截断规则；
- 叶子模块不得反向导入门面模块，避免循环依赖；
- 兼容门面只做编排和重导出，不新增业务规则；
- 先用现有测试锁定行为，再抽取共享批处理上下文。
