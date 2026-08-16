# 六维市场温度计打分口径

## 产物架构

已落地的标准入口：

```bash
make market-temperature DATE=YYYY-MM-DD
```

配置、事实、评分结构和输出模板已拆分：

| 层 | 文件 | 职责 |
|---|---|---|
| 配置 | `config/analytics/market_temperature.yaml` | 六维权重、指标清单、数据集水位、日期列和滞后容忍 |
| 配置加载 | `src/stock/analytics/market_temperature/config.py` | 读取 YAML 并转为强类型配置 |
| 事实采集 | `src/stock/analytics/market_temperature/facts.py` | 解析 20/5/10 日窗口、采集数据水位和 `MetricEngine` 指标事实 |
| 评分结构 | `src/stock/analytics/market_temperature/scoring.py` | 按事实、方向和权重生成维度温度与综合温度 |
| 输出模板 | `src/stock/analytics/market_temperature/templates.py` | 生成 `report.md`、`human_report.md` 与 `report.json` |
| 产物写入 | `src/stock/analytics/market_temperature/artifacts.py` | 写 `runs/` 和刷新 `latest/` |
| CLI | `src/stock/cli/market_temperature.py` | 命令行入口 |

产物目录：

```text
data/analytics/market_temperature/
├── runs/as_of=YYYY-MM-DD/run_YYYYMMDDTHHMMSS/
│   ├── manifest.json
│   ├── facts.parquet
│   ├── scores.json
│   ├── report.md
│   ├── human_report.md
│   ├── report.json
│   ├── quality_report.md
│   └── quality_report.json
└── latest/
    ├── manifest.json
    ├── facts.parquet
    ├── scores.json
    ├── report.md
    ├── human_report.md
    ├── report.json
    ├── quality_report.md
    └── quality_report.json
```

`facts.parquet` 是事实层唯一来源；`scores.json`、技术明细报告和人工阅读报告可以基于事实与配置反复重算。当前综合温度已接入 0-100 温度化公式，所有入分指标必须先落为事实，再按配置权重合成；权重为 0 的指标只用于事实披露和解释，不参与维度分。

`scores.json` 同时输出 `systemic_risk`。该字段是基于六维温度的风险共振摘要，不是独立行情指标：

- 估值高温、综合高温、情绪高温、宏观流动性偏紧属于风险源；
- 技术偏热但资金未确认属于修复质量风险；
- 情绪未过热、宏观流动性中性偏松、基本面不弱属于缓冲因素；
- 系统性风险只回答“整体回撤和风险扩散压力高不高”，不替代行业结构排序。

## 时间窗口

- 主窗口：最近 20 个已落盘 A 股交易日，来自 `DataCatalog(data_source="tushare").latest_trade_dates("stock_daily_bar", n=20)`。
- 历史分位窗口：默认 5 年交易日或可用全历史；若 5 年窗口样本不足，必须说明。
- 主日期：`tushare.stock_daily_bar` 最新交易日；其他数据源按各自最新日期对齐并披露。

## 口径与质量约束

每次运行会生成 `quality_report.md/json`。质量报告只读取 `manifest + facts + config`，不重新计算指标。

硬约束：

- 报告基准日、manifest 和事实表 `as_of_date` 必须一致；
- 20 日主窗口必须覆盖配置要求的已落盘交易日数量；
- 必需数据集必须可用，并满足 `max_lag_days`；
- 非水位事实里的 `metric_date/latest_date/report_date/ann_window` 等实际指标日期不得晚于基准日。

软约束：

- 可选数据集若配置 `max_lag_days`，超限时标为质量警告；
- 静态表用样本数判断可用性，不要求交易日期；
- 月频、季频和事件型数据按配置披露频率与滞后，不解释成 20 日边际变化。

数据配置字段：

| 字段 | 作用 |
|---|---|
| `required` | 是否为硬依赖，缺失或滞后会形成硬错误 |
| `max_lag_days` | 相对基准日允许的最大滞后天数 |
| `static` | 静态字典或合约表，无交易日期列 |
| `date_column` | 非 `trade_date` 日期列，如 `ann_date`、`report_date`、`month` |
| `cadence` | 数据频率说明，如 `trading_daily`、`monthly`、`quarterly`、`event`、`static` |
| `quality_tier` | 质量层级说明，如 `core`、`confirming`、`slow`、`background` |

## 默认权重

| 维度 | 权重 | 说明 |
|---|---:|---|
| 估值面 | 20% | 估值越高、股权风险补偿越低，温度越高 |
| 资金面 | 20% | 杠杆和主动资金越积极，温度越高 |
| 情绪面 | 15% | 换手活跃和上涨扩散越强，温度越高 |
| 技术面 | 15% | 趋势、动量和均线宽度越强，温度越高 |
| 基本面 | 15% | 盈利底座越强，风险偏好支撑越强 |
| 宏观流动性 | 15% | 利率越低、信用和外部风险环境越友好，温度越高 |

调整权重必须在分析中说明理由；默认不要因为某个维度数据更易取得而提高其实际权重。

