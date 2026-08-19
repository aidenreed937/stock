# 六维市场温度计唯一评分口径

## 1. 评分来源与优先级

六维市场温度计只允许使用以下三层规则，不能另行维护一套手工评分表：

1. `config/analytics/market_temperature.yaml`：决定六个维度、维度权重、指标权重、方向、指标来源和数据质量约束；
2. `src/stock_analytics/pipelines/market_temperature/metric_temperature.py`：决定 MetricEngine 原始事实如何映射为 0-100 温度；
3. `src/stock_analytics/pipelines/market_temperature/scoring.py`：决定指标缺失、维度缺失、基本面陈旧和综合分的重归一规则。

本文件只解释上述实现，不覆盖配置或源码。若本文件与 YAML 或源码不一致，以 YAML 和源码为准，并应优先修正文档。

申万行业结构使用独立的 `config/analytics/industry_structure.yaml` 和 `src/stock_analytics/pipelines/industry_structure/scoring.py`，其结构分不进入六维综合温度。行业结构的完整口径见 `references/industry-structure.md`。

## 2. 产物链路与真实路径

标准入口：

```bash
make market-temperature DATE=YYYY-MM-DD
```

| 环节 | 当前路径 | 职责 |
|---|---|---|
| 配置 | `config/analytics/market_temperature.yaml` | 六维权重、指标清单和数据集约束 |
| 配置加载 | `src/stock_reporting/interpretation/market_temperature/config.py` | YAML -> 强类型配置 |
| 事实采集 | `src/stock_analytics/pipelines/market_temperature/facts.py` | 交易窗口、水位、MetricEngine 和派生事实 |
| mart 事实 | `src/stock_analytics/pipelines/market_temperature/facts_mart.py` | 从 `market_daily.parquet` 提取已物化事实 |
| 派生事实 | `src/stock_analytics/pipelines/market_temperature/derived.py` | 基本面、情绪、宏观派生温度 |
| 温度转换 | `src/stock_analytics/pipelines/market_temperature/metric_temperature.py` | raw 事实 -> 0-100 温度 |
| 六维评分 | `src/stock_analytics/pipelines/market_temperature/scoring.py` | 指标加权、维度加权和系统性风险摘要 |
| 运行编排 | `src/stock_analytics/pipelines/market_temperature/pipeline.py` | 采集、评分、质量、报告和写盘 |
| 质量 JSON | `src/stock_analytics/data_quality.py` | 基于 manifest、facts 和 YAML 质量约束检查 |
| 质量 Markdown | `src/stock_reporting/core/quality.py` | 渲染质量报告 |
| 报告渲染 | `src/stock_reporting/templates/market_temperature.py` | Jinja2 报告适配器 |
| CLI | `src/stock_cli/market_temperature.py` | 命令行入口 |

产物写入 `data/analytics/market_temperature/`，每次运行包含 `manifest.json`、`facts.parquet`、`scores.json`、`report.md`、`report.json`、`human_report.md` 和质量报告，并刷新 `latest/` 副本。

`facts.parquet` 是事实层唯一来源。报告模板不重新计算指标；`scores.json` 只根据 facts 和配置生成。

## 3. 窗口和质量

- 主窗口是最近 20 个已落盘 A 股交易日，来自 `stock_daily_bar`；
- YAML 的 `short_windows` 是 `[5, 10]`，`facts.py` 通过 `short_term.py` 从 `market_daily` 计算短线附加事实；样本充足时输出温度，样本不足时标记 `insufficient`，不进入六维主温度。`optional_facts.py` 只负责领域 Mart 观察项，不能重复追加短线事实；每个窗口在 `facts.parquet` 应只有一行；
- 行业/个股估值使用五年滚动窗口，大盘宽基估值与 ERP 使用十年滚动窗口；其他派生宏观分位以其实际历史样本为准；
- 所有数据按基准日过滤，不能使用未来事实；
- 必需数据缺失或超过 `max_lag_days` 时，质量报告产生硬问题；可选数据缺失或滞后时产生警告；
- 低频数据只能解释最新状态，不能写成最近 20 个交易日内发生的变化。

