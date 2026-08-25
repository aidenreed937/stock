# 领域职责地图

本文是项目的职责索引，回答三个问题：一项能力属于哪个领域、应该落在哪一层、外部调用方从哪里进入。

实现细节、字段、公式和 CLI 参数仍以当前代码、配置、测试、`--help` 和 Manifest 为准；本文只维护稳定边界。Analytics 分层的依赖门禁见 [`analytics-boundaries.md`](analytics-boundaries.md)，数据存储细节见 [`../data_architecture.md`](../data_architecture.md)。

## 1. 一句话边界

```text
stock_data 负责把外部数据变成可信 Curated 事实
    ↓
stock_analytics 负责把事实变成指标、特征、领域 Mart 和分析产物
    ↓
stock_strategy / stock_reporting 负责研究决策与人类可读表达
    ↓
stock_cli 负责参数、任务编排和终端交互
```

外部 API、RAW、Curated 和数据质量属于 `stock_data`；Analytics 不直接请求远程数据源，也不把原始响应当作事实输入。

## 2. 顶级源码包职责

| 领域 | 代码入口 | 负责内容 | 不负责内容 |
| --- | --- | --- | --- |
| 基础契约 | `src/stock_core/` | 数据契约、领域模型、配置、常量、异常和运行时上下文 | 业务指标、报告和数据源请求 |
| 数据工程 | `src/stock_data/` | Fetcher、TaskRegistry、RAW/Curated ETL、存储、质量、审计和数据目录 | 指标解释、策略信号和报告渲染 |
| 分析计算 | `src/stock_analytics/` | 纯算子、通用指标、可复用特征、领域事实和分析管线 | 远程 API 采集和最终交易执行 |
| 策略研究 | `src/stock_strategy/` | 策略上下文、信号生成、组合/回测运行器；`application` 提供研究应用 Facade | 自己维护数据源和分析层内部实现；应用 Facade 只调用公开数据管线 |
| 报告视图 | `src/stock_reporting/` | 模板、解释规则、Markdown/JSON 渲染 | 重新计算事实和指标 |
| 应用编排 | `src/stock_cli/` | 参数解析、任务组合、日志和终端输出 | 承载领域公式和业务规则 |
| 兼容门面 | `src/stock/` | 旧调用路径兼容 | 新能力的主要落点 |

## 3. Analytics 层职责

### 3.1 计算层

| 层 | 稳定职责 | 典型输入 | 稳定输出 | 边界 |
| --- | --- | --- | --- | --- |
| `primitives` | 纯数学、统计、技术指标和无状态规则 | DataFrame、标量、序列 | 新 DataFrame 或标量 | 不读目录、不访问 `DataCatalog`、不写文件 |
| `metrics` | 按 `MetricSpec` 计算可复用的时序/截面指标 | `MetricContext`、`DataCatalog`、Curated 数据集 | `MetricResult` 或临时指标表 | 不负责 Mart 写入，不依赖 `features` |
| `features` | 特征定义、版本、血缘、输入水位和物化 | Curated 数据集、primitives | `FeatureStore` 宽表/长表及元数据 | 不负责业务评分，不依赖 `pipelines` |
| `marts` | 具有领域主键和稳定 Schema 的聚合事实 | Curated 数据集、`FeatureStore`、必要的指标/算子 | Domain Mart | 不负责报告、评分和远程采集 |
| `pipelines` | 日期窗口、事实组合、评分、诊断和产物编排 | metrics、features、marts、配置 | scores、reports、Manifest 和运行目录 | 不直接遍历 `data/` 物理目录 |

### 3.2 公共调用入口

按能力使用不同入口，不把所有职责塞进一个“大门面”：

| 调用目标 | 外部入口 | 说明 |
| --- | --- | --- |
| 指标和特征读取/计算 | `stock_analytics.api` | `compute_metrics`、`compute_features`、`list_metrics`、`list_features`；这是 metrics/features 的统一外部入口 |
| 特征宽表构建和存储 | `stock_analytics.features` | `MarketDailyBuilder`、`FeatureStore` 等包级门面 |
| 领域 Mart 构建 | `stock_analytics.marts` | `DomainMartBuilder` 和领域 Mart 构建函数 |
| 业务分析流程 | `stock_analytics.pipelines.<domain>` | 市场温度、行业结构、个股诊断、简报等运行入口 |
| 纯计算算子 | `stock_analytics.primitives` | 只暴露无状态计算能力 |

`stock_analytics.api` 是调用边界，不是新的数据源 API，也不是 Mart 构建器。Mart 可以继续使用 `DataCatalog` 和 `FeatureStore` 完成领域特有的窗口、缓存、增量和写入逻辑。

## 4. 业务领域职责

业务领域可以跨越多个 Analytics 层，但每个领域只能有一个事实和流程的归属点。