`config/analytics/market_temperature.yaml` 中单个指标支持 `source`：

| source | 含义 |
|---|---|
| `metric_engine` | 默认值，由 `MetricEngine.compute()` 计算 |
| `derived` | 由 `src/stock/analytics/market_temperature/derived.py` 直接读取 DataCatalog 计算 |

维度内按可用且可温度化的指标权重重归一。`weight: 0` 表示只采集事实、不入分。

如用户要求“纯 20 日短线热度”，可额外列一个敏感性版本，把基本面降到 10% 并把差额分给日频维度；默认综合温度仍使用上表，避免无回测依据的权重漂移。

## 短期补充窗口（可选）

短期补充窗口用于捕捉 5 日/10 日动量、情绪脉冲和超买超卖。它是主温度之后的“短线温度”附加输出，不替代 20 日主窗口，也默认不并入六维综合温度权重。

| 窗口 | 角色 | 用法 |
|---|---|---|
| 5 日 | 短线探测器 | 捕捉最近一周资金异动、赚钱效应脉冲和极端超买超卖 |
| 10 日 | 短线趋势确认 | 平滑 5 日噪音，确认短线动量是否延续 |
| 20 日 | 主窗口 | 维持六维市场温度计的波段判断和主综合温度 |

当前 `MetricEngine` 已注册的短窗指标只有 `return_5d`。以下指标若要使用，需要用 `DataCatalog` 从本地日度数据临时计算，并在输出中说明“非内置 metric”：`return_10d`, `rsi_6d`, `rsi_10d`, `ma_bias_5d`, `ma_bias_10d`, `above_ma5_share`, `above_ma10_share`, `margin_balance_growth_5d`, `realized_volatility_5d`, `max_drawdown_5d`。

推荐短线温度子项：

| 子项 | 指标 | 数据来源 | 处理 |
|---|---|---|---|
| 技术动量 | `return_5d`、临时计算 `return_10d` | `MetricEngine` / `stock_daily_bar` | 全市场中位数和上涨占比 |
| 短期超买 | 临时计算 `rsi_6d/10d`, `ma_bias_5d/10d` | `stock_daily_bar` | 中位数或历史分位 |
| 短线宽度 | 临时计算 `above_ma5_share/above_ma10_share` | `stock_daily_bar` | 站上短均线个股占比 |
| 情绪脉冲 | 5 日均 `market_turnover_rate`、5 日均 `advance_share` | 已有 metrics 日序列 | 同源指标只取 1-2 个，不重复加权 |
| 资金异动 | 5 日累计主力净流入占比、临时计算两融余额 5 日变化 | `moneyflow`, `margin`, `stock_daily_bar` | 资金流数据滞后时必须披露 |
| 短期风险 | 临时计算 5 日波动率、5 日最大回撤 | `stock_daily_bar` | 只作风险提示，不解释为趋势本身 |

短线温度解读：

| 短线温度 | 描述 |
|---:|---|
| `> 80` | 短期超买或情绪脉冲过强，追涨风险升高 |
| `60-80` | 短线动量强，需看 20 日温度是否确认 |
| `40-60` | 短线中性，主判断回到 20 日温度 |
| `20-40` | 短线偏冷或回踩，观察 20 日趋势是否破坏 |
| `< 20` | 短期超卖，可能有技术性反弹，但不单独构成趋势反转 |

短线温度与 20 日温度背离时，优先以 20 日主窗口判断趋势，以短线温度判断节奏：

| 5/10 日短线温度 | 20 日主温度 | 解读 |
|---|---|---|
| 高 | 中低 | 短线修复开始，波段尚未确认 |
| 高 | 高 | 短线和波段共振偏热，警惕拥挤和回撤 |
| 低 | 高 | 短线降温，但波段趋势可能仍健康 |
| 低 | 低 | 短线和波段均偏冷，可能处于调整中继 |

短线窗口噪音高，默认使用 3-5 日均值、累计值或中位数平滑；不要因单日短线温度变化改写主综合结论。

## metrics 源码导航

分析前先查 `src/stock/analytics/metrics` 的当前实现。此文件只提供导航和默认分析口径；若与源码不一致，以源码为准。

| 目的 | 源码位置 | 关注点 |
|---|---|---|
| 统一调度 | `src/stock/analytics/metrics/engine.py` | `MetricEngine.compute` 如何调度注册指标 |
| 上下文与日期 | `src/stock/analytics/metrics/context.py` | `MetricContext.start_date/end_date/target_date/cache` |
| 指标注册 | `src/stock/analytics/metrics/registry.py` | `MetricRegistry.specs/select/get` |
| 内置入口 | `src/stock/analytics/metrics/calculators/__init__.py` | `BUILTIN_METRIC_SPECS`, `BUILTIN_CALCULATORS` |
| 表现 | `src/stock/analytics/metrics/calculators/performance.py` | `return_1d/5d/20d/60d/252d` |
| 估值 | `src/stock/analytics/metrics/calculators/valuation.py` | `valuation_temperature`, PE/PB 分位, ERP, 股债收益比 |
| 资金 | `src/stock/analytics/metrics/calculators/flow.py` | 两融、主力资金、北向、成交额分位 |
| 情绪/流动性 | `src/stock/analytics/metrics/calculators/liquidity.py` | 换手率、成交额均量比、Z-score |
| 技术趋势 | `src/stock/analytics/metrics/calculators/trend.py` | MA 乖离、RSI、距252日高点 |
| 市场宽度 | `src/stock/analytics/metrics/calculators/breadth.py` | 上涨占比、均线上方占比、新高新低 |
| 波动风险 | `src/stock/analytics/metrics/calculators/volatility.py` | 已实现波动率、下行波动率、最大回撤 |
| 宏观扩展 | `src/stock/analytics/metrics/calculators/macro.py` | 当前是否已有宏观指标实现 |

