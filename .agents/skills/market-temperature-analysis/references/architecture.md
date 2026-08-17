# 市场温度计架构边界

## 目的

本文件说明 `src/stock/analytics/metrics`、`src/stock/analytics/market_temperature` 与 `src/stock/analytics/industry_structure` 的关系，避免后续扩展时把“通用指标计算”“六维温度计应用”和“行业结构分析”混在一起。

## 总体关系

`features / mart` 是特征宽表集市层，负责将全市场日频行情与明细指标预聚合为 `market_daily.parquet`，提供亚秒级查询加速。

`metrics` 是通用指标计算层，负责把本地黄金表计算成可复用指标。

`market_temperature` 是六维市场温度计应用管线，负责把通用指标、特征集市事实和温度计专用派生事实组织成一次分析产物。

`industry_structure` 是申万行业结构应用管线，负责把行业动量、估值、基本面和拥挤度组织成行业排序与轮动分析产物。它和 `market_temperature` 是同级应用，不是六维温度计的 derived 指标。

`reporting` 是统一展现层与模板渲染引擎，负责通过 Jinja2 模板将计算事实与评分结构格式化为整洁规范的 Markdown / 终端报告，不参与任何指标计算。

```text
DataCatalog 本地黄金表
  ├─> features.builders.market_daily -> data/curated/mart/market_daily.parquet (日频预聚合宽表)
  ├─> metrics / MetricEngine -> 通用指标：估值、资金、技术、广度、流动性等
  └─> market_temperature.derived / facts_mart -> 温度计专用派生事实

metrics 输出 + mart 宽表 + derived 输出
  └─> market_temperature.facts
        └─ facts.parquet

facts + config/analytics/market_temperature.yaml
  └─> market_temperature.scores
        └─ scores.json

scores + facts + config
  └─> stock.reporting.engine (Jinja2 模板渲染)
        └─ report.md / human_report.md / report.json

DataCatalog + analytics/industry
  └─> industry_structure.panel / scores
        └─ industry_panel.parquet / scores.json -> stock.reporting -> report.md
```

## 包职责

### `src/stock/analytics/features`
用于构建和管理 Analytics Mart 日频聚合特征宽表。
- `MarketDailyBuilder` 负责从底层 stock_daily_bar, margin, daily_basic, moneyflow 等全量宽表做向量化预聚合；
- `FeatureStore` 负责 `data/curated/mart/` 宽表、元数据指纹与长表特征持久化与读取。

### `src/stock/analytics/metrics`

用于沉淀通用、可复用、与单一报告无关的指标计算能力。

- `MetricEngine.compute()` 是统一调度入口；
- `MetricRegistry` 管理指标定义；
- `calculators/*.py` 实现具体算法；
- 输出 `MetricResult.frame`，由调用方决定如何聚合、展示或打分。

适合放入 `metrics` 的指标：

- 可被市场扫描、策略、报告、回测或其他分析复用；
- 输入数据和输出含义稳定；
- 不依赖六维温度计的权重、归属、文案或报告结构。

### `src/stock/analytics/pipelines/market_temperature`

用于生成 A 股六维市场温度计产物。

- `pipeline.py` 编排一次运行；
- `facts.py` / `facts_mart.py` 采集窗口、水位、`MetricEngine` 指标、`FeatureStore` 集市宽表和派生指标；
- `derived.py` 计算温度计专用派生事实；
- `scores.py` 根据事实、方向和权重生成六维温度与系统性风险评级；
- `quality.py` 生成口径与质量报告；
- `artifacts.py` 写入 `data/analytics/market_temperature/`。

### `src/stock/analytics/pipelines/industry_structure`

用于生成申万行业结构分析产物。

- `panel.py` 构建每个行业一行的 `industry_panel.parquet`；
- `scores.py` 生成动量、估值、基本面、拥挤度四类子分和行业结构分；
- `facts.py` 采集窗口、水位和面板摘要；
- `pipeline.py` 编排一次运行；
- `artifacts.py` 写入 `data/analytics/industry_structure/`。

行业结构分只用于行业排序和轮动判断，不并入六维市场温度。

### `src/stock/reporting`

用于报告模板渲染与格式化展现层。

