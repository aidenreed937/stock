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
    --data-source tushare \
    --endpoint daily \
    --force-refresh
```

### 1.3 CLI 参数列表

| 参数名 | 简写/长选项 | 类型 | 是否必填 | 默认值 | 作用与示例 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **开始日期** | `--start` | `str` | **是** | 无 | 回填起始日期 (格式 `YYYY-MM-DD`，如 `2026-01-01`) |
| **结束日期** | `--end` | `str` | **是** | 无 | 回填结束日期 (格式 `YYYY-MM-DD`，如 `2026-08-12`) |
| **数据源名称** | `--data-source` | `str` | 否 | `tushare` | 标识来源，决定 RAW 归档路径 (如 `tushare`, `akshare`) |
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
    --data-source tushare \
    --endpoint adj_factor,hk_hold,daily_basic \
    --start 2024-01-01 \
    --end 2026-08-12
```

#### 场景 5：使用 Alpha Vantage 回填 `CNH=X` 离岸人民币历史

Alpha Vantage 的 `fx_daily` 使用 `FX_DAILY` 接口，回填默认配置为每分钟 5 次请求、1 个 Worker；需要先配置 API key：

```bash
export ALPHA_VANTAGE_API_KEY="你的真实API_KEY"
make backfill \
    START=2014-08-01 \
    END=2026-08-14 \
    SOURCE=alphavantage \
    ENDPOINT=fx_daily \
    SYMBOL="CNH=X" \
    FORCE_REFRESH=1
```

回填后可检查 `data/curated/alphavantage/market=GLOBAL/macro_indicators/data.parquet` 的日期覆盖和行数。

---

## 2. 增量同步工具 (Daily Sync CLI)

```bash
# 默认同步指定数据源的全部公开原子任务
make sync SOURCE=lixinger

# 使用 TaskBundle 调度 LiXinger 行业相关任务
make sync SOURCE=lixinger ENDPOINT=industry_bundle

# 多个 bundle 或原子 task 可混合传入；展开后仍逐个任务独立执行
make sync SOURCE=lixinger ENDPOINT=market_bundle,macro_monthly_bundle

# 或直接调用 Python 模块
uv run python -m stock_cli.sync --data-source lixinger --endpoint industry_bundle
```

可用 LiXinger bundle：`market_bundle`、`industry_bundle`、`company_bundle`、`macro_daily_bundle`、`macro_monthly_bundle`。`index_fundamental` 任务只有一个原子接口，继续直接传入；历史名称 `macro_bundle`、`index_bundle` 已移除。bundle 仅是调度输入，不合并数据集、水位或失败状态。

其他数据源的推荐 bundle：

- TuShare：`daily_market_bundle`、`fund_daily_bundle`、`hsgt_flow_bundle`、`financial_statement_bundle`、`pit_bundle`、`macro_daily_bundle`、`macro_monthly_bundle`、`metadata_bundle`。
- LiXinger：`market_bundle`、`industry_bundle`、`company_bundle`、`macro_daily_bundle`、`macro_monthly_bundle`；`index_fundamental` 继续作为原子任务。
- yfinance：`fundamental_bundle`、`corporate_action_bundle`、`research_daily_bundle`、`research_event_bundle`。
- FRED：`macro_monthly_bundle`。日频、季频和周频目前各只有一个序列，继续使用原子任务；聚合任务 `macro_indicators` 仅保留显式调用，避免重复请求。

Alpha Vantage 增量同步只有 `fx_daily` 一个任务。同步 CLI 默认读取 `config/data.yaml` 中的数据源并发配置；当前 Alpha Vantage 配置为单并发，直接执行即可：

```bash
make sync SOURCE=alphavantage ENDPOINT=fx_daily WORKERS=1
```

---

## 3. 全市场全景温度计与体检 CLI (Market Scan CLI)

一键生成宏观、中观、微观六维市场温度计与申万行业结构报告：

```bash
# 通过 Makefile 快捷执行 (支持 DATE, FORMAT, OUTPUT)
make scan DATE=2026-08-14 FORMAT=markdown

# 或直接运行 Python 模块
uv run python -m stock_cli.market_temperature --date 2026-08-14 --format markdown
```

---

## 4. 全市场实时聚合 CLI (Market Aggregate CLI)

独立于核心观察池腾讯逐标的监控，低频抓取 A 股全市场并只输出聚合摘要，不输出 5,500+ 只股票的逐标的明细：

```bash
# 单次聚合快照
make market-aggregate

# Markdown 摘要并将一行快照留档到 data/raw/realtime/market_aggregate/eastmoney
make market-aggregate FORMAT=markdown RECORD=1

# 建议 30～60 秒一轮的低频监控
make market-aggregate WATCH=1 INTERVAL=60
```

输出包括覆盖率、涨跌家数及占比、±5% 强势家数、中位数与分位数涨跌幅、成交额加权涨跌幅、成交额、总/流通市值、流通市值换手率和成交额前 5% 集中度。覆盖不完整或使用缓存时会分别显示 `partial`、`stale`/`expired`。这些指标不等同于涨跌停、全市场均线比例或行业轮动结论。

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

---

## 6. 全局数据源探测工具 (Global Data Probe CLI)

用于快速检测各大数据源（TuShare, yfinance, FRED, 理杏仁）的连通性、响应时延与 Schema 契约状态。

```bash
# 通过 Makefile 快捷执行
make probe

# 或直接运行 Python 模块
uv run python -m stock_data.ops.probe
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
uv run python -m stock_data.validator --endpoint daily
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