推荐首轮定位命令：

```text
codegraph_explore: src/stock/analytics/metrics MetricEngine MetricContext BUILTIN_METRIC_SPECS BUILTIN_CALCULATORS calculators valuation flow liquidity trend breadth volatility performance macro
```

## 本地数据边界

先按本地数据边界决定指标能否入分。没有稳定 Curated 表的指标只作为缺口说明，不进入综合温度。

| 指标 | 本地状态 | 处理 |
|---|---|---|
| 业绩预告改善/超预期 | 已有 `tushare.forecast`，字段含 `ann_date`, `end_date`, `type`, `p_change_min/max`, `net_profit_min/max` | 纳入基本面扩展 |
| 分析师盈利预测上修比例 | 已有 `tushare.report_rc`，字段含 `report_date`, `quarter`, `org_name`, `np`, `eps`, `tp` | 纳入基本面扩展 |
| 创新高/新低家数 | 已有 `new_high_share_252d`, `new_low_share_252d` | 纳入技术/市场宽度 |
| 涨停/跌停/炸板事件 | 已有 `tushare.limit_list_d`，覆盖 2020-01-01 至 2026-08-14；`limit=U/D/Z` 分别代表涨停/跌停/炸板 | 纳入情绪面扩展 |
| 新增开户数 | 已有 `lixinger.investor_accounts`，字段含 `nni_m`, `n_non_ni_m`, `ni`, `non_ni` | 作为月频慢情绪低权重入分 |
| 期权合约与日行情 | 已有 `tushare.opt_basic` 静态合约表和 `tushare.opt_daily` 日行情 | 可计算 PCR、成交额、持仓量和近月成交占比观察温度；默认 `weight: 0`，不进入主温度；当前未定义隐含波动率 |
| 中国信用利差 AA-AAA | 无稳定本地信用利差表 | 不入分 |
| 中国 CPI / 实际利率 | 已有 `tushare.cn_cpi.nt_yoy`，可与 10 年国债组合 | 可作为宏观流动性辅助 |

注意：`stk_limit` 只能提供涨跌停价格，不等于涨停/跌停事件明细。涨跌停事件温度使用 `limit_list_d`；该接口不提供 ST 股票统计，输出时不要把它表述为全 A 含 ST 的涨跌停全量。

## 指标去重与归属

综合温度只对同一原始信号加权一次。若一个指标能解释多个维度，选择最主要的维度纳入分数，其他维度只可在文字里作辅助解释。

| 信号 | 计分归属 | 处理规则 |
|---|---|---|
| 成交额分位、成交额 Z-score、均量比 | 资金面 | `market_amount_percentile_1250d` 表示场内资金活跃度，只作资金面低权重子项；`amount_ma_ratio_20d` 和 `amount_zscore_60d` 只作幅度辅助 |
| 换手率、换手率分位、换手率 Z-score | 情绪面 | 优先用 `turnover_rate_percentile_1250d`；缺失时用 `market_turnover_rate` 的历史分位或 `turnover_rate_zscore_60d` |
| `above_ma20_share`、`above_ma60_share` | 技术面 | 不放入情绪面，避免把趋势宽度重复加权 |
| `market_turnover_rate`、`turnover_rate_percentile_1250d`、`turnover_rate_zscore_60d` | 情绪面子项 | 高相关时合成一个“换手烈度”子分，不分别等权进入维度分 |
| 融资、两融、主力资金、北向资金 | 资金面 | 不与成交额活跃度混在同一子项；北向字段语义未核实时只称资金金额或活跃度 |
| `forecast`、`report_rc` | 基本面 | 与申万行业财报共同构成基本面，不写成日频行情热度 |

默认维度内子权重：