## 4. 六维权重和当前有效指标

维度权重来自 YAML，合计 100%：

| 维度 | 权重 | 当前有效入分指标 |
|---|---:|---|
| 估值面 | 20% | `valuation_temperature`（唯一入分合成指标；PE/PB/ERP 分位只作辅助事实） |
| 资金面 | 20% | `margin_buy_share_zscore_60d`、`margin_penetration_percentile_1250d`、`margin_balance_growth_20d`、`main_money_net_inflow_share`；`market_amount_percentile_1250d` 权重为 0，仅作历史兼容观察 |
| 情绪面 | 15% | `turnover_rate_percentile_1250d`、`advance_share`、`limit_event_temperature`、`investor_account_temperature` |
| 技术面 | 15% | `return_20d`、`rsi_14d`、`ma_bias_20d`、`above_ma20_share`、`above_ma60_share`、`new_high_share_252d`、`new_low_share_252d` |
| 基本面 | 15% | `fs_revenue_growth_temperature`、`fs_profit_growth_temperature`、`fs_roe_temperature`、`forecast_positive_temperature`、`report_revision_temperature` |
| 宏观流动性 | 15% | `macro_bond_yield_10y_temperature`、`macro_shibor_on_temperature`、`macro_real_rate_temperature`、`macro_m2_yoy_temperature`、`macro_m1_m2_gap_temperature`、`macro_social_finance_stock_temperature`、`macro_external_environment_temperature` |

### 4.1 估值面

YAML 子权重：

| 指标 | 子权重 | 方向 | 当前处理 |
|---|---:|---|---|
| `valuation_temperature` | 100% | 正向 | 已是 0-100 温度，作为唯一估值合成指标直接使用 |
| `pe_percentile_10y` | 0% | 正向 | 大盘宽基 PE 十年分位，仅作辅助事实 |
| `pb_percentile_10y` | 0% | 正向 | 大盘宽基 PB 十年分位，仅作辅助事实 |
| `equity_risk_premium_percentile_10y` | 0% | 反向 | ERP 十年历史分位，仅作辅助事实；ERP 越高通常越便宜 |
| `dividend_yield_percentile_10y` | 未单独入分 | 反向 | 股息率十年分位；已进入 `valuation_temperature` 内部组合，不再作为独立 YAML 子项重复计权 |

`valuation_temperature` 的 MetricEngine 结果是每个指数一行；YAML 的 `aggregation: mean` 会对最新日期的所有可用指数结果求均值。当前实现不会自动筛选 `000985`。需要使用中证全指时，必须在报告中核对结果行的 `symbol`；不能把“均值结果”直接称为 `000985`。

`valuation_temperature` 的实际公式为：`(PE10Y + PB10Y + (100 - ERP10Y) + (100 - DY10Y)) / 4`。其中 `equity_risk_premium` raw 值为 `1 / PE - tcm_y10`，收益率在 Curated 中按小数保存；展示为百分比时再乘以 100。大盘宽基估值与 ERP 使用项目实现的 2,500 个交易日十年窗口，行业/个股估值继续使用 1,250 个交易日五年窗口。同一基准日切换窗口会改变历史样本参照，不能直接解释为底层数据变化。

### 4.2 资金面

| 指标 | 子权重 | 温度规则 |
|---|---:|---|
| `margin_buy_share_zscore_60d` | 25% | 标准正态 CDF 映射 |
| `margin_penetration_percentile_1250d` | 20% | 分位直接作为温度 |
| `margin_balance_growth_20d` | 20% | `50 + value * 500` |
| `main_money_net_inflow_share` | 20% | `50 + value * 1000` |
| `market_amount_percentile_1250d` | 0% | 历史兼容字段；全市场自由流通换手率不再作为资金面第二个换手率分位入分 |

