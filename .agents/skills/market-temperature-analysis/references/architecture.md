# 市场温度计架构边界

## 目的

本文件说明项目当前真实包路径，以及通用指标、六维市场温度计、申万行业结构和报告渲染之间的职责边界。

## 总体关系

`config/analytics/market_temperature.yaml` 是六维市场温度计的唯一评分配置。它只声明维度权重、指标权重、方向、来源和数据集质量约束，不实现计算。

```text
DataCatalog 本地 Curated 黄金表
  ├─> stock_analytics.features.builders.market_daily
  │     └─> data/curated/mart/market_daily.parquet
  ├─> stock_analytics.metrics / MetricEngine
  │     └─> 通用指标事实
  └─> stock_analytics.pipelines.market_temperature.derived
        └─> 温度计专用派生事实

MetricEngine + FeatureStore + derived
  └─> stock_analytics.pipelines.market_temperature.facts
        └─> facts.parquet

facts + config/analytics/market_temperature.yaml
  ├─> stock_analytics.pipelines.market_temperature.scoring
  │     └─> scores.json
  ├─> stock_reporting.templates.market_temperature
  │     └─> report.md / human_report.md / report.json
  └─> stock_analytics.data_quality + stock_reporting.core.quality
        └─> quality_report.md / quality_report.json

DataCatalog + industry pipeline
  └─> stock_analytics.pipelines.industry_structure
        └─> industry_panel.parquet / scores.json / report.md
```

行业结构管线与市场温度计是同级应用。行业结构分只用于行业排序和轮动判断，不参与六维综合温度。

## 真实源码路径

| 目的 | 当前路径 | 职责 |
|---|---|---|
| 特征集市与领域 Mart | `src/stock_analytics/features/`、`src/stock_analytics/marts/` | 构建和读取 `market_daily.parquet` 及领域 Mart |
| 通用指标 | `src/stock_analytics/metrics/` | 注册、计算和返回可复用 `MetricResult.frame` |
| 市场温度计 | `src/stock_analytics/pipelines/market_temperature/` | 交易窗口、事实、派生指标、评分和产物编排 |
| 行业结构 | `src/stock_analytics/pipelines/industry_structure/` | 行业面板、子分、结构分和行业产物 |
| 评分配置加载 | `src/stock_reporting/interpretation/market_temperature/config.py` | 读取并转换市场温度 YAML |
| 温度转换 | `src/stock_analytics/pipelines/market_temperature/metric_temperature.py` | 将事实映射为 0-100 温度 |
| 六维评分 | `src/stock_analytics/pipelines/market_temperature/scoring.py` | 按方向、权重和可用性生成维度与综合温度 |
| 事实采集 | `src/stock_analytics/pipelines/market_temperature/facts.py` | 采集窗口、水位、MetricEngine、派生事实和短线事实 |
| 短线事实 | `src/stock_analytics/pipelines/market_temperature/short_term.py` | 从 `market_daily` 生成 5/10 日附加温度；每窗口只生成一行 |
| 可选观察事实 | `src/stock_analytics/pipelines/market_temperature/optional_facts.py`、`domain_mart_facts.py` | 读取领域 Mart 观察项，不进入六维主评分 |
| 领域 Mart 构建 | `src/stock_analytics/marts/builder.py`、`build_steps.py` | 从 Curated 输入构建可转债、公司行为和结算价波动率代理 Mart |
| 温度计派生事实 | `src/stock_analytics/pipelines/market_temperature/derived.py` | 基本面、情绪和宏观流动性派生温度 |
| 质量报告 | `src/stock_analytics/data_quality.py` | 基于 manifest、facts 和 YAML 生成质量 JSON |
| 质量报告渲染 | `src/stock_reporting/core/quality.py` | 将质量 JSON 渲染为 Markdown |
| 产物写入 | `src/stock_analytics/pipelines/market_temperature/artifacts.py` | 写入 runs 和 latest |
| 报告渲染 | `src/stock_reporting/templates/market_temperature.py` | 调用 Jinja2 模板生成报告 |
| 市场温度 CLI | `src/stock_cli/market_temperature.py` | 市场温度命令入口 |
| 行业结构 CLI | `src/stock_cli/industry_structure.py` | 行业结构命令入口 |

## 包职责

### `src/stock_analytics/features`

`MarketDailyBuilder` 从行情、两融、估值和资金流等黄金表构建全市场日频宽表；`FeatureStore` 负责 mart 的读取、持久化和元数据指纹。特征集市只负责事实加速，不决定六维评分权重。