| 维度 | 子项 | 默认子权重 | 方向 |
|---|---|---:|---|
| 估值面 | `valuation_temperature` 主指数结果行 | 70% | 越高越热 |
| 估值面 | PE/PB/ERP/股债收益比辅助分 | 30% | PE/PB 越高越热，ERP/股债收益比越低越热 |
| 资金面 | 融资买入、两融渗透率、两融余额 20 日变化 | 45% | 越高越热 |
| 资金面 | 主力/北向资金净流入占比 | 35% | 越高越进攻 |
| 资金面 | `market_amount_percentile_1250d` 成交活跃度 | 20% | 越高越热 |
| 情绪面 | 换手率分位或换手 Z-score | 40% | 越高越热 |
| 情绪面 | `advance_share` 上涨家数占比 | 25% | 越高越热 |
| 情绪面 | `limit_event_temperature` 涨跌停事件温度 | 25% | 涨停越多、跌停越少、封板越稳越热 |
| 情绪面 | `investor_account_temperature` 月度新增投资者温度 | 10% | 新增投资者越多越热；月频慢变量 |
| 技术面 | 20 日收益、RSI、MA 乖离 | 45% | 越高越热 |
| 技术面 | `above_ma20_share`, `above_ma60_share` | 40% | 越高越强 |
| 技术面 | 距 252 日高点、新高/新低占比 | 15% | 越接近高点、新高越多越热 |
| 基本面 | 申万 2021 行业财报收入/利润/ROE | 45% | 越高越强 |
| 基本面 | `forecast` 业绩预告改善 | 20% | 越高越强 |
| 基本面 | `express` 业绩快报利润增速/ROE | 15% | 越高越强 |
| 基本面 | `report_rc` 盈利预测上修比例 | 20% | 越高越强 |
| 宏观流动性 | 国内利率与资金价格：10 年国债、Shibor、实际利率 | 40% | 越低越宽松 |
| 宏观流动性 | 国内货币信用：M1/M2、社融 | 20% | 越强越宽松 |
| 宏观流动性 | 外部环境：美股、VIX、美元、美债、铜 | 40% | 美股/铜越强越友好；VIX/美元/美债越低越友好 |

若某个子项缺失或样本不足，只在该维度内对可用子项重归一，并在输出中披露有效子项。不要用其他维度的指标填补空缺。

## 分数方向

所有维度都映射到 `0-100`，高分表示市场更热、更拥挤或更偏进攻。

- 正向历史分位：`温度 = 历史分位`。若分位为 `0-1`，先乘以 100。
- 反向历史分位：`温度 = 100 - 历史分位`。
- 正向 Z-score：`温度 = norm_cdf(z) * 100`。
- 反向 Z-score：`温度 = (1 - norm_cdf(z)) * 100`。
- 原生 0-100 指标直接使用；原生 0-1 占比乘以 100。所有结果最终裁剪到 `[0, 100]`。
- 同一子项内可同时查看 5 年分位和短窗 Z-score：分位更稳健，Z-score 保留幅度信息。合成分数时默认只取一个主口径，另一个用于解释，不重复加权。
- 1250 日滚动分位遇到历史窗口内少量空值时，当前值非空且窗口内有效样本不少于 80% 即可计算；当前值为空仍输出空值，避免数据缺口被前值冒充。

方向清单：

- 估值：PE/PB 分位越高越热；ERP、股息率、股债收益比越低越热。
- 资金：融资占比、两融渗透率、两融余额增速、主力/北向净流入占比越高越热。
- 情绪：换手率、上涨家数占比越高越热。
- 技术：20日收益、RSI、均线乖离、站上中短期均线比例越高越热。
- 基本面：盈利增速、ROE、正增长行业占比越高越支撑风险偏好。
- 宏观流动性：利率越低越宽松；M1/M2、社融越强越宽松；美元指数/VIX 越低越利好风险偏好。

## 推荐计算

### 估值面

主指标：

- `valuation_temperature` 由 `MetricEngine` 计算全量指数结果后，在结果表中优先筛选 `000985` 中证全指。
- 当前源码签名不支持给 `valuation_temperature` 单独传 `index_symbol` 参数；不要假设 `MetricEngine.compute()` 会按指数参数过滤。
- 若结果里没有 `000985`，回退展示 `000300`, `000905`, `000852` 的可得估值温度或 PE/PB 分位，并说明回退口径。
- 辅助展示 `000300`, `000905`, `000852` 的 `pe_percentile_5y`, `pb_percentile_5y`, `equity_bond_yield_ratio`, `equity_risk_premium`。

解释：

- `valuation_temperature >= 80`：估值偏热或接近拥挤。
- `60-80`：偏热但仍可能由低利率支撑。
- `< 40`：估值偏冷。

### 资金面

主指标：

- `margin_buy_share_zscore_60d`：`norm_cdf(z) * 100`。
- `margin_penetration_percentile_1250d`：五年历史分位。
- `margin_balance_growth_20d`：`50 + 20日增长率 * 500` 后裁剪到 `[0,100]`。
- `main_money_net_inflow_share`：`50 + 主力净流入成交占比 * 1000` 后裁剪到 `[0,100]`。
- `northbound_net_inflow_share` 或 `northbound_net_inflow_zscore_60d`，仅在字段语义已核实时纳入；否则只辅助展示。
- `market_amount_percentile_1250d`，作为资金活跃度低权重子项。

`margin_buy_share` 和 `margin_penetration` 原始值保留为事实展示，默认 `weight: 0`，不直接入分。

可用 `moneyflow_hsgt.north_money` 做北向活跃度参考，但不要在未验证字段语义时称为“净流入”。

