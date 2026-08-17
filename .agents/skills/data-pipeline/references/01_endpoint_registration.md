# 注册新数据接口标准流水线 (Endpoint Registration Checklist)

当系统中需要引入新接口（如新宏观指标、期货行情、公司财务新表等）时，必须严格遵守以下 5 步流水线，保障 SSOT 路由、单位归一与 2-Tier ETL 的完整性。

---

## 1. 注册 5 步核心流水线

### 步骤 1：Fetcher 接口元数据定义
在对应 Provider 目录（如 `src/stock_data/fetcher/<provider>/endpoints/` 或 `registry.py`）中实例化 `EndpointMeta`：
* 定义 `api_name`、`primary_keys`、`date_columns`、`required_columns`；
* **切勿在 Fetcher 层定义 `fetch_mode`**（调度属性属于上层 TaskRegistry）。

### 步骤 2：质量与单位 Profile 绑定 (RAW -> Curated 转换)
* 在 Provider 的 `_PROFILES` 字典中为新端点指定必需列、单位映射（如 `CNY100m`、`percent`）和质检 Profile；
* 凡存在上游非标准单位的数值字段（如万元、百万元、千元、手），**必须在 [`src/stock_data/pipeline/normalizer/unit_normalizer.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/pipeline/normalizer/unit_normalizer.py) 中显式声明倍率规则**；
* **严禁将倍率修正留给下游分析层**（分析层只做无倍率统计）。

### 步骤 3：任务路由与技术属性登记 (`TaskRegistry`)
在 [`src/stock_data/core/task_registry.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/core/task_registry.py) 中用 `TaskSpec` 登记：
```python
"new_task_name": TaskSpec(
    task_name="new_task_name",      # 公开 CLI 项目任务名
    provider="tushare",             # 数据源
    api_name="new_api_name",        # 上游源 API 真实名称
    dataset="new_dataset_name",     # 落盘数据集目录名
    frequency="daily",              # daily / monthly
    quality_profile="generic",      # bar / generic / macro
    partitioned=True,               # 是否按 year/month 物理分区
    fetch_mode="per_day",           # per_day (全市场按日) 或 per_symbol (按标的遍历)
    is_single_sync=False,           # 是否仅需同步一次基础信息表
    required_pool=None,             # "stock_basic" | "fund_basic" | None
),
```

### 步骤 4：观察池与回填规划适配 (`BackfillPlanner`)
在 [`src/stock_data/pipeline/planner.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/pipeline/planner.py) 中：
* 若属于 `per_symbol` 任务，确认是否需从 [`config/universe/watchlist.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/universe/watchlist.yaml) 展开；
* 确认是否需要对齐标的上市基准日（`base_date`）或常量起始日截断（[`src/stock_data/core/constants.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/core/constants.py)）。

### 步骤 5：自动化门禁与重放验证
1. 运行单测：`uv run pytest tests/unit/stock_data/fetcher/ -q --no-cov`；
2. 试运行回填：`make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=<source> ENDPOINT=<task_name>`；
3. 从 RAW 重放验证 Curated：核验主键唯一性、行数、日期范围、字段非空率与数值单位。
