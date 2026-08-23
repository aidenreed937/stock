---
name: market-temperature-analysis
description: 用本地 Curated 黄金表和现有 analytics/metrics 体系生成 A 股六维市场温度计分析，并可附加 5/10 日短线温度、申万行业结构分析、跨周期复盘、重要信号日识别和普通投资者简报解读。Use when the user asks for 市场温度、市场体检、六维市场温度计、最近20日综合分析、短线温度、5日/10日节奏、申万行业结构、行业轮动、行业强弱排名、资金估值情绪技术基本面宏观流动性联动分析、跨周期验证、资金运动规律、重要交易日信号，或希望重复执行同一套 A 股市场状态判断框架。
---

# Market Temperature Analysis

## 核心原则

只使用本地 Curated 黄金表和项目内已有分析器输出。不要用模型记忆补点位、政策、新闻或宏观结论；本地没有稳定数据表支撑的维度必须标为不可量化或仅作外部背景。

默认分析周期为最近 20 个已落盘 A 股交易日，而不是最近 20 个自然日。先用 `DataCatalog.latest_trade_dates("stock_daily_bar", n=20)` 取得窗口，再以最新行情交易日作为主口径日期。5 日/10 日窗口只作为短线温度补充观察，不替代 20 日主温度。用户明确要求“最近 N 日”时，N 指交易日，使用批量脚本的 `--last-n N`，不要按自然日倒推。

观测日期规则：显式传入 `DATE` 时以 `DATE` 为准；未传 `DATE` 的市场温度和行业结构分别取各自主数据集的最新交易日；未传 `DATE` 的投资者简报和量化投研简报都扫描两类上游 `runs/as_of=*`，取共同的最新观测日期，再读取该日期下最新一次运行。`latest/` 只是最近一次成功发布的副本，不能替代 `as_of_date` 判断。

市场温度管线还会把外盘事实截断到 A 股基准日前一个已落盘交易日，并在 manifest 的
`source_cutoffs.external_market` 留痕；这是防止隔夜数据前视的固定口径，不要手工把外盘日期推进到
当前 A 股收盘日。

需要理解 `metrics` 与 `market_temperature` 的职责边界、数据流和扩展落点时，读取 `references/architecture.md`。需要系统性理解综合温度金融物理机制、五档操作时钟、快慢背离诊断、一票否决规则与跨周期实战口诀时，读取 `references/composite-temperature-interpretation.md`。需要分析申万2021行业轮动、行业强弱、景气-估值矩阵时，读取 `references/industry-structure.md`。需要具体字段、打分方向、metrics 源码位置和输出模板时，读取 `references/scoring.md`。需要做多日期联合分析、资金运动规律、重要信号日或跨周期验证时，读取 `references/cross-cycle-study.md` 和 `references/signal-days.md`。需要面向普通投资者解释“能不能参与/参与什么方向/如何控风险”时，读取 `references/investor-interpretation.md`。需要验证产物是否可追溯、无编造和无串线时，读取 `references/report-consistency.md`。

## 标准执行入口与安全边界

按以下顺序执行，不要手工拼装 facts 或直接复制 `latest/`：

1. 先用 `DataCatalog` 查询 `stock_daily_bar` 最新交易日；若用户指定日期，确认该日期已落盘，否则报告缺口并停止。
2. 普通单日生成直接运行 `make scan DATE=YYYY-MM-DD`；只要市场温度计则运行 `make market-temperature DATE=YYYY-MM-DD`；若需一键生成包含大盘温度、31 行业主线与自选池量化雷达的每日盘后复盘报告并自动落盘，直接运行 `make daily-review [DATE=YYYY-MM-DD]`。
3. 需要“最近 N 个交易日”或多日历史产物时，只运行下方批量脚本；脚本会先完成所有日期，再统一校验和发布 `latest/`。
4. 需要刷新 Mart 时使用脚本的 `--refresh-mart`，它只走增量构建，不传 `OVERWRITE=1`；构建后必须确认 `market_daily` 历史起点未变化。
5. 禁止把 `TARGET=all ... OVERWRITE=1` 作为日常刷新方式。`OVERWRITE=1` 是有意重建并替换 Mart 的破坏性操作，只能在明确的历史重建/数据修复任务中单独执行，并在执行前记录原始历史起点和备份策略。
6. 批量命令运行时必须看到子命令实时输出；若命令失败、被中断或一致性校验失败，不发布 `latest/`，不把部分产物当作完成。

