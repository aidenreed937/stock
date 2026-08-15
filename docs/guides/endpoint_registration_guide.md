# 数据接口注册完整开发规范与 Checklist

为了避免在新增数据接口（TuShare、理杏仁、yfinance、FRED 等）时发生配置遗漏或参数错误，系统确立了标准的 **5 步注册流水线**。任何新端点的接入必须按顺序完整覆盖以下 5 个模块。

---

## 5 步注册标准 Checklist

```
[ ] 步骤 1: Fetcher 接口元数据定义 (EndpointMeta)
[ ] 步骤 2: 质量与单位 Profile 绑定 (Registry Profiles)
[ ] 步骤 3: 项目任务路由契约 (TaskRegistry / TaskSpec)
[ ] 步骤 4: 观察池与单次同步策略 (BackfillPlanner)
[ ] 步骤 5: 自动化测试与 Lint 门禁验证 (pytest & make lint)
```

---

## 步骤 1：Fetcher 接口元数据定义

不同数据源的接口元数据在各自的 `fetcher` 目录下定义。

### TuShare
- **文件路径**：[`src/stock/data/fetcher/tushare/endpoints/finance.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/fetcher/tushare/endpoints/finance.py) 或 [`market.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/fetcher/tushare/endpoints/market.py)
- **规则**：
  - 实例化 `EndpointMeta`，明确 `primary_keys`、`date_columns` 和 `required_columns`。
  - ⚠️ **禁止项**：不要将 `fetch_mode` 作为参数传入 `EndpointMeta`（它属于任务调度层）。

```python
"shibor": EndpointMeta(
    api_name="shibor",
    description="Shibor 银行间同业拆放利率",
    frequency="daily",
    group="macro_data",
    primary_keys=["date"],
    date_columns=["date"],
    required_columns=["date"],
),
```

### 理杏仁 (LiXinger)
- **文件路径**：[`src/stock/data/fetcher/lixinger/registry.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/fetcher/lixinger/registry.py)
- **规则**：
  - 在 `LIXINGER_API_REGISTRY` 中注册完整 API 路径（如 `macro/national-debt`），并设置 `default_metrics` 与 `default_params`。
  - 在文件下方增加 CLI 短别名映射（如 `LIXINGER_API_REGISTRY["national_debt"] = ...`）。

---

## 步骤 2：质量与单位 Profile 绑定

- **文件路径**：[`src/stock/data/fetcher/tushare/registry.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/fetcher/tushare/registry.py)
- **规则**：
  - 在 `_TUSHARE_PROFILES` 字典中为新接口声明必需列、单位映射（如 `CNY100m`、`percent`、`point`）以及质检 Profile 类型（如 `bar`、`macro_monthly`、`macro_rate`、`financial_statement`）。

```python
"shibor": (["date"], {"on": "percent", "1w": "percent", "1m": "percent", "1y": "percent"}, "macro_rate"),
"fut_index_daily": (
    ["ts_code", "trade_date", "open", "high", "low", "close"],
    {"close": "point", "vol": "share", "amount": "CNY"},
    "bar",
),
```

---

## 步骤 3：任务路由与分区分流 (`TaskRegistry`)

- **文件路径**：[`src/stock/data/task_registry.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/task_registry.py)
- **规则**：
  1. **公开项目任务名 (`task_name`)**：CLI、文档和调度器统一使用项目任务名，例如 `index_daily_bar`；不要把上游 API 名（如 TuShare `index_daily`）直接写进操作示例。
  2. **底层 API 路由 (`api_name`)**：在 `TaskSpec` 中显式记录项目任务到上游 API 的映射，确保 `index_daily_bar -> index_daily` 这类解耦关系清晰可测。
  3. **落盘数据集名 (`dataset`)**：明确 RAW/Curated 的标准数据集目录名，通常与 `task_name` 一致。
  4. **调度与存储契约**：按接口真实行为设置 `fetch_mode`、`partitioned`、`is_single_sync` 和 `required_pool`。需要本地基础池的任务必须设置 `required_pool`，避免空池静默回填。
  5. **历史兼容别名 (`_ALIASES`)**：只用于兼容旧 API 名或外部路径；新增文档和 CLI 示例必须使用 `TaskSpec.task_name`。

---

## 步骤 4：观察池与单次同步策略 (`BackfillPlanner`)

- **文件路径**：[`src/stock/data/planner.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/planner.py)
- **规则**：
  1. **观察池路由**：确认 `_watchlist_symbols()` 能按数据源和资产类别解析正确标的池，例如 A 股股票、指数、基金、FRED 宏观序列或 yfinance 宏观资产。
  2. **单标的基准日**：需要按标的回填的任务必须能读取 `base_date` 并截断无效历史区间。
  3. **`per_symbol + is_single_sync` 展开策略**：若接口虽然是单文件落盘，但源端仍要求按标的请求，必须由 `_should_expand_single_sync()` 返回 `True`，拆成多个原子任务；真正的行业/宏观批量端点才保留空标的单任务。
  4. **增量同步一致性**：每日增量同样按单标的水位与 `base_date` 规划。新增端点后需要验证 `DailySyncEngine` 不会传空标的或把任务名误当 API 标的。

---

## 步骤 5：自动化测试与 Lint 门禁验证

每次注册完成后，必须依次执行以下门禁命令：

```bash
# 1. 运行数据模块单元测试 (确保无 TypeError 或路由解析失败)
uv run pytest tests/unit/data/ --no-cov

# 2. 运行项目全局代码规范与类型检查
make lint
```

通过以上 5 步即可保证新接口在采集、质检、存储与任务调度各环节的一致性与稳定性。