资金面只对成交活跃度计分一次。`amount_ma_ratio_20d` 和 `amount_zscore_60d` 可解释短期放量幅度，但不要与 `market_amount_percentile_1250d` 同时等权进入资金面。

### 情绪面

主指标：

- `turnover_rate_percentile_1250d`；缺失时用 `market_turnover_rate` 历史分位或 `turnover_rate_zscore_60d` 转换。
- `advance_share * 100`。
- `limit_event_temperature`：来自 `limit_list_d` 的涨跌停/炸板事件温度。
- `investor_account_temperature`：来自 `lixinger.investor_accounts` 的 `nni_m + n_non_ni_m` 月度新增投资者数历史分位，低权重纳入。

涨跌停事件温度计算：

- `limit_up_count_temperature`：当日 `limit=U` 家数历史分位。
- `limit_down_count_temperature`：当日 `limit=D` 家数历史反向分位，跌停越少温度越高。
- `limit_up_down_strength_temperature`：`U / (U + D)` 历史分位，反映涨跌停强弱。
- `limit_seal_success_temperature`：`U / (U + Z)` 历史分位，`Z` 为炸板，反映封板成功率。
- `limit_event_temperature`：上述可用子项等权平均；单项缺失时披露并对可用子项重归一。

当前配置中 `market_turnover_rate` 原始值只作事实展示，默认 `weight: 0`。情绪面不计入 `market_amount_percentile_1250d`，避免与资金面的成交活跃度重复。`above_ma20_share` 不进入情绪面。`investor_account_temperature` 是月频慢变量，只代表最新可得开户热度水位，不代表最近 20 个交易日内开户变化。

`opt_basic` 和 `opt_daily` 当前只做期权数据水位披露；没有稳定隐含波动率、认沽认购比或期权成交拥挤度公式前，不进入情绪面温度。

注意：`daily_basic.turnover_rate` 简单平均和项目情绪模块的成交额/流通市值聚合口径可能不同。对用户输出优先使用项目现有口径，并说明差异。

### 技术面

主指标：

- 个股 `return_20d` 中位数和上涨占比。
- 个股 `rsi_14d` 中位数。
- 个股 `ma_bias_20d` 中位数。
- `above_ma20_share`, `above_ma60_share`。
- `distance_to_252d_high` 中位数。
- 主要指数 20 日收益：上证指数、沪深300、中证500、中证1000、创业板指。

判断：

- 站上20日线高、站上60日线低：短线修复强，中期趋势未全面确认。
- RSI 中位数 60-70：强势但未极端。
- RSI 中位数超过 70 且成交额分位高：追涨风险升高。

### 基本面

主指标来自三类本地数据：

1. 理杏仁申万行业合并财报：

- `sw_2021_fs_non_financial`
- `sw_2021_fs_bank`
- `sw_2021_fs_security`
- `sw_2021_fs_insurance`

抽取字段：

- 收入 TTM 增速：`q.ps.toi.ttm_y2y`
- 利润 TTM 增速：`q.ps.np.ttm_y2y`
- ROE TTM：`q.m.roe.ttm`

2. Tushare 业绩预告 `forecast`：

- 用 `ann_date` 对齐主窗口，只取 `ann_date <= 主日期` 且最近 20 个交易日公告的记录。
- 先按 `symbol, end_date` 保留最新一条 PIT 记录。
- 计算 `p_change_mid = mean(p_change_min, p_change_max)`；若缺失，用 `type` 中的预增、略增、续盈、扭亏等正向标签做替代。
- 默认输出“正向预告占比”和 `p_change_mid` 中位数。只有在能与 `report_rc` 同期一致预期匹配时，才称为“超预期”；否则称“业绩预告改善”。

3. Tushare 业绩快报 `express`：

- 用 `ann_date` 对齐主窗口，只取 `ann_date <= 主日期` 且最近 20 个交易日公告的记录。
- 先按 `symbol, end_date` 保留最新一条 PIT 记录。
- 计算 `n_income / yoy_net_profit - 1` 和 `diluted_roe` 的行业或全市场中位数；本地 `yoy_net_profit` 是上年同期净利润金额，不是同比百分比。若上年同期净利润小于等于 0，不把该样本纳入利润增速分。
- 业绩快报比正式财报更快，但覆盖样本通常不全；有效样本不足时只展示原始值，不硬算子项。

4. Tushare 分析师盈利预测 `report_rc`：

- 用 `report_date` 对齐最近 20 个交易日。
- 以 `symbol, org_name, quarter` 为粒度，比较窗口内最新 `np` 与窗口前最近一次同机构同报告期 `np`。
- `revision_ratio = 上修数 / (上修数 + 下修数)`；若无法逐机构比较，退化为最近 20 日一致预期中位数相对前 60 日中位数的上修股票占比。
- 可用 `index_member` 关联申万行业，但综合温度默认先取全市场或有预测覆盖样本的等权结果。

行业口径：

- 使用申万 2021 一级行业口径；非金融、银行、证券、保险四类表合并后计算。
- 默认不剔除银行、证券、保险；若因字段不可比而剔除，必须写明。
- 正增长行业占比的分母为“最新报告期目标字段非空的行业数”，不是全部行业数。