## 已落地产物链路

优先使用仓库内标准产物管线，而不是每次手工拼装 facts：

```bash
# 0. 特征集市宽表构建与加速 (物化全市场股票日频聚合指标至 data/curated/mart/)
# 日常增量刷新：不带 OVERWRITE=1，保留既有历史
make features-build TARGET=all START=YYYY-MM-DD END=YYYY-MM-DD
make features-build TARGET=market_daily START=YYYY-MM-DD END=YYYY-MM-DD

# 领域 Mart 输入缺失时只生成稳定空 Schema/不可用观察事实，不伪造数据；
# TARGET=all 会先构建 market_daily，再构建领域 Mart。

# 1. 单日市场温度计产物管线
make market-temperature DATE=YYYY-MM-DD
make market-temperature DATE=YYYY-MM-DD COMPARE_DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.market_temperature --date YYYY-MM-DD
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.market_temperature --date YYYY-MM-DD --compare-date YYYY-MM-DD

# 2. 每日盘后全景复盘与配置研报自动落盘管线 (基于 stock_reporting Jinja2 模板引擎)
make daily-review $(if $(DATE),DATE=YYYY-MM-DD)
# 产物自动归档落盘至 output/reports/daily/{YYYY-MM-DD}_全景量化复盘报告.md
```

默认配置在 `config/analytics/market_temperature.yaml`。产物写入 `data/analytics/market_temperature/`：

- `runs/as_of=YYYY-MM-DD/run_YYYYMMDDTHHMMSS/manifest.json`：运行元数据、窗口交易日和文件清单；
- `facts.parquet`：窗口、水位和 `MetricEngine` / `FeatureStore` 指标事实（优先从 `mart.market_daily` 毫秒级提取）；
- `scores.json`：六维温度、综合温度、状态和合成说明；
- `report.md` / `report.json`：面向阅读和机器消费的报告（Markdown 由 `stock_reporting` 经 Jinja2 模板渲染）；
- `human_report.md`：面向人工阅读的结论版报告；
- `quality_report.md` / `quality_report.json`：口径、窗口、水位、滞后和质量约束报告；
- `manifest.json`：除运行窗口和文件清单外，记录外盘 `source_cutoffs` 及可选对比运行；
- `latest/`：最近一次成功发布运行的同名文件副本；仅作展示，不作为观测日期判断依据。

`facts.parquet` 的 `metric_value` 行统一有 `metric_date` 列；旧事实仍可能在 `note` 中保留
`metric_date=`，读取方应优先使用标准列。`scores.json` 顶层还包含配置驱动的 `external_risk`
（外盘背景压力、单日冲击和待 A 股确认状态）以及机器可消费的 `drivers`（跨期综合温度变化和
按维度权重计算的边际贡献）。外盘观察项默认不改写六维综合分。

### 多交易日批量/串行生成约束

连续多个交易日生成产物时，默认按日期串行执行，并在同一进程内复用一次 Mart 与数据读取缓存：

- 批量生成阶段统一不刷新 `latest/`，不能让日期任务交错写共享目录；
- Mart 在批量开始前最多重建一次；报告阶段只读取该次重建结果；
- 投资者简报和量化投研简报必须等待同一基准日的市场温度和行业结构产物完成后再生成，并显式传入 `DATE`；
- 所有日期产物完成后，先执行区间 `report-consistency`；确认全部通过后，再由单个收口任务将选定的最新交易日发布到 `latest/`。

仓库内提供批量快捷脚本
`.agents/skills/market-temperature-analysis/scripts/build_multi_date_artifacts.py`：

