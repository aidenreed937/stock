# Analytics 分层边界

本文档定义 `stock_analytics` 的稳定入口、职责边界和依赖方向。代码实现可以继续演进，但新增模块必须遵守这些边界。

## 分层职责

| 层 | 负责内容 | 输入 | 输出与持久化 |
| --- | --- | --- | --- |
| `primitives` | 纯数学、技术指标和无状态规则算子 | DataFrame、标量或序列 | 纯计算结果，不读目录、不写文件 |
| `metrics` | 按 `MetricSpec` 从 Curated 数据集计算通用指标 | `MetricContext`、`DataCatalog` | 指标结果或临时指标表，不负责 Mart 写入 |
| `features` | 可复用特征的定义、版本、血缘和物化 | Curated 数据集、primitives | `FeatureStore` 宽表/长表及元数据 |
| `marts` | 具有领域语义的聚合事实表 | Curated 数据集、FeatureStore | Domain Mart |
| `pipelines` | 日期窗口、事实组合、评分和产物编排 | metrics、features、marts | 报告、manifest、scores 和运行产物 |
| `reporting` | 报告模板和解释 | pipeline 产物 | Markdown/JSON 等展示结果 |

### 选择落点的规则

1. 只有公式、没有数据访问和业务状态的逻辑放入 `primitives`。
2. 需要按规格读取数据、按窗口计算且不需要持久化的逻辑放入 `metrics`。
3. 被多个管线复用，或需要定义版本、来源水位、输入指纹和增量物化的逻辑放入 `features`。
4. 具有明确领域主键和稳定表结构的聚合事实放入 `marts`。
5. 组合多个事实、应用业务评分或生成报告的逻辑放入 `pipelines`。

如果同一公式同时被 `metrics` 和 `features` 使用，应先抽到 `primitives`，不要让两个上层模块互相依赖。

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
from stock_analytics.features import FeatureStore
from stock_analytics.metrics import MetricEngine
from stock_analytics.pipelines.market_temperature import run_market_temperature
from stock_analytics.primitives import calculate_rsi
```

`pipeline.py`、`facts.py`、`scoring.py`、`panel.py` 等实现文件可以保留兼容导出，但不作为新的外部依赖入口。拆分大文件时应优先保留这些兼容门面，再逐步迁移调用方。

## 大管线拆分约束

市场温度计按事实主题拆分为基本面、情绪、宏观和通用事实工具；行业结构按面板构建、批量聚合、评分和诊断拆分。每个拆分模块必须满足：

- 不改变原有事实 Schema、metric ID、score key 和日期截断规则；
- 叶子模块不得反向导入门面模块，避免循环依赖；
- 兼容门面只做编排和重导出，不新增业务规则；
- 先用现有测试锁定行为，再抽取共享批处理上下文。
