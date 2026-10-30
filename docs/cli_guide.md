# 金融数据分析与历史回填 CLI 命令行使用指南

本文档汇总了系统中所有可用命令行工具 (CLI)、Makefile 快捷指令与常用执行场景。

---

## 1. 历史数据回填工具 (Historical Backfill CLI)

用于全市场历史行情与基本面数据的批量补全、断点续传与重洗。

### 1.1 快捷执行 (Makefile)

```bash
# 1. 基础回填 (默认 tushare 数据源日线行情)
make backfill START=2026-08-01 END=2026-08-12
```

### 1.2 完整参数调用 (`python -m stock_cli.backfill`)

```bash
uv run python -m stock_cli.backfill \
    --start 2026-08-01 \
    --end 2026-08-12 \
    --source tushare \
    --endpoint daily \
    --force-refresh
```

### 1.3 CLI 参数列表

| 参数名 | 简写/长选项 | 类型 | 是否必填 | 默认值 | 作用与示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **开始日期** | `--start` | `str` | **是** | 无 | 回填起始日期 (格式 `YYYY-MM-DD`，如 `2026-01-01`) |
| **结束日期** | `--end` | `str` | **是** | 无 | 回填结束日期 (格式 `YYYY-MM-DD`，如 `2026-08-12`) |
| **数据源名称** | `--source` | `str` | 否 | `tushare` | 标识来源，决定 RAW 归档路径 |
| **接口名称** | `--endpoint` | `str` | 否 | `daily` | API 接口标识 (如 `daily`, `daily_basic`, `income`) |
| **强制覆盖** | `--force-refresh` | `flag` | 否 | `False` | 开启后绕过本地 RAW 离线缓存，重新从 API 请求并覆盖归档 |

### 1.4 常见使用场景

#### 场景 1：追溯回填过去 1 年的日线行情（支持断点续传）
```bash
uv run python -m stock_cli.backfill --start 2025-08-01 --end 2026-08-12
```

#### 场景 2：重新抓取并覆盖某月数据 (强制刷新缓存)
```bash
uv run python -m stock_cli.backfill --start 2026-07-01 --end 2026-07-31 --force-refresh
```

#### 场景 3：回填每日指标数据 (`daily_basic`)
```bash
uv run python -m stock_cli.backfill --start 2026-08-01 --end 2026-08-12 --endpoint daily_basic
```

#### 场景 4：单一 CLI 进程按顺序串行回填多个核心接口 (防超限、防超并发)
```bash
uv run python -m stock_cli.backfill \
    --source tushare \
    --endpoint adj_factor,hk_hold,daily_basic \
    --start 2024-01-01 \
    --end 2026-08-12
```

#### 场景 5：使用 Alpha Vantage 回填 `CNH=X` 离岸人民币历史

Alpha Vantage 的 `fx_daily` 使用 `FX_DAILY` 接口，回填默认配置为每分钟 5 次请求、1 个 Worker；需要先配置 API key。若有多个已授权 Key，可用 JSON 数组配置 Key 池，客户端会按额度/服务失败切换，不会在成功请求之间轮换：

```bash
export ALPHA_VANTAGE_API_KEY="你的真实API_KEY"
# 可选：多个已授权 Key
export ALPHA_VANTAGE_API_KEYS='["主Key","备用Key"]'
make backfill \
    START=2014-08-01 \
    END=2026-08-14 \
    SOURCE=alphavantage \
    ENDPOINT=fx_daily \
    SYMBOL="CNH=X" \
    FORCE_REFRESH=1
```

回填后可检查 `data/curated/alphavantage/market=GLOBAL/macro_indicators/data.parquet` 的日期覆盖和行数。

美股个股日线使用 `stock_daily_bar`，底层调用 `TIME_SERIES_DAILY`。免费额度按最近 100 个交易日窗口设计，适合增量同步，不适合全历史回填：

