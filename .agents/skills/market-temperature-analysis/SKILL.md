---
name: market-temperature-analysis
description: 用本地 Curated 黄金表和现有 analytics/metrics 体系生成 A 股六维市场温度计分析。Use when the user asks for 市场温度、市场体检、六维市场温度计、最近20日综合分析、资金估值情绪技术基本面宏观流动性联动分析，或希望重复执行同一套 A 股市场状态判断框架。
---

# Market Temperature Analysis

## 核心原则

只使用本地 Curated 黄金表和项目内已有分析器输出。不要用模型记忆补点位、政策、新闻或宏观结论；本地没有稳定数据表支撑的维度必须标为不可量化或仅作外部背景。

默认分析周期为最近 20 个已落盘 A 股交易日，而不是最近 20 个自然日。先用 `DataCatalog.latest_trade_dates("stock_daily_bar", n=20)` 取得窗口，再以最新行情交易日作为主口径日期。

需要具体字段、打分方向、metrics 源码位置和输出模板时，读取 `references/scoring.md`。

## 标准流程

1. 读取 `data-catalog` 技能，确认 `DataCatalog` 用法和数据口径。
2. 先用 `codegraph_explore` 查看 `src/stock/analytics/metrics` 的当前实现，确认 `MetricEngine`、`BUILTIN_METRIC_SPECS`、`BUILTIN_CALCULATORS` 和各 `calculators/*.py` 里的实际计算口径。
3. 查询关键数据集最新水位：
   - `tushare`: `stock_daily_bar`, `daily_basic`, `margin`, `moneyflow`, `moneyflow_hsgt`, `index_daily`, `sw_daily`
   - `lixinger`: `index_fundamental`, `national_debt`, `sw_2021_fundamental`, 四类 `sw_2021_fs_*`
   - `yfinance`: `macro_indicators`
   - `fred`: `macro_indicators`，仅在需要美国宏观背景时使用
4. 若核心行情或估值缺失，先说明数据缺口，不要硬算综合温度。
5. 用 `MetricEngine` 优先计算已有指标：
   - 估值：`valuation_temperature`, `pe_percentile_5y`, `pb_percentile_5y`, `equity_risk_premium`, `equity_bond_yield_ratio`
   - 资金：`margin_buy_share`, `margin_penetration`, `margin_balance_growth_20d`, `main_money_net_inflow_share`
   - 情绪/流动性：`market_turnover_rate`, `amount_ma_ratio_20d`, `amount_zscore_60d`, `turnover_rate_zscore_60d`
   - 技术/宽度：`return_20d`, `rsi_14d`, `ma_bias_20d`, `above_ma20_share`, `above_ma60_share`, `new_high_share_252d`, `new_low_share_252d`
   - 风险：`realized_volatility_20d`, `downside_volatility_20d`, `max_drawdown_60d`
6. 用 `MarketScanEngine.compute(target_date=latest, index_symbol="000300")` 获取宏观象限、低估行业、拥挤行业、市场健康度，作为交叉校验。
7. 对指标做 0-100 温度归一。分数越高表示越热、越拥挤、越偏进攻；利率类方向相反，低利率对应更高流动性温度。
8. 输出时先给综合温度和一句话判断，再列六维表格，最后写结构机会、风险和数据水位限制。

## 六维定义

默认权重：

| 维度 | 权重 | 主指标 |
|---|---:|---|
| 估值面 | 20% | 中证全指 `valuation_temperature`，辅以沪深300、中证500、中证1000 |
| 资金面 | 20% | 融资买入占比、两融渗透率、两融余额20日变化、主力资金净流入占比、北向资金活跃度 |
| 情绪面 | 15% | 成交额分位、换手率、站上20日线比例、上涨家数占比 |
| 技术面 | 15% | 20日收益、RSI、均线乖离、站上60日线比例、距252日高点距离 |
| 基本面 | 15% | 行业财报收入/利润 TTM 增速、ROE、正增长行业占比、PB-ROE 低估行业 |
| 宏观流动性 | 15% | 中国10年国债、Shibor、M1/M2、社融、美元指数/VIX 外部环境 |

## 输出要求

区分三层信息：

- 已验证事实：本地数据直接计算得到的日期、数值、分位、变化。
- 机制推断：由指标组合推出的市场状态，如“短线偏热但中期趋势未全面确认”。
- 数据限制：数据滞后、字段口径不明、缺少政策/新闻/隐含波动率等。

常用结论分档：

| 综合温度 | 描述 |
|---:|---|
| `< 20` | 低温机会区 |
| `20-40` | 偏冷修复观察区 |
| `40-60` | 中性轮动区 |
| `60-80` | 偏热修复区 |
| `> 80` | 高温拥挤区 |

## 口径提醒

`moneyflow` 常晚于行情一个交易日，资金结论要写清最新资金日期。`moneyflow_hsgt.north_money` 在当前库里按资金金额使用，除非已验证字段语义，否则不要表述为严格“北向净买入”。

基本面数据多为季频，最近 20 日分析中只能作为基本面底座，不要写成 20 日内发生的财报变化。

项目没有新闻舆情、政策文本、隐含波动率或新增开户的稳定本地表。除非用户明确要求联网并给出来源，否则不要把这些维度纳入综合温度。

若 `references/scoring.md` 的指标说明与 `src/stock/analytics/metrics` 源码不一致，以源码实现为准，并在完成分析后更新本 skill。