`margin_buy_share` 和 `margin_penetration` 在 YAML 中权重为 0，只作事实展示。`moneyflow` 常晚于行情，资金结论必须写明资金事实日期；北向字段未经语义核验时只能称资金金额或活跃度观察。

### 4.3 情绪面

| 指标 | 子权重 | 温度规则 |
|---|---:|---|
| `turnover_rate_percentile_1250d` | 40% | 分位直接作为温度 |
| `advance_share` | 25% | 占比乘 100 |
| `limit_event_temperature` | 25% | `derived.py` 对可用涨跌停事件子项等权；已经是温度 |
| `investor_account_temperature` | 10% | 月度新增投资者数历史分位；已经是温度 |

`market_turnover_rate`、`market_amount_percentile_1250d` 及期权、涨跌停组件的其他明细指标在当前 YAML 中权重为 0；情绪面只保留 `turnover_rate_percentile_1250d` 这一套换手率分位入分。`market_amount_percentile_1250d` 虽保留历史字段名，实际计算的是全市场自由流通换手率的五年分位，不再直接对绝对成交额排序。它们可以展示或解释，但不改变主分。`limit_list_d` 中 `U`、`D`、`Z` 分别代表涨停、跌停和炸板；`stk_limit` 只是涨跌停价格，不是事件明细。

期权结算价 BS-IV 代理已以 `metric_value` 事实接入情绪面：`settlement_iv_proxy_temperature`（全市场 `settlement_iv_proxy_median` 历史反向分位）与 `settlement_iv_proxy_skew_temperature`（认沽-认购 IV 偏度历史反向分位）由 `derived.py` 的 `_settlement_iv_rows()` 生成，默认 `weight: 0`，不参与情绪面分；方向 `inverse` 语义为 IV/Skew 偏高代表恐慌避险需求，温度降低。该指标是结算价反解 Black-Scholes 波动率代理，非标准 VIX，升级权重后仍必须持续披露该口径限制。

### 4.4 技术面

| 指标 | 子权重 | 温度规则 |
|---|---:|---|
| `return_20d` | 20% | `50 + value * 500` |
| `rsi_14d` | 20% | RSI 原值直接作为温度 |
| `ma_bias_20d` | 15% | `50 + value * 500` |
| `above_ma20_share` | 20% | 占比乘 100 |
| `above_ma60_share` | 15% | 占比乘 100 |
| `new_high_share_252d` | 5% | 占比乘 100 |
| `new_low_share_252d` | 5% | 占比乘 100，再按 inverse 取反 |

当前指标默认使用源码的有效行情记录和滚动窗口。除非另行明确，不能暗示源码自动剔除了 ST、北交所、新股或停牌样本。

### 4.5 基本面

YAML 当前没有 `express` 指标，六维基本面只有以下五项：

| 指标 | 子权重 | 当前派生口径 |
|---|---:|---|
| `fs_revenue_growth_temperature` | 20% | 申万行业财报最新报告期收入 TTM 增长为正的比例，已乘 100 |
| `fs_profit_growth_temperature` | 25% | 申万行业财报最新报告期利润 TTM 增长为正的比例，已乘 100 |
| `fs_roe_temperature` | 10% | ROE TTM 的历史中位温度 |
| `forecast_positive_temperature` | 20% | 最近 20 个交易日业绩预告正向样本占比，已乘 100 |
| `report_revision_temperature` | 25% | 全部可比样本的净修正率映射温度：`50 + (上修数 - 下修数) / 总可比样本数 * 50`；总可比样本数小于 5 时为 `insufficient` |

正式财报由 `sw_2021_fs_non_financial`、`sw_2021_fs_bank`、`sw_2021_fs_security` 和 `sw_2021_fs_insurance` 提供，通常是季频底座。`forecast` 只能称业绩预告改善或承压，`report_rc` 是卖方预测修正，不等同真实财报改善。当前六维基本面没有行业结构模块中的正式/快速 70%/30% 混合规则；不得把行业结构内部规则移植到六维评分。