```bash
make sync SOURCE=alphavantage ENDPOINT=stock_daily_bar WORKERS=1
```

结果落在 `data/curated/alphavantage/market=US/stock_daily_bar/`。Alpha Vantage 与 yfinance 使用独立 Provider 和目录，可以分别同步或交叉校验；系统不会自动用一个来源无规则覆盖另一个来源。

需要“先补 yfinance、再用 Alpha Vantage 最少次数兜底”时使用混合回填入口。它按标的/交易日检查缺口，Alpha Vantage 只对近期仍有缺口的标的各请求一次；免费 `compact` 无法覆盖最近 100 个交易日以前的历史缺口，会在摘要中披露：

```bash
make backfill \
    SOURCE=us_hybrid \
    ENDPOINT=stock_daily_bar \
    SYMBOL=watchlist \
    START=2014-08-01 \
    END=2026-10-07 \
    WORKERS=1
```

---

## 2. 增量同步工具 (Daily Sync CLI)

```bash
# 默认同步指定数据源的常规公开原子任务；高消耗个股风险接口不包含在内
make sync SOURCE=lixinger

# 使用 TaskBundle 调度 LiXinger 行业成分与估值任务
make sync SOURCE=lixinger ENDPOINT=industry_bundle

# 单独调度季度行业合并财报（历史回填按季度末 × 行业代码批次请求）
make sync SOURCE=lixinger ENDPOINT=industry_financial_bundle

# 多个 bundle 或原子 task 可混合传入；展开后仍逐个任务独立执行
make sync SOURCE=lixinger ENDPOINT=market_bundle,macro_monthly_bundle

# 或直接调用 Python 模块
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.sync --source lixinger --endpoint industry_bundle
```

理杏仁支持多个已授权 Token 的 profile 配置。`.env` 中使用 JSON 配置表，并通过
`LIXINGER_PROFILE` 为当前进程显式选择一个 Token；未配置时继续兼容 `LIXINGER_TOKEN`。
不在收到 403 额度耗尽时自动轮换 Token：

```bash
LIXINGER_TOKENS='{"primary":"...","backup":"..."}'
LIXINGER_PROFILE=primary

LIXINGER_PROFILE=backup make backfill \
  START=2020-01-01 END=2026-06-30 \
  SOURCE=lixinger ENDPOINT=industry_financial_bundle
```

可用 LiXinger bundle：`market_bundle`、`industry_bundle`（申万成分与估值）、`industry_financial_bundle`（申万一/二/三级季度合并财报）、`company_bundle`、`company_risk_event_bundle`、`macro_daily_bundle`（含 `gold_price`：伦敦金与上海金）、`macro_monthly_bundle`。`index_fundamental` 任务只有一个原子接口，继续直接传入；历史名称 `macro_bundle`、`index_bundle` 已移除。bundle 仅是调度输入，不合并数据集、水位或失败状态。

黄金替代源可单独回填：

```bash
make backfill SOURCE=lixinger ENDPOINT=gold_price \
  START=2025-10-01 END=2026-10-08 WORKERS=1
```

监管措施、交易所问询和限售解禁风险接口属于高消耗任务，已注册但不进入默认
`make sync SOURCE=lixinger`。显式指定时默认仅采集 LiXinger 观察池：

```bash
make sync SOURCE=lixinger ENDPOINT=regulatory_measures
make sync SOURCE=lixinger ENDPOINT=exchange_inquiry
make sync SOURCE=lixinger ENDPOINT=unlock_summary

# 单只候选股按需回填历史
make backfill SOURCE=lixinger ENDPOINT=regulatory_measures SYMBOL=600519 \
  START=2024-01-01 END=2026-08-21
```

其他数据源的推荐 bundle：