```bash
# 从本地 stock_daily_bar 解析区间交易日；日期任务串行执行并共享一次读取缓存
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python \
  uv run python .agents/skills/market-temperature-analysis/scripts/build_multi_date_artifacts.py \
  --start YYYY-MM-DD --end YYYY-MM-DD

# 最近 N 个交易日：按日期串行生成，默认不刷新 Mart（仅在确认上游数据已更新时加 --refresh-mart）
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python \
  uv run python .agents/skills/market-temperature-analysis/scripts/build_multi_date_artifacts.py \
  --last-n N

# 最近 N 个交易日并先增量刷新 Mart；不会覆盖/删除历史，不要加 OVERWRITE=1
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python \
  uv run python .agents/skills/market-temperature-analysis/scripts/build_multi_date_artifacts.py \
  --last-n N --refresh-mart

# 显式指定日期，适合非连续交易日；默认发布其中最新日期到 latest/
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python \
  uv run python .agents/skills/market-temperature-analysis/scripts/build_multi_date_artifacts.py \
  --dates YYYY-MM-DD YYYY-MM-DD --dry-run
```

脚本按日期串行执行市场温度、行业结构、投资者简报和量化投研简报，并在进程内复用一次 Mart 与数据集缓存；生成完成后自动运行一致性校验，校验通过才发布四类产物的 `latest/`，并再次校验 `latest/`。支持 `--start START --end END`、`--last-n N` 和 `--dates DATE...` 三种日期入口。使用 `--no-publish-latest` 可只生成并校验运行目录，使用 `--dry-run` 可只查看计划。批量脚本会实时转发子命令输出，避免长时间无反馈；若 `--refresh-mart` 后发现 `market_daily` 历史起点变晚，会拒绝继续生成。

需要解释两个基准日的驱动差异时，使用 `COMPARE_DATE` / `--compare-date`。它读取对比日期最近一次已落盘的 `manifest.json` 和 `scores.json`，只在人读版报告中加入“跨期驱动变化”表；不会重算或改写前期产物。

当前代码已实现“配置（`config/analytics/`） / 事实（`facts.parquet`） / 评分结构（`scores.json`） / 模板渲染（`src/stock_reporting/`） / 质量报告 / 产物写入”解耦。`scores.json` 已接入六维温度合成、系统性风险、外盘风险和跨期驱动摘要：MetricEngine 指标和 DataCatalog/Mart 派生指标先在 `facts.parquet` 落为事实，再按 `config/analytics/market_temperature.yaml` 中的方向与权重温度化。权重为 0 的指标只作事实展示，不参与维度分。情绪面可拆成 `daily` 主动能、`activity` 活跃水位和 `slow` 慢情绪子组；主组无可用事实时，评分代码才按 `activity`、`slow` 顺序降级。`drivers` 以维度温度差乘维度权重计算 Top 3 边际贡献，便于跨期脚本复用。系统性风险只基于六维温度之间的共振和背离，不使用新闻、政策或模型记忆。`quality_report.md/json` 只基于 manifest、facts 和 YAML 数据配置生成，不重算指标。所有 Markdown 报告均通过 `stock_reporting.engine.ReportRenderer` 统一经 Jinja2 模板（`.md.j2`）渲染输出。

申万行业结构分析使用独立产物管线：

```bash
make industry-structure DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.industry_structure --date YYYY-MM-DD
```

默认配置在 `config/analytics/industry_structure.yaml`。产物写入 `data/analytics/industry_structure/`，包括 `industry_panel.parquet`、`scores.json`、`report.md`、`human_report.md`、`quality_report.md/json` 和 `latest/` 副本。行业结构分只用于行业排序和轮动判断，不并入六维综合温度。

行业结构默认权重为动量 40%、估值 25%、基本面 15%、拥挤度 20%。行业基本面由理杏仁 `sw_2021_fs_*` 正式财报和 Tushare `forecast` / `express` / `report_rc` 快速确认项合成；正式财报超过配置天数未更新时自动降权，默认从 70% 降到 40%，快速项从 30% 提到 60%。TCR 使用最近 20 个行业交易日的行业成交额占全部申万一级行业成交额比例均值，并以行业自身历史分位转换为拥挤温度。结构健康度单独输出，核心看 20 日行业扩散、60 日中期确认、Top 行业中期收益和拥挤行业占比。落后方向使用 `lagging_or_weak`，即结构分倒序靠后的行业，用于补充观察弱势和回避方向。