| 业务领域 | 主要模块 | 负责内容 | 主要产物 |
| --- | --- | --- | --- |
| 市场状态与温度 | `marts/market_temperature.py`、`pipelines/market_temperature/`、市场类 metrics/features | 全市场宽度、流动性、资金、宏观、情绪和衍生品事实的窗口化组合与温度评分 | `market_temperature_derived_facts`、scores、报告 |
| 行业结构与轮动 | `marts/industry_structure.py`、`pipelines/industry_structure/`、行业 metrics | 申万一级行业日频事实、行业截面、面板、相对强弱和结构评分 | `industry_daily`、`industry_panel_daily`、行业诊断/报告 |
| 个股诊断与筛选 | `pipelines/stock_diagnostics/`、`pipelines/stock_screen/`、`pipelines/watchlist_scanner/` | 个股基本面、估值、技术、风险规则、观察池扫描和筛选决策 | 个股诊断、筛选结果、观察池扫描产物 |
| 衍生品与风险 | `marts/option_volatility.py`、`marts/convertible_bond.py`、`metrics` 的 derivatives 域 | 期权 PCR、结算价 IV 代理、期权标的行情和可转债聚合 | 衍生品指标、IV/可转债 Domain Mart |
| 公司行为 | `marts/corporate_actions.py` | 增减持、回购、大宗交易及其领域聚合 | 公司行为 Domain Mart |
| 实时市场监控 | `stock_analytics/realtime/`、`pipelines/market_aggregate/` | 核心观察池逐标的快照与全市场聚合摘要，区分实时快照和历史事实 | 实时快照、聚合摘要和质量报告 |
| 投研简报与论点复盘 | `pipelines/investor_brief/`、`pipelines/quant_brief/`、`pipelines/thesis_review/` | 组合已物化事实、评分和既有报告产物，形成面向人的简报和论点复盘 | Markdown/JSON 简报、Manifest、复盘产物 |

领域模块之间的关系是“共享事实、分别编排”，不是互相复制数据访问或业务规则。跨领域组合应放在 `pipelines`，而不是把评分逻辑塞回 `marts` 或 `metrics`。

## 5. 统一数据流

```text
外部数据源
  → stock_data Fetcher / TaskRegistry
  → data/raw/ 原始快照
  → Cleaner / Normalizer / Quality Gate
  → data/curated/ 标准化事实
       ├─→ metrics：按规格计算通用指标
       ├─→ features：计算并物化可复用特征
       └─→ marts：构建领域聚合事实
                ↓
           pipelines：窗口、组合、评分和产物编排
                ├─→ stock_reporting：解释与渲染
                └─→ stock_strategy：研究策略与信号
```

所有层都应保留来源、日期口径和缺失状态。`data/analytics/latest` 只是成功运行的展示副本，不是新的事实来源。

## 6. 新需求落点判断

| 新需求 | 首选落点 | 判断标准 |
| --- | --- | --- |
| 接入新上游 API 或新增数据集 | `stock_data` + TaskRegistry/Fetcher | 先落 RAW/Curated，再让分析层消费 |
| 新增公式或统计方法 | `stock_analytics/primitives` | 没有目录访问、业务状态或持久化 |
| 新增可复用指标 | `stock_analytics/metrics` | 按 MetricSpec、窗口和实体粒度计算，不直接写 Mart |
| 新增可复用特征 | `stock_analytics/features` | 需要版本、血缘、水位或物化宽表/长表 |
| 新增稳定领域事实 | `stock_analytics/marts` | 有明确领域主键、Schema、增量写入和审计需求 |
| 组合多个事实或生成评分/报告 | `stock_analytics/pipelines` | 需要日期窗口、业务规则、产物或 Manifest |
| 运行策略研究应用 | `stock_strategy.application` | 需要加载策略/数据配置、准备历史数据并调用 `StrategyRunner` |
| 给外部调用方提供统一读取入口 | `stock_analytics.api` | 只聚合 metrics/features，不绕过数据工程层 |

当一个需求同时涉及多个层时，先拆成“事实来源、纯计算、物化事实、流程编排”四部分，再分别落点；不要用一个跨层模块解决所有问题。

## 7. 文档分工

| 文档 | 唯一职责 |
| --- | --- |
| [`../architecture.md`](../architecture.md) | 顶级源码包、系统数据流和稳定架构摘要 |
| [`overview.md`](overview.md) | 架构入口导航和变更入口 |
| `domain-responsibilities.md` | 本文：领域职责、入口和需求落点 |
| [`analytics-boundaries.md`](analytics-boundaries.md) | Analytics 依赖方向、公共导入和拆分门禁 |
| [`../data_architecture.md`](../data_architecture.md) | RAW/Curated/Mart 存储和分区细节 |
| [`../plan/`](../plan/) | 未完成或已完成改造的实施计划、验收和后续任务 |
| [`../research/`](../research/) | 投研方法、基线、案例和阶段回顾，不定义代码依赖边界 |

职责发生变化时先更新本文和对应代码门禁，再在计划/研究文档中记录原因、影响和验证结果。