展示最新报告期、有效行业数、中位数、正增长行业占比、业绩预告公告数、快报公告数、研报覆盖数和上修/下修样本数。季频财报只能作为基本面底座；`forecast`、`express` 和 `report_rc` 可反映 20 日内的预告/快报/预期边际变化。若有效样本不足，不硬算对应子项，只展示原始值和缺口。

### 宏观流动性

主指标：

- `lixinger.national_debt.tcm_y10`：中国10年国债，低利率对应高流动性温度。
- `tushare.shibor.on`：短端资金价格，低利率对应高流动性温度。
- `tushare.cn_cpi.nt_yoy`：中国 CPI 同比，可与 10 年国债计算实际利率辅助项。
- `lixinger.cn_m.m2_yoy`、`m1_yoy - m2_yoy`。
- `lixinger.sf_month.stk_endval` 同比。
- `yfinance.index_daily_bar`: `^GSPC`, `^IXIC` 作为美股指数收益代理。
- `yfinance.macro_indicators`: `^VIX`, `DX-Y.NYB`, `^TNX` 作为外部环境核心代理；`HG=F` 铜价若本地有稳定数据则纳入，缺失时不硬算；`GC=F` 黄金和 `CL=F` 原油用于外部压力观察。
- `alphavantage.macro_indicators`: `CNH=X` / USD-CNH 外汇日线，只作人民币汇率压力观察项。

当前 `src/stock/analytics/metrics/calculators/macro.py` 没有内置宏观计算器。宏观流动性需要直接查询本地宏观数据表后做历史分位温度化。

月频 M1/M2、社融、CPI 只使用最新可得值的历史分位，不反映 20 日边际变化；若样本不足或字段缺失，不硬算该子项。利率、实际利率、美元指数、VIX 属反向指标，低位对应更高流动性或风险偏好温度。

当前已实现的宏观派生温度：

| 指标 | 规则 |
|---|---|
| `macro_bond_yield_10y_temperature` | `lixinger.national_debt.tcm_y10` 历史反向分位 |
| `macro_shibor_on_temperature` | `tushare.shibor.on` 历史反向分位 |
| `macro_real_rate_temperature` | 月末 10 年国债收益率 - `tushare.cn_cpi.nt_yoy / 100`，历史反向分位 |
| `macro_m2_yoy_temperature` | `lixinger.cn_m.m2_yoy` 历史分位 |
| `macro_m1_m2_gap_temperature` | `m1_yoy - m2_yoy` 历史分位 |
| `macro_social_finance_stock_temperature` | `lixinger.sf_month.stk_endval` 同比历史分位 |
| `macro_sp500_20d_return_temperature` | `^GSPC` 20 日收益历史分位 |
| `macro_nasdaq_20d_return_temperature` | `^IXIC` 20 日收益历史分位 |
| `macro_vix_temperature` | `^VIX` 历史反向分位 |
| `macro_usd_index_20d_change_temperature` | `DX-Y.NYB` 20 日变化历史反向分位 |
| `macro_us_10y_temperature` | `^TNX` 历史反向分位 |
| `macro_copper_20d_return_temperature` | `HG=F` 铜价 20 日收益历史分位；本地缺失时标记 `insufficient` |
| `macro_external_environment_temperature` | 上述外部环境可用核心子项等权平均；缺失子项披露并对可用子项重归一 |
| `macro_gold_20d_return_pressure` | `GC=F` 黄金 20 日收益历史分位，权重为 0，仅作避险压力观察 |
| `macro_oil_20d_return_pressure` | `CL=F` 原油 20 日收益历史分位，权重为 0，仅作通胀压力观察 |
| `macro_safe_haven_pressure_temperature` | 黄金上涨、VIX 升温、美股下跌压力可用子项等权平均；权重为 0 |
| `macro_inflation_pressure_temperature` | 原油上涨、美债收益率上行、美国 CPI 压力可用子项等权平均；权重为 0 |
| `macro_demand_pressure_temperature` | 铜、原油、美股走弱压力可用子项等权平均；权重为 0 |
| `macro_external_pressure_temperature` | 避险、通胀、需求三类压力可用子项最大值；权重为 0，仅作风险提示 |
| `macro_usd_index_temperature` | `DX-Y.NYB` 水平历史反向分位，权重为 0，仅作辅助观察 |
| `macro_cnh_20d_change_temperature` | Alpha Vantage `CNH=X` 离岸人民币 USD/CNH 20 日变化历史反向分位，权重为 0，仅作人民币贬值压力观察 |
| `macro_fred_t10y2y_temperature` | FRED `T10Y2Y` 期限利差历史分位，权重为 0，仅作美国期限结构背景观察 |
| `macro_fred_fedfunds_temperature` | FRED `FEDFUNDS` 政策利率历史反向分位，权重为 0，仅作美国政策利率背景观察 |
| `macro_fred_walcl_temperature` | FRED `WALCL` 美联储资产负债表规模历史分位，权重为 0，仅作美国流动性背景观察 |
| `macro_fred_cpi_yoy_temperature` | FRED `CPIAUCSL` 同比历史反向分位，权重为 0，仅作美国通胀压力背景观察 |
| `macro_fred_unrate_temperature` | FRED `UNRATE` 失业率历史反向分位，权重为 0，仅作美国就业压力背景观察 |
| `macro_fred_payems_yoy_temperature` | FRED `PAYEMS` 非农就业人数同比历史分位，权重为 0，仅作美国就业周期背景观察 |
| `macro_fred_gdp_yoy_temperature` | FRED `GDP` 同比历史分位，权重为 0，仅作美国季度经济底座背景观察 |

