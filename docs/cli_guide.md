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

---

## 2. 主示范程序 CLI

运行 YAML 策略驱动的主流程测试：

```bash
# 执行 main 程序
make run

# 或直接运行 Python 模块
uv run python -m stock.main
```

---

## 3. 代码质量与环境检查 CLI

在提交代码或发布前，运行全量代码规范与单测检查：

```bash
# 全量检查 (代码格式化 + Lint 检查 + Mypy 严格类型检查 + Pytest 测试)
make check

# 单独运行模块检查
make format   # Ruff 格式化
make lint     # Ruff 静态规则 + Mypy 检查
make test     # Pytest 全量测试与覆盖率统计
```
