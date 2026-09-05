# 注册新采集任务标准流水线 (Endpoint Registration Checklist)

当系统中需要引入新接口（如新宏观指标、期货行情、公司财务新表等）时，必须严格遵守以下 **步骤 0 查验探测 + 步骤 1~6 注册流水线**，保障 SSOT 路由、真实 Schema 与 2-Tier ETL 的确定性。

---

## 步骤 0：官方文档查验与真实响应单步探测 (Ground Truth First)

> [!CAUTION]
> **严禁凭大模型记忆猜测 Schema**！字段名、主键组合、日期字段名、空值表现形式以及数值单位（如万元/元/手/百分比）**必须有官方文档依据或真实 API 响应佐证**。

### 1. 官方文档与专用 Skill 查询表
在定义接口前，优先查阅对应官方文档或调用项目内专属技能：

| 数据源 (`data_source`) | 推荐查询方式 / 技能 | 官方接口文档入口 | 关键核验要素 |
| :--- | :--- | :--- | :--- |
| **`tushare`** | 读取技能 [`.agents/skills/tushare-data/SKILL.md`](../../tushare-data/SKILL.md) | [TuShare 官方数据字典](https://tushare.pro/document/2) | 接口权限积分、输入参数、输出字段名、金额单位（万元/千元） |
| **`lixinger`** | 读取技能 [`.agents/skills/lixinger-open-skill/SKILL.md`](../../lixinger-open-skill/SKILL.md) | [理杏仁开放平台文档](https://open.lixinger.com/api/doc) | URL 路径、请求体 JSON 格式、时间跨度限制（$\le 10$年） |
| **`industry`** | 查阅 `config/data_sources/*_registry.yaml` | 国家统计局/海关总署/郑商所/大商所/Mysteel/InfoLink | 原始物理量保真、发布时间窗口守卫、RAW/Curated 分层 |
| **`yfinance`** | 使用 GrokSearch 检索 yfinance 对应属性 | [yfinance 文档](https://ranaroussi.github.io/yfinance/) | Ticker 属性名、列名大小写、时区与复权规则 |
| **`fred`** | 检索 FRED Series ID | [FRED API 文档](https://fred.stlouisfed.org/docs/api/fred/) | `series_id`、发布频率（日/月/季）、单位（Percent/Index） |
| **`alphavantage`** | 检索 Alpha Vantage API Function | [Alpha Vantage 文档](https://www.alphavantage.co/documentation/) | `function` 名、免费限频（5次/分）、JSON 响应顶层 Key |

---

### 2. 真实响应单步探测（零猜测实操）
在正式编写注册代码前，运行轻量单行 Python 探测命令，实际抓取 1 条样本数据打印字段 Schema 与真实数值：

#### ① TuShare 真实响应探测
```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -c '
from stock_data.core.factory import get_shared_fetcher
client = get_shared_fetcher("tushare").client
# 调用待注册的上游 API (例如 moneyflow 或 daily_basic)
df = client.query("<api_name>", ts_code="000001.SZ", limit=1)
print("=== 真实字段清单 ===", df.columns)
print("=== 样本数据样例 ===", df.head(1).to_dicts())
'
```

#### ② 理杏仁 真实响应探测
```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -c '
from stock_data.core.factory import get_shared_fetcher
client = get_shared_fetcher("lixinger").client
# 发送原始 POST 请求
res = client._post("<api_endpoint_url>", {"stockCodes": ["600519"], "date": "2026-08-14"})
print("=== 响应 JSON Keys ===", res.keys() if isinstance(res, dict) else type(res))
print("=== 样本数据样例 ===", str(res)[:300])
'
```

#### ③ Yahoo Finance / FRED 真实响应探测
```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -c '
from stock_data.core.factory import get_shared_fetcher
fetcher = get_shared_fetcher("yfinance") # 或 "fred"
# 执行探测
df = fetcher.fetch_daily_bars(["AAPL"], start_date=None, end_date=None)
print("=== 真实字段清单 ===", df.columns)
'
```

---

## 2. 注册 6 步核心流水线

### 步骤 1：Provider 接口元数据定义
根据步骤 0 获得的真实字段清单，在对应 Provider 目录（如 `src/stock_data/fetcher/<provider>/endpoints/` 或 `registry.py`）中实例化 `EndpointMeta`：
* 定义上游身份与接口契约：`api_name` / `series_id`、`primary_keys`、`date_columns`、`required_columns`、`units`、`update_time`、`update_delay_days`、`rate_limit_per_min`；
* 普通端点的调度事实也优先写在 Provider 元数据：`frequency`、`fetch_mode`、`partitioned`、`is_single_sync`、`dataset`、`required_pool`、`query_mode`；
* `task_derivation.py` 会从 Provider 元数据自动推导 `TaskSpec`，不要再新增中心任务名白名单。

### 步骤 2：质量与单位 Profile 绑定 (RAW -> Curated 转换)
* 在 Provider 的 `_PROFILES` 字典中为新端点指定必需列、单位映射（如 `CNY100m`、`percent`）和质检 Profile；
* 凡存在上游非标准单位的数值字段（如万元、百万元、千元、手），**必须在 [`src/stock_data/pipeline/normalizer/unit_normalizer.py`](../../../../src/stock_data/pipeline/normalizer/unit_normalizer.py) 中显式声明倍率规则**；
* **严禁将倍率修正留给下游分析层**（分析层只做无倍率统计）。

### 步骤 3：项目任务名与特殊契约登记
按 [`docs/architecture/task-management.md`](../../../../docs/architecture/task-management.md) 的落点选择修改位置，不要把新逻辑写入 `task_registry.py`：

| 场景 | 修改位置 |
| :--- | :--- |
| 任务名与上游 API 名一致，且 Provider 元数据已足够推导 | 只改 Provider registry / endpoints |
| 公开项目短任务名需要映射到不同上游 API | 对应 `*_manual_tasks.py` |
| 垂直产业任务 | `industry_*_task_specs.py`，任务包在 `industry_bundle_specs.py` |
| 新增正式任务包 | 对应 `*_bundle_specs.py` |
| 兼容历史任务名或任务包名 | `task_aliases.py` / `task_bundle_aliases.py` |

手工任务只在确实需要短任务名、跨 API 路由或特殊调度契约时登记：
```python
("tushare", "new_task_name"): make_spec(
    "new_task_name",        # 公开 CLI 项目任务名
    "tushare",              # 数据源
    "new_api_name",         # 上游源 API 真实名称
    "new_dataset_name",     # 落盘数据集目录名
    "generic",              # quality_profile
    fetch_mode="per_day",
    partitioned=True,
    is_single_sync=False,
    required_pool=None,
),
```

### 步骤 4：观察池与回填规划适配
默认先通过 `TaskSpec.fetch_mode`、`required_pool`、`query_mode` 和 `date_columns` 驱动已有 Planner，不要为每个新接口改调度代码：
* 若属于 `per_symbol` 任务，确认是否复用 [`config/universe/watchlist.yaml`](../../../../config/universe/watchlist.yaml) 或 Provider 默认股票/基金池；
* 确认是否需要对齐标的上市基准日（`base_date`）或常量起始日截断（[`src/stock_data/core/constants.py`](../../../../src/stock_data/core/constants.py)）；
* 只有新增调度维度、标的池类型或报告期推进语义时，才修改 `src/stock_data/pipeline/planner.py` / `sync_planner.py`。

### 步骤 5：任务注册健康检查
注册或调整任务后先运行只读架构自检，确认任务包、别名、公开目录和 `TaskSpec` 没有悬空引用或旧入口回流：

```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.task_health --provider <source>
```

### 步骤 6：自动化门禁与重放验证
1. 运行任务注册与核心解析单测：`UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run pytest tests/unit/stock_data/core/test_task_health.py tests/unit/stock_data/core/test_task_registry.py --no-cov`；
2. 运行受影响 Fetcher / Pipeline 单测：`UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run pytest tests/unit/stock_data/fetcher/ -q --no-cov`；
3. 试运行小区间回填：`make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=<source> ENDPOINT=<task_name>`；
4. 从 RAW 重放验证 Curated：核验主键唯一性、行数、日期范围、字段非空率与数值单位。