默认配置中，宏观流动性维度内部权重为国内流动性 60%、外部环境 40%。外部环境只通过 `macro_external_environment_temperature` 入分；单项外盘指标权重为 0，用于事实披露和解释，避免重复加权。

外部压力项不进入 `macro_external_environment_temperature`，也不进入六维综合温度；其方向与主温度相反，分数越高代表外盘对 A 股的额外压力越大。FRED 美国宏观背景项不进入 `macro_external_environment_temperature`，也不进入六维综合温度。它们用于解释外部利率、期限结构、资产负债表、通胀、就业和 GDP 周期状态；月频/季频项只代表最新可得状态，不代表最近 20 个 A 股交易日内发生了边际变化。

周频或周度重采样可以作为敏感性分析，但不是默认口径。默认仍使用最近 20 个已落盘 A 股交易日。

## 全市场样本与过滤披露

情绪、技术、宽度和表现类个股指标默认遵循 metrics 源码当前过滤：

- `stock_daily_bar` 指标保留 `close > 0` 且关键字段非空的记录。
- 滚动指标因窗口不足自然产生空值；当前源码没有显式剔除 ST、退市整理、北交所或上市不足 60/252 日的新股。
- 个股中位数和占比默认是全市场等权；成交额、市值、资金流为项目源码中的汇总口径。

若分析时额外增加 ST、新股、北交所或停牌过滤，必须在输出中说明。若不增加额外过滤，也要披露“样本为当前 `stock_daily_bar` 有效记录，未额外剔除 ST/北交所/新股”。

## 申万行业结构评分口径

行业结构分析是独立中观排序模块，不并入六维市场温度。完整执行说明见 `references/industry-structure.md`。

默认权重：

| 子分 | 权重 | 方向 | 说明 |
|---|---:|---|---|
| 动量趋势 | 40% | 越强越高 | 20日收益、相对收益、60日收益、均线乖离的横截面分位 |
| 估值性价比 | 25% | 越便宜越高 | PE/PB 五年反向分位、PB-ROE 残差反向分位 |
| 基本面合成 | 15% | 越强越高 | 正式财报底座 + 预告/快报/研报快速确认 |
| 拥挤度约束 | 20% | 越不拥挤越高 | `100 - TCR历史分位` |

TCR 定义为最近 20 个行业交易日的行业成交额占全部申万一级行业成交额比例均值，单位为百分点；`crowding_temperature = tcr_percentile`，越高越拥挤，`crowding_score = 100 - crowding_temperature`。

行业基本面合成口径：

| 字段 | 来源 | 规则 |
|---|---|---|
| `official_fundamental_score` | `lixinger.sw_2021_fs_*` | 收入 TTM 增速、利润 TTM 增速、ROE TTM 的行业自身历史分位均值 |
| `fast_fundamental_score` | `tushare.forecast`, `express`, `report_rc` | 预告正向占比、预告增速中位数、快报利润增速/ROE、研报上修比例的行业横截面分位均值；快报利润增速由当期净利润与上年同期净利润计算 |
| `fundamental_score` | 合成 | 正式财报和快速确认按配置加权；缺失一侧时按有效权重重归一 |
| `fundamental_status` | 合成 | 机器字段；Markdown 报告必须翻译为“财报已滞后但有快速确认”“仅有滞后财报”等中文说明 |

默认 `stale_after_days=90`。正式财报未滞后时正式/快速权重为 `70%/30%`；正式财报滞后时降级为 `40%/60%`。正式分数仍保留，但解释中要写清它是中期底座，不代表最近 20 日边际变化。

标签规则：

- `强势主线`：`momentum_score >= 75` 且 `return_20d > 0`。
- `低估改善`：`valuation_score >= 70` 且 `fundamental_score >= 55`。
- `拥挤风险`：`crowding_temperature >= 80`。
- `超跌修复`：`return_20d < 0` 且 `return_5d > 0`。
- `景气承压`：`fundamental_score < 40`。
- `相对占优`：`relative_return_20d > 0`。

标签不是互斥分组。若结构领先行业多数 60 日收益仍为负，应提示“短期修复强于中期趋势，中期趋势未全面确认”。

结构健康度单独输出为 `structure_health`，不等同于结构分排名：

- 20 日上涨行业占比衡量短线扩散；
- 60 日上涨行业占比衡量中期确认；
- 结构分 Top 行业中 60 日仍为负的数量衡量领先方向是否只是短线反弹；
- 拥挤行业占比衡量结构风险；
- 强势主线数量衡量主线清晰度。