`report_revision_temperature` 的可比样本由同一 `symbol + org_name + quarter` 在最近 20 个交易日内的最新预测，与窗口开始前最近一次预测配对得到。预测不变项仍计入分母：原始净修正率为 `(up - down) / total_comparable * 100`，再映射到 `[0, 100]` 温度；因此全上修为 100、全下修为 0、全不变为 50。

### 4.6 宏观流动性

YAML 子权重：

| 指标 | 子权重 | 当前派生口径 |
|---|---:|---|
| `macro_bond_yield_10y_temperature` | 18% | 中国 10 年国债历史反向分位 |
| `macro_shibor_on_temperature` | 12% | Shibor ON 历史反向分位 |
| `macro_real_rate_temperature` | 10% | 10 年国债收益率减 CPI 后的实际利率历史反向分位 |
| `macro_m2_yoy_temperature` | 8% | M2 同比历史分位 |
| `macro_m1_m2_gap_temperature` | 6% | M1 同比减 M2 同比的历史分位 |
| `macro_social_finance_stock_temperature` | 6% | 社融存量同比历史分位 |
| `macro_external_environment_temperature` | 40% | 外部环境核心子项的可用均值 |

宏观外部环境的核心子项包括美股 20 日收益、VIX、美元指数 20 日变化、美债 10 年收益率和铜价 20 日收益。单项外盘指标、外部压力指标、CNH 和 FRED 背景指标在 YAML 中均为 0 权重，只作事实披露和解释；它们不重复进入外部环境或六维综合温度。

## 5. 温度转换源码规则

`fact_temperature(row, direction)` 的实际分支如下：

| 条件 | 原始值到温度 |
|---|---|
| `unit == "temperature"`，或指标为 `valuation_temperature`，或指标名含 `percentile` | 直接使用数值 |
| 指标名含 `zscore` | `normal_cdf(value) * 100` |
| `rsi_14d` | 直接使用 RSI 数值 |
| `advance_share`、`above_ma20_share`、`above_ma60_share`、新高/新低占比 | `value * 100` |
| `return_20d`、`ma_bias_20d`、`margin_balance_growth_20d` | `50 + value * 500` |
| `main_money_net_inflow_share` | `50 + value * 1000` |
| 其他未覆盖 raw 指标 | 返回 `None`，不入分 |

随后按 YAML 的 `direction` 处理：正向保持原值，`inverse` 使用 `100 - value`。所有结果通过 `clip_temperature()` 裁剪并四舍五入到 `[0, 100]`。因此“配置了权重”不等于“当前一定有有效分”：原始值若没有源码转换分支，仍会因 `None` 被排除。

派生指标由 `derived.py` 以 `unit=temperature` 写入 facts，因此不再经过 raw 公式；仍会经过方向处理和 `[0, 100]` 裁剪。

## 6. 聚合、缺失和陈旧数据

### 6.1 指标事实聚合

`facts.py` 先计算每个 MetricEngine 指标在基准日前的最新日期，再按 YAML 的 `aggregation` 聚合：

- `mean`：最新日期所有结果行的均值；
- `median`：最新日期结果行的中位数；
- 其他值（包括 `latest`）：取最新结果行的最后一个值。

因此估值 `mean` 是最新日期的指数横截面均值，不自动等价于某个指定指数。

### 6.2 维度分

`scoring.py` 只使用 `enabled` 且 `weight > 0` 的 YAML 指标。事实状态不是 `ok`、温度转换结果为 `None` 或样本不足时，该指标不进入分母；其余可用指标按原配置权重重新归一。`weight: 0` 指标无论事实是否存在，都不参与维度分。

基本面维度配置 `stale_after_days: 90`、`stale_weight_scale: 0.40`。当事实 note 标记的 `stale_days` 超过 90 天时，该指标权重乘以 0.40，再与其他可用指标重新归一。这个规则不是把基本面替换成另一套 70%/30% 组合。