普通投资者简报使用合并产物管线，只读取同一基准日的市场温度计与行业结构已落盘结果，不重新计算指标。传入 `DATE` 时读取该日期下最新一次运行；省略 `DATE` 时自动选择两个上游产物共同的最新观测日期，不直接信任 `latest/`：

```bash
make investor-brief DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.investor_brief --date YYYY-MM-DD
```

默认配置在 `config/analytics/investor_brief.yaml`。产物写入 `data/analytics/investor_brief/`，包括 `manifest.json`、`brief_report.md/json` 和 `latest/` 副本。简报只回答两个问题：系统风险是否允许参与，以及短期可观察的行业方向；行业方向默认剔除高拥挤和景气承压标签，拥挤行业和落后方向单独列示。

量化投研简报是同一上游事实的 A 视角解释层，面向底层量化投研、风控闸门和行业筛选，不替代普通投资者简报，也不重新计算指标或引入新数据源。它同样只读取同一基准日的市场温度计与行业结构产物：

```bash
make quant-brief DATE=YYYY-MM-DD
# 或
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.quant_brief --date YYYY-MM-DD
```

默认配置在 `config/analytics/quant_brief.yaml`。产物独立写入 `data/analytics/quant_brief/`：

- `runs/as_of=YYYY-MM-DD/run_*/manifest.json`、`brief_report.md`、`brief_report.json`：运行历史及其上游 `run_id` 链接；
- `latest/manifest.json`、`brief_report.md`、`brief_report.json`：最近一次成功发布的量化投研简报；
- `brief_report.json` 顶层包括 `macro`、`nature`、`veto`、`sector`、`risk_gates`、`position_policy`、`data_quality_notes` 和 `reading_notes`。

解读仓位时必须区分：`macro.equity_position_band` 是综合温度给出的基础仓位，`risk_gates.max_position_band` 是风险闸门上限，`position_policy.effective_band` 才是当前有效仓位。`sector.priority_excluded` 用于解释结构领先但因资金未确认、拥挤或景气承压等原因未进入优先方向的行业。`nature.nature_type=distribution_risk` 在人读版中显示为“资金-成交背离风险（硬闸门观察）”，不改变资金硬闸门的实际阈值。

市场温度管线未显式传 `--compare-date` 时，会自动取最近历史已落盘 `as_of` 的 `scores.json` 计算 `drivers`（`composite_delta` 与 Top 3 边际贡献），保证跨期驱动始终可用；显式传入时以显式日期为准。quant_brief 生成时从本地 Curated `tushare.margin` 日频表加载两融余额序列，`veto.margin.turning_point` 输出 `persistent_negative` / `persistent_positive` / `confirmed_turning` / `mixed` / `insufficient_history` 连续状态，替代硬编码的 `insufficient_history`。两融拐点状态只作杠杆方向确认，不改变仓位档位；本地 margin 数据缺失时回退为 `insufficient_history`。

跨周期复盘使用只读产物脚本，先校验一致性，再抽取阶段变化、重要信号日、行业频率、TCR 迁移、
资金 20 日累计占比和情绪面子组变化：

```bash
make report-consistency START=YYYY-MM-DD END=YYYY-MM-DD
make market-cycle-review START=YYYY-MM-DD END=YYYY-MM-DD
```

产物写入 `data/analytics/market_cycle_review/`，包括 `review.md/json` 和 `latest/` 副本。跨周期复盘只总结已落盘事实，不重算市场温度或行业结构。

## 标准流程

