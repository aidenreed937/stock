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

### 1.2 完整参数调用 (`python -m stock.data.backfill`)

```bash
uv run python -m stock.data.backfill \
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
uv run python -m stock.data.backfill --start 2025-08-01 --end 2026-08-12
```

#### 场景 2：重新抓取并覆盖某月数据 (强制刷新缓存)
```bash
uv run python -m stock.data.backfill --start 2026-07-01 --end 2026-07-31 --force-refresh
```

#### 场景 3：回填每日指标数据 (`daily_basic`)
```bash
uv run python -m stock.data.backfill --start 2026-08-01 --end 2026-08-12 --endpoint daily_basic
```

#### 场景 4：单一 CLI 进程按顺序串行回填多个核心接口 (防超限、防超并发)
```bash
uv run python -m stock.data.backfill \
    --data-source tushare \
    --endpoint adj_factor,hk_hold,daily_basic \
    --start 2024-01-01 \
    --end 2026-08-12
```

---

## 2. 增量同步工具 (Daily Sync CLI)

```bash
# 默认同步指定数据源的全部公开原子任务
make sync SOURCE=lixinger

# 使用 TaskBundle 调度 LiXinger 行业相关任务
make sync SOURCE=lixinger ENDPOINT=industry_bundle

# 多个 bundle 或原子 task 可混合传入；展开后仍逐个任务独立执行
make sync SOURCE=lixinger ENDPOINT=market_bundle,macro_bundle
```

可用 LiXinger bundle：`market_bundle`、`industry_bundle`、`company_bundle`、`macro_bundle`、`index_bundle`。bundle 仅是调度输入，不合并数据集、水位或失败状态。

## 3. 全库物理存储主审计 CLI (Master Audit CLI)

基于 Polars 物理扫描全库全部 Parquet 文件，输出全表覆盖标的数、最小/最大交易日与完备度诊断：

```bash
# 通过 Makefile 快捷执行
make master-audit

# 或直接运行 Python 模块
uv run python -m stock.data.audit.master_audit
```

---

## 3. 全局数据源探测工具 (Global Data Probe CLI)

用于快速检测各大数据源（TuShare, yfinance, FRED, 理杏仁）的连通性、响应时延与 Schema 契约状态。

```bash
# 通过 Makefile 快捷执行
make probe

# 或直接运行 Python 模块
uv run python -m stock.data.probe
```

---

## 3. 离线数据质量审计工具 (Offline Data Validator CLI)

用于对本地 DuckDB 归档数据执行完整性与准确性规则校验（如：空值检查、主键重复、物理逻辑错误、断点检测等）。

```bash
# 默认审计日线数据 (daily)
make validate

# 指定审计其他接口 (通过 Makefile)
make validate ENDPOINT=daily_basic

# 完整参数调用
uv run python -m stock.data.validator --endpoint daily
```

---

## 4. 主示范程序 CLI

运行 YAML 策略驱动的主流程测试：

```bash
# 执行 main 程序
make run

# 或直接运行 Python 模块
uv run python -m stock.main
```

---

## 5. 代码质量与环境检查 CLI

在提交代码或发布前，运行全量代码规范与单测检查：

```bash
# 全量检查 (代码格式化 + Lint 检查 + Mypy 严格类型检查 + Pytest 测试)
make check

# 单独运行模块检查
make format   # Ruff 格式化
make lint     # Ruff 静态规则 + Mypy 检查
make test     # Pytest 全量测试与覆盖率统计
```