- TuShare：`daily_market_bundle`、`fund_daily_bundle`、`fund_portfolio_bundle`、`hsgt_flow_bundle`、`financial_statement_bundle`、`pit_bundle`、`macro_daily_bundle`、`macro_monthly_bundle`、`metadata_bundle`、`corporate_action_bundle`、`shareholder_event_bundle`、`research_daily_bundle`、`market_behavior_bundle`、`pledge_bundle`。
- LiXinger：`market_bundle`、`industry_bundle`（申万成分与估值）、`industry_financial_bundle`（申万季度合并财报）、`company_bundle`、`company_risk_event_bundle`、`macro_daily_bundle`（含 `gold_price`：伦敦金与上海金）、`macro_monthly_bundle`；`index_fundamental` 继续作为原子任务。
- yfinance：`fundamental_bundle`、`corporate_action_bundle`、`research_daily_bundle`、`research_event_bundle`。
- FRED：`global_macro_daily_bundle`（DGS10、DGS3MO、T10Y2Y、VIXCLS、WTI、广义美元指数、月频铜价）和 `macro_monthly_bundle`；聚合任务 `macro_indicators` 仅保留显式调用，避免重复请求。
- Industry：`semiconductor_bundle`（半导体 13 个在线/存证端点）、`industry_tech_bundle`、`chemical_industry_bundle`、`industry_energy_bundle`、`industry_consume_bundle`、`industry_macro_bundle`、`industry_gacc_bundle`、`industry_monthly_bundle`、`industry_all_bundle`。

半导体专项同步应使用 `semiconductor_bundle` 或 `make sync-semiconductor`；`industry_tech_bundle` 只用于跨行业科技数据，不包含先进封装与 CoWoS 两个半导体专项端点。

化工专项同步使用 `chemical_industry_bundle` 或 `make sync-chemical`；利润腿和 10 年产能利用率仍属于手工存证任务，不进入该自动同步包。

新注册的高消耗研究接口默认不进入 `make sync SOURCE=tushare`；需要时显式运行对应 bundle，或单独指定 `dc_concept_cons`：

```bash
make sync SOURCE=tushare ENDPOINT=shareholder_event_bundle
make sync SOURCE=tushare ENDPOINT=research_daily_bundle  # 包含 cyq_perf (<1s 直出全市场)
make sync SOURCE=tushare ENDPOINT=market_behavior_bundle
make sync SOURCE=tushare ENDPOINT=dc_concept_cons
make sync SOURCE=tushare ENDPOINT=top10_floatholders,stk_holdernumber  # 单日秒级增量公告同步 (<1s)
```

公司行为四个事件端点（`stk_holdertrade`、`repurchase`、`block_trade`、`share_float`）在发布窗口后按有限滚动窗口每日刷新；需要同步完成后重建受影响 Mart 时追加 `REFRESH_MARTS=1`：

```bash
make sync SOURCE=tushare ENDPOINT=corporate_action_bundle REFRESH_MARTS=1
```

TuShare 财报使用 `financial_statement_bundle`，展开为 `income`、`fina_indicator`、`balancesheet`、
`cashflow` 四个报告期任务。它们与 `top10_floatholders`、`stk_holdernumber` 均属于全市场批量任务（`fetch_mode=per_period`），按目标日前最近已完成季度末调度，并以全市场 `stock_basic` 为股票池；当前报告期可能刷新以吸收重述。CLI 传项目任务名，不传上游内部的 `*_vip` 名称：

```bash
make sync SOURCE=tushare ENDPOINT=financial_statement_bundle
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=tushare ENDPOINT=financial_statement_bundle
make backfill START=2020-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=top10_floatholders,stk_holdernumber
make backfill START=2024-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=cyq_perf
```

Alpha Vantage 增量同步包含 `stock_daily_bar`、`fx_daily` 和公司基本面任务。公司基本面使用独立的 `alphavantage` 数据目录，不覆盖 yfinance 的同名数据集；当前 Alpha Vantage 配置为单并发，直接执行即可：