1. 读取 `data-catalog` 技能，确认 `DataCatalog` 用法和数据口径。
2. 先查询 `stock_daily_bar` 最新水位和目标日期；用户说“最新”时以该水位为准，不以系统日期或 `latest/` 目录名推断。
3. 若用户要重复执行或产出文件，先按“标准执行入口与安全边界”选择单日或批量命令；不要先无条件重建 Mart。
4. 先用 `codegraph_explore` 查看 `src/stock_analytics/metrics` 的当前实现，确认 `MetricEngine`、`BUILTIN_METRIC_SPECS`、`BUILTIN_CALCULATORS` 和各 `calculators/*.py` 里的实际计算口径。
5. 查询关键数据集最新水位：
   - `tushare`: `stock_daily_bar`, `daily_basic`, `margin`, `moneyflow`, `moneyflow_hsgt`, `index_daily`, `sw_daily`, `stk_limit`, `limit_list_d`, `opt_basic`, `opt_daily`, `cb_basic`, `cb_daily`, `stk_holdertrade`, `repurchase`, `block_trade`, `forecast`, `report_rc`, `index_member`, `shibor`, `cn_cpi`
   - `lixinger`: `index_fundamental`, `national_debt`, `investor_accounts`, `cn_m`, `sf_month`, `sw_2021_fundamental`, `sw_2021_constituents`, 四类 `sw_2021_fs_*`
   - `yfinance`: `index_daily_bar`, `macro_indicators`
   - `alphavantage`: `macro_indicators`，用于 `CNH=X` / USD-CNH 外汇日线
   - `fred`: `macro_indicators`，仅在需要美国宏观背景时使用
6. 若核心行情或估值缺失，先说明数据缺口，不要硬算综合温度。
7. 用 `MetricEngine` 和温度计派生事实按 YAML 中 `weight > 0` 的指标合成六维分数；当前入分清单为：
   - 估值：`valuation_temperature`（由 PE/PB/ERP/股息率的 **10Y 分位** 等权合成）；`pe_percentile_10y`、`pb_percentile_10y`、`equity_risk_premium_percentile_10y` 是可解释的辅助事实，`dividend_yield_percentile_10y` 是综合温度的内部组件，不是独立 YAML 入分项；相关 5Y 分位只作历史兼容，raw `equity_risk_premium` 仍作为事实展示，不直接参与温度评分。
   - 资金：`margin_buy_share_zscore_60d`, `margin_penetration_percentile_1250d`, `margin_balance_growth_20d`, `margin_balance_growth_60d`, `main_money_net_inflow_share`, `main_money_net_inflow_share_20d_cum`。
   - 情绪：`turnover_rate_percentile_1250d`, `advance_share`, `limit_event_temperature`, `investor_account_temperature`。
   - 技术：`return_20d`, `rsi_14d`, `ma_bias_20d`, `above_ma20_share`, `above_ma60_share`, `new_high_share_252d`, `new_low_share_252d`。
   - 基本面：`fs_revenue_growth_temperature`, `fs_profit_growth_temperature`, `fs_roe_temperature`, `forecast_positive_temperature`, `report_revision_temperature`；六维基本面没有 `express` 子项。
   - 宏观流动性：`macro_bond_yield_10y_temperature`, `macro_shibor_on_temperature`, `macro_real_rate_temperature`, `macro_m2_yoy_temperature`, `macro_m1_m2_gap_temperature`, `macro_social_finance_stock_temperature`, `macro_external_environment_temperature`。
8. 用 `DataCatalog` 派生事实补足 YAML 已配置的基本面指标：`forecast_positive_temperature` 和 `report_revision_temperature`；`express` 只属于独立的申万行业结构模块，不得写入六维基本面分。资金 20 日累计占比使用同一窗口累计主力净流入 / 累计成交额；报告中同时披露其 `metric_date` 和窗口起止。
9. 需要择时或短线节奏判断时，按 `references/scoring.md` 计算 5 日/10 日短线温度，作为附加输出，不并入主综合温度权重。
10. 需要行业交叉校验时，读取同一基准日的 `data/analytics/industry_structure/` 标准产物；行业结构分独立计算，不并入六维综合温度。
11. 对指标做 0-100 温度归一。分数越高表示越热、越拥挤、越偏进攻；反向指标用 `100 - 分位温度` 或负向 Z-score 转换，利率类低位对应更高流动性温度。
12. 输出前检查 `quality_report.md/json`：硬错误不得忽略；软警告必须在数据限制或口径说明里解释。批量任务还必须运行区间 `report-consistency`，通过后才发布 `latest/`。
13. 输出时先给综合温度、系统性风险和一句话判断，再列“解读顺序”说明各维度时效性，然后列六维表格；若计算了短线温度，放在主表之后作为节奏参考；最后写结构健康度、结构机会、风险和数据水位限制。