### 6.3 综合分

六维综合温度是可用维度温度按 YAML 维度权重的加权均值。温度为 `None` 的维度不进入分母，剩余维度按可用维度权重重归一；全部维度不可用时综合温度为 `None`，状态为 `pending`。系统性风险摘要只读取六维温度及其共振关系，不是额外评分维度。

## 7. 短线温度和行业结构

YAML 配置 `[5, 10]` 日短窗，标准管线从 `market_daily` 计算两项短线温度。样本足够时 `scores.json` 输出 `status: ready` 和温度；样本不足或输入缺失时输出 `status: insufficient`，不得填充默认值。短线事实只作附加节奏观察，不写入六维主综合温度。

行业结构必须单独运行：

```bash
make industry-structure DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.industry_structure --date YYYY-MM-DD
```

行业结构的默认总分为动量 40%、估值 25%、基本面 15%、拥挤度约束 20%；其基本面内部才使用新鲜财报 70%/快速确认 30%，财报陈旧时调整为 40%/60%。这套规则只属于行业结构，不得写进六维市场温度评分。

## 8. 输出和披露要求

报告至少区分三层信息：

- 已验证事实：facts 中的日期、原始值、温度、样本量和水位；
- 机制推断：由多个维度温度组合得出的状态判断；
- 数据限制：缺失、滞后、低频、字段语义不明或当前转换器未覆盖的指标。

必须披露：

- 主窗口起止日期和基准日；
- 进入评分的有效指标与被排除指标；
- ERP raw 值与十年分位辅助事实的展示分工；
- 估值 `valuation_temperature` 的实际结果行聚合口径；
- 资金流、季频财报、月频宏观和慢情绪指标的最新日期；
- 缺失指标是否触发了维度内重归一、缺失维度是否触发了综合分重归一。

## 9. 执行检查清单

- [ ] 是否读取 `config/analytics/market_temperature.yaml`，而不是引用旧手工权重？
- [ ] 是否使用 `src/stock_analytics/pipelines/market_temperature/metric_temperature.py` 的实际转换分支？
- [ ] 是否只让 `weight > 0` 且事实状态为 `ok` 的指标入分？
- [ ] 是否对缺失指标和缺失维度分别重归一？
- [ ] 是否区分 raw ERP 展示值与十年分位辅助事实？
- [ ] 是否核对 `valuation_temperature` 的实际指数结果行，而不是默认称为 `000985`？
- [ ] 是否将 `express` 和行业结构 70%/30% 规则限制在行业结构模块？
- [ ] 是否明确 5/10 日短线温度是附加输出，并区分 `ready` 与 `insufficient`？
- [ ] 是否披露各数据源水位、滞后和有效样本？

## 10. 最小调用骨架

```python
from stock_analytics.metrics import MetricContext, MetricEngine
from stock_data.catalog import DataCatalog

catalog = DataCatalog(data_source="tushare")
latest = catalog.get_latest_trade_date("stock_daily_bar")
dates20 = list(reversed(catalog.latest_trade_dates("stock_daily_bar", n=20)))

engine = MetricEngine()
context = MetricContext(
    catalog=catalog,
    start_date=dates20[0],
    end_date=latest,
    target_date=latest,
)
results = engine.compute(
    [
        "valuation_temperature",
        "pe_percentile_10y",
        "pb_percentile_10y",
        "margin_buy_share_zscore_60d",
        "margin_penetration_percentile_1250d",
        "margin_balance_growth_20d",
        "main_money_net_inflow_share",
        "market_amount_percentile_1250d",
        "turnover_rate_percentile_1250d",
        "advance_share",
        "return_20d",
        "rsi_14d",
        "ma_bias_20d",
        "above_ma20_share",
        "above_ma60_share",
        "new_high_share_252d",
        "new_low_share_252d",
    ],
    context=context,
)
```

标准六维产物应通过 `make market-temperature` 生成，以便同时获得派生事实、质量报告和报告渲染结果。