```bash
make sync SOURCE=alphavantage ENDPOINT=stock_daily_bar WORKERS=1
make sync SOURCE=alphavantage ENDPOINT=fx_daily WORKERS=1
# 免费优先：EARNINGS、INCOME_STATEMENT、BALANCE_SHEET、CASH_FLOW
make sync SOURCE=alphavantage ENDPOINT=fundamental_bundle WORKERS=1
```

可单独执行的公司数据任务为 `company_overview`、`earnings`、`financials`、`balance_sheet`、`cashflow`。
其中 `company_overview` 对应 Alpha Vantage 的 `OVERVIEW`，官方文档标为 Premium，默认任务包不会执行；需要 Premium 权限时使用 `premium_fundamental_bundle` 显式调用。其余四项返回年度与季度报告，实际可用性仍受账户额度和接口策略约束。

---

## 3. 全市场全景温度计与体检 CLI (Market Scan CLI)

一键生成宏观、中观、微观六维市场温度计与申万行业结构报告：

```bash
# 通过 Makefile 快捷执行
make scan DATE=2026-08-14

# 或直接运行 Python 模块
uv run python -m stock_cli.market_temperature --date 2026-08-14
```

需要解释两个基准日的温度变化时，传入 `COMPARE_DATE`；它会把前一运行的评分交给
`scores.json.drivers`，不改写历史产物。跨交易日复盘必须先运行一致性校验：

```bash
make market-temperature DATE=2026-08-14 COMPARE_DATE=2026-08-13
make report-consistency START=2026-08-01 END=2026-08-14
make market-cycle-review START=2026-08-01 END=2026-08-14
```

### 3.1 多日期分析产物 CLI

多日期入口会按交易日串行生成市场温度、行业结构、投资者简报和量化投研简报，先完成一致性校验，再发布选定日期的 `latest`。批量过程不在 skill 目录内维护脚本：

```bash
# 最近 N 个交易日
make multi-date LAST_N=20

# 指定交易日区间
make multi-date START=2026-08-01 END=2026-08-14

# 显式指定非连续交易日并预览计划
make multi-date DATES="2026-08-01 2026-08-14" DRY_RUN=1

# 直接查看当前 CLI 参数
uv run python -m stock_cli.multi_date --help
```

需要增量刷新 Mart 时追加 `REFRESH_MARTS=1`（兼容 `REFRESH_MART=1`）；实验或回填运行使用 `RUN_CLASS=experiment` 或 `RUN_CLASS=backfill`。历史重建仍需显式使用特征构建 CLI 的覆盖参数，并提前确认备份和恢复方案。

---

## 4. 全市场实时聚合 CLI (Market Aggregate CLI)

独立于核心观察池腾讯逐标的监控，低频抓取 A 股全市场并只输出聚合摘要，不输出 5,500+ 只股票的逐标的明细。默认配置为 `config/analytics/market_aggregate.yaml`，报告模板由 `stock_reporting` 的 Jinja2 渲染器加载：

```bash
# 单次聚合快照
make market-aggregate

# Markdown 摘要并将一行快照留档到 data/raw/realtime/market_aggregate/tencent
make market-aggregate FORMAT=markdown RECORD=1

# 建议 30～60 秒一轮的低频监控
make market-aggregate WATCH=1 INTERVAL=60

# 使用自定义配置和产物目录
make market-aggregate CONFIG=config/analytics/market_aggregate.yaml OUTPUT_ROOT=data/analytics/market_aggregate
```

全市场聚合默认读取本地 `stock_basic` 股票全集，按批次调用腾讯行情接口；不会用核心观察池代替全市场。若本地基础库缺失，先运行 `make backfill ENDPOINT=stock_basic`。单批请求数量可通过 `BATCH_SIZE` 覆盖。

输出包括覆盖率、涨跌家数及占比、±5% 强势家数、中位数与分位数涨跌幅、成交额加权涨跌幅、成交额、总/流通市值、流通市值换手率和成交额前 5% 集中度。覆盖不完整或使用缓存时会分别显示 `partial`、`stale`/`expired`。这些指标不等同于涨跌停、全市场均线比例或行业轮动结论。

