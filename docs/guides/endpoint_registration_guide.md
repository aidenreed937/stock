# 数据接口注册完整开发规范与 Checklist

为了避免在新增数据接口（TuShare、理杏仁、yfinance、FRED 等）时发生配置遗漏或参数错误，系统确立了标准的 **5 步注册流水线**。任何新端点的接入必须按顺序完整覆盖以下 5 个模块。

---

## 5 步注册标准 Checklist

```
[ ] 步骤 1: Fetcher 接口元数据定义 (EndpointMeta)
[ ] 步骤 2: 质量与单位 Profile 绑定 (Registry Profiles)
[ ] 步骤 3: 任务路由与分区分流 (TaskRegistry)
[ ] 步骤 4: 调度规划器策略归类 (BackfillPlanner)
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
  1. **标的遍历集合 (`PER_SYMBOL_DATASETS`)**：如果该接口需要按股票代码逐一回填全历史（如财报、预告），必须加入此集合。
  2. **免分桶单表集合 (`non_part_datasets`)**：如果是宏观单表、利率序列、指数日线等无需按年月深度分区的表，加入此集合，系统将统一落盘为单个 `data.parquet`。
  3. **自定义任务与别名 (`_CUSTOM_TASKS` / `_ALIASES`)**：确保 CLI 传入的任务短名称能正确路由至底层 API。

---

## 步骤 4：调度规划器策略归类 (`BackfillPlanner`)

- **文件路径**：[`src/stock/data/planner.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/planner.py)
- **规则**：
  1. **单表/宏观同步集合 (`MARKET_SINGLE_SYNC_ENDPOINTS`)**：若新端点属于全市场单次同步（无需遍历标的池），必须加入此集合。
  2. **A 股本地股票池集合 (`TUSHARE_STOCK_POOL_ENDPOINTS`)**：若新端点需要以本地 `stock_basic` 作为标的池依次拉取，加入此集合。

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