## 六维定义

默认权重：

| 维度 | 权重 | 主指标 |
|---|---:|---|
| 估值面 | 20% | 最新日期所有可用指数 `valuation_temperature` 结果的均值；报告必须核对具体 `symbol`，不能默认称为中证全指 |
| 资金面 | 20% | 融资买入占比、两融渗透率、两融余额20日变化、主力/北向资金净流入占比；自由流通换手率分位仅作历史兼容观察 |
| 情绪面 | 15% | 换手率分位、上涨家数占比、涨跌停/炸板事件温度 |
| 技术面 | 15% | 20日收益、RSI、均线乖离、站上20/60日线比例、距252日高点距离 |
| 基本面 | 15% | 申万2021行业收入/利润 TTM 增速、ROE、业绩预告、盈利预测上修比例 |
| 宏观流动性 | 15% | 中国10年国债、Shibor、M1/M2、社融、中国CPI实际利率；外盘观察作为外部环境子项纳入，不新增第七维 |

短线温度不设主权重，默认只展示 5 日和 10 日节奏判断；除非用户明确要求，否则不要把短线温度并入六维综合温度。

## 输出要求

区分三层信息：

- 已验证事实：本地数据直接计算得到的日期、数值、分位、变化。
- 机制推断：由指标组合推出的市场状态，如“短线偏热但中期趋势未全面确认”。
- 数据限制：数据滞后、字段口径不明、缺少政策/新闻/标准隐含波动率指数或 VIX 等。

常用结论分档：

| 综合温度 | 描述 |
|---:|---|
| `< 20` | 低温机会区 |
| `20-40` | 偏冷修复观察区 |
| `40-60` | 中性轮动区 |
| `60-80` | 偏热修复区 |
| `> 80` | 高温拥挤区 |

## 口径提醒

`moneyflow` 的固定可用时滞没有权威上限，资金结论要写清最新资金日期和 `metric_date`，以实际入库水位为准。单日主力净流入只描述脉冲，20 日累计占比才用于趋势确认；`moneyflow_hsgt.north_money` 在当前库里按资金金额使用，除非已验证字段语义，否则不要表述为严格“北向净买入”。

申万行业财报多为季频，最近 20 日分析中只能作为基本面底座，不要写成 20 日内发生的财报变化。行业结构报告若 `fundamental_status` 为 `stale_blended` 或 `official_stale`，要明确这是“正式财报滞后，快速预告/快报/研报确认项权重提高”的降级状态。`forecast`、`express` 和 `report_rc` 可反映最近 20 日公告/研报预期变化，但必须披露有效样本数。

宏观月频、季频数据使用最新可得值的历史分位，只代表当前状态，不代表最近 20 个交易日内发生了边际变化。

