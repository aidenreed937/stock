---
name: market-temperature-analysis
description: 用本地 Curated 黄金表和现有 analytics/metrics 体系生成 A 股六维市场温度计分析，并可附加 5/10 日短线温度和申万行业结构分析。Use when the user asks for 市场温度、市场体检、六维市场温度计、最近20日综合分析、短线温度、5日/10日节奏、申万行业结构、行业轮动、行业强弱排名、资金估值情绪技术基本面宏观流动性联动分析，或希望重复执行同一套 A 股市场状态判断框架。
---

# Market Temperature Analysis

## 核心原则

只使用本地 Curated 黄金表和项目内已有分析器输出。不要用模型记忆补点位、政策、新闻或宏观结论；本地没有稳定数据表支撑的维度必须标为不可量化或仅作外部背景。

默认分析周期为最近 20 个已落盘 A 股交易日，而不是最近 20 个自然日。先用 `DataCatalog.latest_trade_dates("stock_daily_bar", n=20)` 取得窗口，再以最新行情交易日作为主口径日期。5 日/10 日窗口只作为短线温度补充观察，不替代 20 日主温度。

需要理解 `metrics` 与 `market_temperature` 的职责边界、数据流和扩展落点时，读取 `references/architecture.md`。需要分析申万2021行业轮动、行业强弱、景气-估值矩阵时，读取 `references/industry-structure.md`。需要具体字段、打分方向、metrics 源码位置和输出模板时，读取 `references/scoring.md`。

## 已落地产物链路

优先使用仓库内市场温度计产物管线，而不是每次手工拼装 facts：

```bash
make market-temperature DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock.cli.market_temperature --date YYYY-MM-DD
```

默认配置在 `config/analytics/market_temperature.yaml`。产物写入 `data/analytics/market_temperature/`：

- `runs/as_of=YYYY-MM-DD/run_YYYYMMDDTHHMMSS/manifest.json`：运行元数据、窗口交易日和文件清单；
- `facts.parquet`：窗口、水位和 `MetricEngine` 指标事实；
- `scores.json`：六维温度、综合温度、状态和合成说明；
- `report.md` / `report.json`：面向阅读和机器消费的报告；
- `human_report.md`：面向人工阅读的结论版报告；
- `latest/`：最近一次成功运行的同名文件副本。

当前代码已实现“配置 / 事实 / 评分结构 / 输出模板 / 产物写入”分离。`scores.json` 已接入六维温度合成和系统性风险摘要：MetricEngine 指标和 DataCatalog 派生指标先在 `facts.parquet` 落为事实，再按 `config/analytics/market_temperature.yaml` 中的方向与权重温度化。权重为 0 的指标只作事实展示，不参与维度分。系统性风险只基于六维温度之间的共振和背离，不使用新闻、政策或模型记忆。

申万行业结构分析使用独立产物管线：

```bash
make industry-structure DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock.cli.industry_structure --date YYYY-MM-DD
```

默认配置在 `config/analytics/industry_structure.yaml`。产物写入 `data/analytics/industry_structure/`，包括 `industry_panel.parquet`、`scores.json`、`report.md`、`human_report.md` 和 `latest/` 副本。行业结构分只用于行业排序和轮动判断，不并入六维综合温度。

行业结构默认权重为动量 40%、估值 25%、基本面 15%、拥挤度 20%。行业基本面由理杏仁 `sw_2021_fs_*` 正式财报和 Tushare `forecast` / `express` / `report_rc` 快速确认项合成；正式财报超过配置天数未更新时自动降权，默认从 70% 降到 40%，快速项从 30% 提到 60%。TCR 使用最近 20 个行业交易日的行业成交额占全部申万一级行业成交额比例均值，并以行业自身历史分位转换为拥挤温度。结构健康度单独输出，核心看 20 日行业扩散、60 日中期确认、Top 行业中期收益和拥挤行业占比。落后方向使用 `lagging_or_weak`，即结构分倒序靠后的行业，用于补充观察弱势和回避方向。

## 标准流程

1. 若用户要重复执行或产出文件，先运行 `make market-temperature DATE=...` 生成标准产物；需要只验证水位时可加 `SKIP_METRICS=1`。
2. 读取 `data-catalog` 技能，确认 `DataCatalog` 用法和数据口径。
3. 先用 `codegraph_explore` 查看 `src/stock/analytics/metrics` 的当前实现，确认 `MetricEngine`、`BUILTIN_METRIC_SPECS`、`BUILTIN_CALCULATORS` 和各 `calculators/*.py` 里的实际计算口径。
4. 查询关键数据集最新水位：
   - `tushare`: `stock_daily_bar`, `daily_basic`, `margin`, `moneyflow`, `moneyflow_hsgt`, `index_daily`, `sw_daily`, `stk_limit`, `limit_list_d`, `opt_basic`, `opt_daily`, `forecast`, `report_rc`, `index_member`, `cn_m`, `sf_month`, `shibor`, `cn_cpi`
   - `lixinger`: `index_fundamental`, `national_debt`, `investor_accounts`, `sw_2021_fundamental`, `sw_2021_constituents`, 四类 `sw_2021_fs_*`
   - `yfinance`: `index_daily_bar`, `macro_indicators`
   - `fred`: `macro_indicators`，仅在需要美国宏观背景时使用