每次运行生成 `manifest.json`、`snapshot.json`、`facts.parquet`、`report.md`、`report.json`、`human_report.md`、`quality_report.md/json`，并按配置刷新 `latest/`。

### 4.1 产物分类、索引与清理

管线产物默认标记为 `official`，也可标记为 `backfill` 或 `experiment`：

```bash
make market-temperature DATE=2026-08-14 RUN_CLASS=experiment
```

每个产物根目录会维护 `run_index.json`。也可以手动重建：

```bash
make artifact-index ROOT=data/analytics/market_temperature
```

历史运行包清理默认只处理 `experiment`，且默认预览，不删除；执行删除必须显式传 `APPLY=1`。`latest/` 对应的运行包始终保护：

```bash
make cleanup-analytics ROOT=data/analytics/market_temperature \
  OLDER_THAN_DAYS=30 RUN_CLASS=experiment
make cleanup-analytics ROOT=data/analytics/market_temperature \
  OLDER_THAN_DAYS=30 RUN_CLASS=experiment APPLY=1
```

若配置启用短期趋势，还会生成 `trend.parquet`：当前腾讯盘中快照与前 4 个完整交易日的本地
`stock_daily_bar` / `daily_basic` 聚合对比。涨跌占比和涨跌幅分布可以做结构比较，但成交额和
流通市值换手率会显式标记“盘中 vs 完整日不可比”，不能直接外推全天值。

---

## 5. 全库物理存储主审计 CLI (Master Audit CLI)

基于 Polars 物理扫描全库全部 Parquet 文件，输出全表覆盖标的数、最小/最大交易日与完备度诊断：

```bash
# 通过 Makefile 快捷执行
make master-audit
make audit TYPE=master DOMAIN=valuation FREQ=daily

# 或直接运行 Python 模块
uv run python -m stock_cli.audit --type master
```

专项审计示例：

```bash
make audit TYPE=factor DATE=2026-08-14       # adj_factor 与申万一级行业覆盖
make audit TYPE=valuation DATE=2026-08-14    # daily_basic 与行情个股对齐
make backfill-accept ENDPOINT=income SOURCE=tushare START=YYYY-MM-DD END=YYYY-MM-DD
```

---

## 6. 全局数据源探测工具 (Global Data Probe CLI)

用于快速检测各大数据源（TuShare, yfinance, FRED, 理杏仁）的连通性、响应时延与 Schema 契约状态。

```bash
# 通过 Makefile 快捷执行
make probe

# 或直接运行 Python 模块
uv run python -m stock_data.governance.ops.probe
```

---

## 7. 离线数据质量审计工具 (Offline Data Validator CLI)

用于对本地 DuckDB 归档数据执行完整性与准确性规则校验（如：空值检查、主键重复、物理逻辑错误、断点检测等）。

```bash
# 默认审计日线数据 (daily)
make validate

# 指定审计其他接口 (通过 Makefile)
make validate ENDPOINT=daily_basic

# 完整参数调用
uv run python -m stock_data.governance.validator --endpoint stock_daily_bar
```

---

## 8. 主示范程序 CLI

运行 YAML 策略驱动的主流程测试：

```bash
# 执行 main 程序
make run

# 或直接运行 Python 模块
uv run python -m stock_cli.main
```

---

## 9. 代码质量与环境检查 CLI

在提交代码或发布前，运行全量代码规范与单测检查：

```bash
# 全量检查 (代码格式化 + Lint 检查 + Mypy 严格类型检查 + Pytest 测试 + 类规模约束)
make check

# 单独运行模块检查
make format   # Ruff 格式化
make lint     # Ruff 静态规则 + Mypy 检查 + 类规模门禁
make test     # Pytest 全量测试与覆盖率统计
```