外盘观察归入宏观流动性维度的“外部环境”子项，默认占宏观维度内部 40%，国内利率和货币信用占 60%。外部环境核心指标为标普500/纳斯达克 20 日收益、VIX 水平、美元指数 20 日变化、美债10年收益率、铜价 20 日收益；美股和铜正向映射，VIX、美元、美债反向映射。`CNH=X` 离岸人民币从 Alpha Vantage `macro_indicators` 读取，只作人民币汇率压力观察项，默认 `weight: 0`，不进入外部环境合成。黄金和原油方向不稳定，不进入外部环境正式分；它们进入“外部压力提示”，与 VIX、美股、美债、CPI、铜联动生成避险压力、通胀压力、需求压力和总体外部压力。外部压力项默认 `weight: 0`，分数越高表示压力越大，只作风险背景，不进入六维综合温度。铜等本地缺失项必须披露为数据缺口并对可用子项重归一，不允许用外部记忆补值。
外盘观察归入宏观流动性维度的“外部环境”子项，默认占宏观维度内部 40%，国内利率和货币信用占 60%。外部环境核心指标为标普500/纳斯达克 20 日收益、VIX 水平、美元指数 20 日变化、美债10年收益率、铜价 20 日收益；美股和铜正向映射，VIX、美元、美债反向映射。`CNH=X` 离岸人民币从 Alpha Vantage `macro_indicators` 读取，只作人民币汇率压力观察项，默认 `weight: 0`，不进入外部环境合成。黄金和原油方向不稳定，不进入外部环境正式分；它们进入“外部压力提示”，与 VIX、美股、美债、CPI、铜联动生成避险压力、通胀压力、需求压力和总体外部压力。外部压力项默认 `weight: 0`，分数越高表示压力越大，只作风险背景，不进入六维综合温度。另有配置驱动的单日外盘冲击规则（标普/纳指/费城半导体单日下跌、VIX 或美债收益率单日上升）；触发后 `transmission_status` 只标记“等待下一交易日 A 股确认”，不能把隔夜冲击直接写成 A 股已传导。铜等本地缺失项必须披露为数据缺口并对可用子项重归一，不允许用外部记忆补值。

FRED 美国宏观背景归入宏观流动性维度的观察项，默认 `weight: 0`，只落 facts 和报告展示，不参与 `macro_external_environment_temperature` 或综合温度。当前观察项包括 `T10Y2Y` 期限利差、`FEDFUNDS` 政策利率、`WALCL` 美联储资产负债表、`CPIAUCSL` 同比、`UNRATE`、`PAYEMS` 同比和 `GDP` 同比；政策利率、通胀和失业率使用反向历史分位，期限利差、资产负债表、非农同比和 GDP 同比使用正向历史分位。月频/季频项只能解释最新美国宏观背景，不要写成最近 20 个 A 股交易日内的边际变化。

`limit_list_d` 已可作为涨跌停/炸板事件表纳入情绪面；`limit=U` 计为涨停，`D` 计为跌停，`Z` 计为炸板。`stk_limit` 只代表涨跌停价格，不等同事件明细。`lixinger.investor_accounts` 已可作为月度新增投资者慢变量纳入情绪面，不能解释为最近 20 个交易日内的开户变化。`opt_basic` 和 `opt_daily` 已可计算认沽/认购成交量比、认沽/认购持仓比、期权成交额、持仓量和近月合约成交占比温度，但这些期权项默认 `weight: 0`，只作风险观察，不进入情绪面正式分或综合温度。`settlement_iv_proxy_daily` 已基于期权结算价、合约、标的行情和利率生成波动率代理，并已接入情绪面评分：`settlement_iv_proxy_temperature`（全市场 BS-IV 中位数历史反向分位）与 `settlement_iv_proxy_skew_temperature`（认沽-认购 IV 偏度历史反向分位）由 `derived.py` 以 `unit=temperature` 写入 `metric_value` 事实，默认 `weight: 0`，仅在明确评估后可按 YAML 上调权重。它不是标准隐含波动率指数或 VIX，升级权重后仍必须在报告中持续标注该口径限制。项目没有新闻舆情、政策文本、标准 IV/VIX 或中国信用利差 AA-AAA 的稳定本地表。除非用户明确要求联网并给出来源，否则不要把无本地表支撑的维度纳入综合温度。

行业资金流可由 `tushare.moneyflow` 通过 `tushare.index_member` / `lixinger.sw_2021_constituents` 的申万2021成分映射聚合到一级行业，并用 `stock_daily_bar.amount` 作分母计算行业主力净流入成交占比。行业资金流当前只作为“资金确认/资金流出压力”观察项输出，不进入行业结构总分。

评分唯一来源是 `config/analytics/market_temperature.yaml`、`src/stock_analytics/pipelines/market_temperature/metric_temperature.py` 和 `src/stock_analytics/pipelines/market_temperature/scoring.py`：YAML 决定维度/指标权重与方向，温度转换源码决定 0-100 映射，评分源码决定缺失指标和缺失维度的重归一。若本文件或 `references/scoring.md` 与上述配置/源码不一致，以配置和源码为准，并在完成分析后更新本 skill。