5. 若核心行情或估值缺失，先说明数据缺口，不要硬算综合温度。
6. 用 `MetricEngine` 优先计算已有指标，并按 `references/scoring.md` 的去重归属合成六维分数：
   - 估值：`valuation_temperature`, `pe_percentile_5y`, `pb_percentile_5y`, `equity_risk_premium`, `equity_bond_yield_ratio`
   - 资金：`margin_buy_share`, `margin_penetration`, `margin_balance_growth_20d`, `main_money_net_inflow_share`, `market_amount_percentile_1250d`
   - 情绪/流动性：`market_turnover_rate`, `turnover_rate_percentile_1250d`, `advance_share`, `limit_event_temperature`, `investor_account_temperature`
   - 技术/宽度：`return_20d`, `rsi_14d`, `ma_bias_20d`, `above_ma20_share`, `above_ma60_share`, `new_high_share_252d`, `new_low_share_252d`
   - 风险：`realized_volatility_20d`, `downside_volatility_20d`, `max_drawdown_60d`
7. 用 `DataCatalog` 直接补足基本面扩展指标：`forecast` 业绩预告改善/超预期、`report_rc` 分析师盈利预测上修比例；这些指标不在当前 `metrics` 计算器里。
8. 需要择时或短线节奏判断时，按 `references/scoring.md` 计算 5 日/10 日短线温度，作为附加输出，不并入主综合温度权重。
9. 用 `MarketScanEngine.compute(target_date=latest, index_symbol="000300")` 获取宏观象限、低估行业、拥挤行业、市场健康度，作为交叉校验。
10. 对指标做 0-100 温度归一。分数越高表示越热、越拥挤、越偏进攻；反向指标用 `100 - 分位温度` 或负向 Z-score 转换，利率类低位对应更高流动性温度。
11. 输出时先给综合温度、系统性风险和一句话判断，再列“解读顺序”说明各维度时效性，然后列六维表格；若计算了短线温度，放在主表之后作为节奏参考；最后写结构健康度、结构机会、风险和数据水位限制。

## 六维定义

默认权重：

| 维度 | 权重 | 主指标 |
|---|---:|---|
| 估值面 | 20% | 中证全指 `valuation_temperature` 结果行，辅以沪深300、中证500、中证1000 |
| 资金面 | 20% | 融资买入占比、两融渗透率、两融余额20日变化、主力/北向资金净流入占比、成交额分位低权重活跃度 |
| 情绪面 | 15% | 换手率分位、上涨家数占比、涨跌停/炸板事件温度 |
| 技术面 | 15% | 20日收益、RSI、均线乖离、站上20/60日线比例、距252日高点距离 |
| 基本面 | 15% | 申万2021行业收入/利润 TTM 增速、ROE、业绩预告、盈利预测上修比例 |
| 宏观流动性 | 15% | 中国10年国债、Shibor、M1/M2、社融、中国CPI实际利率；外盘观察作为外部环境子项纳入，不新增第七维 |

短线温度不设主权重，默认只展示 5 日和 10 日节奏判断；除非用户明确要求，否则不要把短线温度并入六维综合温度。

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

申万行业财报多为季频，最近 20 日分析中只能作为基本面底座，不要写成 20 日内发生的财报变化。行业结构报告若 `fundamental_status` 为 `stale_blended` 或 `official_stale`，要明确这是“正式财报滞后，快速预告/快报/研报确认项权重提高”的降级状态。`forecast`、`express` 和 `report_rc` 可反映最近 20 日公告/研报预期变化，但必须披露有效样本数。

宏观月频、季频数据使用最新可得值的历史分位，只代表当前状态，不代表最近 20 个交易日内发生了边际变化。

外盘观察归入宏观流动性维度的“外部环境”子项，默认占宏观维度内部 40%，国内利率和货币信用占 60%。外部环境核心指标为标普500/纳斯达克 20 日收益、VIX 水平、美元指数 20 日变化、美债10年收益率、铜价 20 日收益；美股和铜正向映射，VIX、美元、美债反向映射。黄金和原油方向不稳定，只作背景展示，不直接纳入综合温度；铜等本地缺失项必须披露为数据缺口并对可用子项重归一，不允许用外部记忆补值。

`limit_list_d` 已可作为涨跌停/炸板事件表纳入情绪面；`limit=U` 计为涨停，`D` 计为跌停，`Z` 计为炸板。`stk_limit` 只代表涨跌停价格，不等同事件明细。`lixinger.investor_accounts` 已可作为月度新增投资者慢变量纳入情绪面，不能解释为最近 20 个交易日内的开户变化。`opt_basic` 和 `opt_daily` 已落盘，但当前未定义隐含波动率或期权成交情绪公式，只做水位披露，不进入综合温度。项目没有新闻舆情、政策文本、隐含波动率或中国信用利差 AA-AAA 的稳定本地表。除非用户明确要求联网并给出来源，否则不要把无本地表支撑的维度纳入综合温度。

若 `references/scoring.md` 的指标说明与 `src/stock/analytics/metrics` 源码不一致，以源码实现为准，并在完成分析后更新本 skill。