若 20 日扩散强但 60 日扩散弱，且 Top 行业多数 60 日仍为负，应表述为“修复中但偏脆弱”，不能简单写成结构健康。

## 输出模板

标准产物中：

- `report.md` 保留数据水位和全部指标事实，适合排查口径；
- `human_report.md` 保留结论、六维解读、精选关键事实和数据限制，适合直接阅读；
- `report.json` 保留机器可读结构。

```markdown
口径：基于本地 Curated 黄金表，最近 20 个已落盘交易日为 `YYYY-MM-DD` 至 `YYYY-MM-DD`。资金流/宏观数据若有滞后，在此说明。

综合温度：`xx.x / 100`，一句话判断。

系统性风险：`低到中等 / 中等 / 中等偏高 / 高`。说明主要风险源、观察信号和缓冲因素。

解读顺序：

| 层级 | 维度 | 温度 | 跟踪速度 | 读法 |
|---|---|---:|---|---|
| 短线信号 | 技术面、情绪面 | xx.x | 最快 | 日频指标，优先判断20日趋势、热度和赚钱效应 |
| 约束信号 | 估值面 | xx.x | 快 | 日频估值主要由价格驱动，用于判断安全边际 |
| 确认信号 | 资金面 | xx.x | 较快 | 两融和资金流常晚一日，用于确认行情质量 |
| 环境底座 | 宏观流动性 | xx.x | 分化 | 利率/外盘较快，货币信用月频，主要看风险环境 |
| 盈利底座 | 基本面 | xx.x | 偏慢 | 财报季频，预告/研报较快；区分底座和预期变化 |

| 维度 | 温度 | 主要事实 | 判断 |
|---|---:|---|---|
| 估值面 | xx.x | ... | ... |
| 资金面 | xx.x | ... | ... |
| 情绪面 | xx.x | ... | ... |
| 技术面 | xx.x | ... | ... |
| 基本面 | xx.x | ... | ... |
| 宏观流动性 | xx.x | ... | ... |

短线温度（可选）：5 日 `xx.x / 100`，10 日 `xx.x / 100`。说明与 20 日主温度是共振还是背离。

结构判断：...

风险提示：...

数据限制：...
```

## 执行前检查清单

- [ ] 是否先用 codegraph 确认 metrics 源码签名与本文一致？
- [ ] 是否避免成交活跃度、均线宽度等重复指标被重复加权？
- [ ] 反向指标是否统一用 `100 - 分位` 或负向 Z-score 转换？
- [ ] 低频指标是否标注“只代表最新状态，不代表 20 日变化”？
- [ ] `forecast` 是否区分“业绩预告改善”和可验证的“超预期”？
- [ ] `report_rc` 上修比例是否披露上修/下修有效样本数？
- [ ] 若输出 5/10 日短线温度，是否明确“不并入主综合温度”？
- [ ] 短窗指标是否区分已注册 metrics 与 DataCatalog 临时计算指标？
- [ ] 综合权重是否与默认权重一致；若调整，是否说明理由？
- [ ] 是否披露各数据源最新日期和有效样本范围？
- [ ] 是否提示 `moneyflow` 滞后、`north_money` 语义、季频基本面限制？
- [ ] 缺失或样本不足的子项是否只展示原始值，而不是硬算进综合温度？

## 最小 Python 骨架

```python
from stock.analytics.engine import MarketScanEngine
from stock.analytics.metrics import MetricContext, MetricEngine
from stock.data.catalog import DataCatalog

cat_ts = DataCatalog(data_source="tushare")
latest = cat_ts.get_latest_trade_date("stock_daily_bar")
dates20 = list(reversed(cat_ts.latest_trade_dates("stock_daily_bar", n=20)))
start20 = dates20[0]

engine = MetricEngine()
ctx = MetricContext(catalog=cat_ts, start_date=start20, end_date=latest)
results = engine.compute(
    [
        "valuation_temperature",
        "margin_buy_share",
        "margin_penetration",
        "margin_balance_growth_20d",
        "main_money_net_inflow_share",
        "market_amount_percentile_1250d",
        "advance_share",
        "above_ma20_share",
        "above_ma60_share",
        "new_high_share_252d",
        "new_low_share_252d",
        "market_turnover_rate",
        "turnover_rate_percentile_1250d",
        "return_5d",
        "return_20d",
        "rsi_14d",
        "ma_bias_20d",
        "distance_to_252d_high",
        "realized_volatility_20d",
    ],
    ctx,
)

forecast = cat_ts.load_dataset("forecast")
report_rc = cat_ts.load_dataset("report_rc")
index_member = cat_ts.load_dataset("index_member")

# 10 日收益、5/10 日 RSI、短均线宽度、5 日波动率等短线温度指标
# 当前不是内置 metric，需要从 stock_daily_bar / margin / moneyflow 临时计算。
short_bars = cat_ts.load_dataset("stock_daily_bar", start_date=dates20[0], end_date=latest)

scan = MarketScanEngine().compute(target_date=latest, index_symbol="000300")
```