`FeatureStore` 还负责 `convertible_bond_daily`、`insider_activity_daily`、`repurchase_daily`、`block_trade_daily` 和 `settlement_iv_proxy_daily` 的领域 Mart 读写。领域 Mart 缺少输入时保持稳定 Schema 或返回不可用事实，不生成伪造数值。

### `src/stock_analytics/metrics`

`MetricEngine.compute()` 是通用指标统一入口；`MetricRegistry` 管理指标定义；`calculators/*.py` 实现估值、资金、流动性、表现、趋势、广度和波动等计算。该层不感知六维权重、报告模板或市场温度文案。

### `src/stock_analytics/pipelines/market_temperature`

- `pipeline.py` 编排一次标准运行；
- `facts.py` / `facts_mart.py` 采集交易窗口、水位、MetricEngine 和 mart 事实；
- `short_term.py` 计算短线附加事实；`optional_facts.py` 只汇总领域 Mart 观察事实，避免重复采集短线事实；
- `domain_mart_facts.py` 将领域 Mart 转成可追溯观察事实；这些事实可以进入报告，但不进入六维主评分；
- `derived.py` / `derived_options.py` 计算温度计专用派生事实；
- `metric_temperature.py` 负责原始 MetricEngine 事实的 0-100 温度转换；
- `scoring.py` 按 YAML 规则生成六维温度、综合温度和系统性风险摘要；
- `artifacts.py` 写入 `data/analytics/market_temperature/`。

### `src/stock_analytics/pipelines/industry_structure`

行业管线生成申万一级行业面板，按 `config/analytics/industry_structure.yaml` 计算动量、估值、基本面和拥挤度子分，再生成结构排序和行业报告。它不向市场温度计提供综合温度分量。

### `src/stock_reporting`

`src/stock_reporting/interpretation/` 负责配置和解释对象，`src/stock_reporting/templates/` 负责 Jinja2 报告模板和展现适配器，`src/stock_reporting/engine/` 负责渲染环境与格式化过滤器。报告层只组织 facts、scores 和质量结果，不重新读取数据计算指标。

## 配置、事实和评分分离

`config/analytics/market_temperature.yaml` 的字段含义：

- 顶层 `main_window` / `short_windows`：分析窗口；
- `dimensions[].weight`：六维综合权重；
- `dimensions[].metrics[].weight`：维度内指标权重；
- `direction`：正向或反向温度；
- `source`：`metric_engine` 或 `derived`；
- `datasets`：数据水位、频率、滞后和质量等级约束。

`facts.parquet` 保存原始指标值或派生温度、日期/窗口、水位、样本量和状态。MetricEngine 事实通常是 `unit=raw`，`derived.py` 输出的派生指标通常已经是 `unit=temperature`。`scoring.py` 只消费 facts 和配置。

质量报告由 `build_quality_report()` 基于 manifest、facts 和 YAML 数据集配置生成；它不重算指标。`required` 与 `max_lag_days` 参与质量判定，`cadence` 与 `quality_tier` 只用于披露。

## 依赖方向

允许：

- `market_temperature` 调用 `metrics`、`FeatureStore` 和 `DataCatalog`；
- `industry_structure` 调用 `DataCatalog` 和行业数据处理模块；
- `reporting` 读取分析产物并渲染 Markdown。

不允许：

- `metrics` 依赖任一具体分析管线；
- `market_temperature` 依赖行业结构分合成六维温度；
- `reporting` 绕过 facts 重新读取本地数据计算指标；
- 用模型记忆补齐本地缺失数据。

## 新增指标放置规则

1. 可跨场景复用的指标放入 `src/stock_analytics/metrics/calculators/`，注册 `MetricSpec` 和 calculator。
2. 只服务六维温度计的指标放入 `src/stock_analytics/pipelines/market_temperature/derived.py`。
3. 只服务行业结构排序的指标放入 `src/stock_analytics/pipelines/industry_structure/`。
4. 只调整归属、权重、方向或启停时修改对应 YAML。
5. 只调整报告表达时修改 `src/stock_reporting/templates/` 下的模板或适配器。
6. 流程和口径变化更新本 skill 的 `SKILL.md` 或 `references/*.md`。

## 评分维护原则

- 当前六维评分以 `config/analytics/market_temperature.yaml`、`metric_temperature.py` 和 `scoring.py` 为唯一依据；
- 权重为 0 的指标可以采集和展示，但不得进入维度分；
- 缺失事实标为 `insufficient` 或 `unavailable`，不得静默填补；
- 缺失指标在维度内重归一，缺失维度在综合分中重归一；
- 基本面、宏观月频或季频数据只能作为最新状态底座，不写成最近 20 个交易日内发生的变化。