- `engine/renderer.py`：`ReportRenderer` 单例环境，配置 Jinja2 模板加载器与 Markdown 空白符修剪策略；
- `engine/filters.py`：注册 `pct`、`decimal`、`yi`、`wan`、`md_table` 等金融数据格式化过滤器；
- `templates/`：沉淀 `.md.j2` 模板与通用宏（`macros/watermark.j2`, `macros/alerts.j2`）；
- `templates/*.py`：展现层适配器，接收上游领域对象并调用模板引擎输出 Markdown 文本。

## 配置与事实分离

`config/analytics/market_temperature.yaml` 只表达分析口径，不实现计算：

- 维度权重；
- 指标归属；
- 指标方向；
- 指标内部权重；
- 指标来源：`metric_engine`、`mart` 或 `derived`；
- 需要检查水位的数据集。

`facts.parquet` 是事实层，保存已计算出的原始指标值、温度值、水位、样本量和状态。`scores.json`、`report.md`、`human_report.md` 都应从 facts 和配置派生。

不要在输出模板里重新计算指标；模板只负责组织表达。

`quality_report.md/json` 是口径与质量层，基于 manifest、facts 和 YAML 数据集配置生成，不重算指标。它负责披露：

- 基准日、交易日窗口和主锚点数据集；
- 硬约束：主窗口样本、必需数据可用性、必需数据滞后、非水位事实未来日期；
- 软约束：可选数据滞后、可选数据不可用、静态表样本；
- 每个数据集的频率、质量层级、最新水位和滞后天数。

数据集配置中的 `cadence` 与 `quality_tier` 只描述数据频率和质量层级，不改变指标计算；`required` 与 `max_lag_days` 才参与水位质量判定。

## 新增指标放置规则

优先按以下顺序判断：

1. 若指标可跨场景复用，放入 `src/stock/analytics/metrics/calculators/`，并注册 `MetricSpec` 与 calculator。
2. 若指标只服务六维温度计，放入 `src/stock/analytics/pipelines/market_temperature/derived.py`。
3. 若指标只服务行业结构排序，放入 `src/stock/analytics/pipelines/industry_structure/`。
4. 若只调整维度归属、权重、方向或启停，修改对应的 `config/analytics/*.yaml`。
5. 若只调整报告表达与排版，修改 `src/stock/reporting/templates/` 下对应的 `.md.j2` 模板或适配器。
6. 若是分析流程、口径或执行注意事项，更新 skill 的 `SKILL.md` 或 `references/*.md`。

## 依赖方向

允许：

- `market_temperature` 调用 `metrics` 和 `FeatureStore`；
- `market_temperature` 直接读取 `DataCatalog` 生成专用派生事实；
- `industry_structure` 复用 `analytics/industry` 和 `DataCatalog` 生成行业面板；
- `metrics` 读取 `DataCatalog` 计算通用指标；
- `reporting` 读取分析产物字典并用 Jinja2 渲染 Markdown。

不允许：

- `metrics` 依赖 `market_temperature` 或 `industry_structure`；
- `metrics` 感知六维权重、报告模板或温度计文案；
- `market_temperature` 依赖行业结构分来合成六维综合温度；
- `reporting` / 模板引擎反向调用底层数据计算指标；
- `reporting` 绕过 facts 直接读取本地数据重算指标；
- 用模型记忆补齐本地缺失数据。

## 扩展示例

新增一个通用技术指标，例如 `return_10d`：

1. 在 `metrics/calculators/performance.py` 或对应 calculator 中实现；
2. 注册 `MetricSpec` 和 calculator；
3. 增加 `metrics` 单元测试；
4. 在 YAML 中把该指标配置到技术面或短线温度展示。

新增一个温度计专用指标，例如“涨跌停事件温度”：

1. 在 `market_temperature/derived.py` 从 `limit_list_d` 计算事实；
2. 把子指标和合成指标写入 facts；
3. 在 YAML 中配置指标归属、方向和权重；
4. 增加 `market_temperature` 单元测试；
5. 在报告模板中披露样本、日期和缺失状态。

## 维护原则

- 计算规则以源码为准，文档不一致时先修文档；
- 原始事实、评分配置和报告表达保持分离；
- 缺数据标为 `insufficient` 或 `unavailable`，不要静默填补；
- 权重为 0 的指标可采集和展示，但不参与维度分；
- 基本面、宏观月频或季频数据只能作为状态底座，不要写成最近 20 个交易日内发生的变化。
