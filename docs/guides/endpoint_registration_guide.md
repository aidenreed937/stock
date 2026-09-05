# 数据接口注册开发规范与 Checklist

为了避免新增数据接口（TuShare、理杏仁、yfinance、FRED、Alpha Vantage、Industry 等）时发生配置遗漏或参数错误，当前统一执行 **步骤 0 查验探测 + 步骤 1~6 注册流水线**。

详细操作以 [data-pipeline 注册流水线](../../.agents/skills/data-pipeline/references/01_endpoint_registration.md) 和 [任务管理架构](../architecture/task-management.md) 为准；本文只保留仓库级引用入口和稳定检查项。

---

## 注册标准 Checklist

```text
[ ] 步骤 0: 官方文档查验与真实响应单步探测
[ ] 步骤 1: Provider 接口元数据定义
[ ] 步骤 2: 质量与单位 Profile 绑定
[ ] 步骤 3: 项目任务名与特殊契约登记
[ ] 步骤 4: 观察池与回填规划适配
[ ] 步骤 5: 任务注册健康检查
[ ] 步骤 6: 自动化门禁与重放验证
```

---

## 步骤 0：官方文档查验与真实响应探测

字段名、主键组合、日期字段名、空值表现形式以及数值单位必须来自官方文档或真实 API 响应，不得凭记忆猜测。

| 数据源 | 推荐查询方式 | 官方接口文档入口 |
| :--- | :--- | :--- |
| `tushare` | 读取 [tushare-data skill](../../.agents/skills/tushare-data/SKILL.md) | [TuShare 官方数据字典](https://tushare.pro/document/2) |
| `lixinger` | 读取 [lixinger-open-skill](../../.agents/skills/lixinger-open-skill/SKILL.md) | [理杏仁开放平台文档](https://open.lixinger.com/api/doc) |
| `industry` | 查阅 `config/data_sources/*_registry.yaml` | 国家统计局、海关总署、交易所、Mysteel、InfoLink 等源头 |
| `yfinance` | 查阅 yfinance 当前文档或源码 | [yfinance 文档](https://ranaroussi.github.io/yfinance/) |
| `fred` | 查阅 FRED Series ID | [FRED API 文档](https://fred.stlouisfed.org/docs/api/fred/) |
| `alphavantage` | 查阅 Alpha Vantage function | [Alpha Vantage 文档](https://www.alphavantage.co/documentation/) |

真实响应探测应使用项目环境运行，并只抓取小样本：

```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -c '
from stock_data.core.factory import get_shared_fetcher
fetcher = get_shared_fetcher("<source>")
# 按待注册接口执行 1 条样本请求，打印字段、主键候选和单位样例
'
```

---

## 步骤 1：Provider 接口元数据定义

普通端点优先在对应 Provider 的 `registry.py` 或 `endpoints/` 元数据中写足接口事实和调度事实：

- 上游身份与接口契约：`api_name` / `series_id`、`primary_keys`、`date_columns`、`required_columns`、`units`、`update_time`、`update_delay_days`、`rate_limit_per_min`；
- 调度与存储契约：`frequency`、`fetch_mode`、`partitioned`、`is_single_sync`、`dataset`、`required_pool`、`query_mode`；
- `task_derivation.py` 会从 Provider 元数据推导 `TaskSpec`，不要新增中心任务名白名单。

---

## 步骤 2：质量与单位 Profile 绑定

- 在 Provider 的 Profile 字典中为新端点声明必需列、单位映射和质检 Profile；
- 对存在源端非标准单位的数值字段，必须在 [UnitNormalizer](../../src/stock_data/pipeline/normalizer/unit_normalizer.py) 显式声明 RAW -> Curated 倍率规则；
- 单位处理遵循 **RAW 保真、Curated 标准单位、分析层无倍率**：RAW 不改原值，Curated 统一为元、股/份、强类型日期和标准 metadata，分析层不得按数据源字段补乘或补除倍率。

常见单位转换位置：

| 数据集 | 源端单位 | Curated 标准单位 | 处理位置 |
| :--- | :--- | :--- | :--- |
| `stock_daily_bar.amount` | TuShare 千元 | 元 | `UnitNormalizer` |
| `daily_basic.total_mv/circ_mv` | TuShare 万元 | 元 | `UnitNormalizer` |
| `moneyflow` 金额字段 | TuShare 万元 | 元 | `UnitNormalizer` |
| `moneyflow_hsgt` 金额字段 | TuShare 百万元 | 元 | `UnitNormalizer` |

---

## 步骤 3：项目任务名与特殊契约登记

按 [任务管理架构](../architecture/task-management.md) 选择落点。`task_registry.py` 只保留旧导入兼容，新增业务逻辑不得写回兼容门面。

| 场景 | 修改位置 |
| :--- | :--- |
| 任务名与上游 API 名一致，且 Provider 元数据已足够推导 | Provider registry / endpoints |
| 公开项目短任务名需要映射到不同上游 API | 对应 `*_manual_tasks.py` |
| 垂直产业任务 | `industry_*_task_specs.py`，任务包在 `industry_bundle_specs.py` |
| 新增正式任务包 | 对应 `*_bundle_specs.py` |
| 兼容历史任务名或任务包名 | `task_aliases.py` / `task_bundle_aliases.py` |

CLI、文档和调度器统一使用项目任务名，例如 `index_daily_bar`；底层 API 名只作为 `TaskSpec.api_name` 的路由事实。

---

## 步骤 4：观察池与回填规划适配

默认先通过 `TaskSpec.fetch_mode`、`required_pool`、`query_mode` 和 `date_columns` 驱动已有 Planner：

- `per_symbol` 任务必须确认使用的标的池，并按需对齐 `config/universe/watchlist.yaml` 或 Provider 默认股票/基金池；
- 需要按标的回填的任务必须能读取 `base_date` 并截断无效历史区间；
- 只有新增调度维度、标的池类型或报告期推进语义时，才修改 `src/stock_data/pipeline/planner.py` / `sync_planner.py`。

---

## 步骤 5：任务注册健康检查

注册或调整任务后先运行只读架构自检，确认任务包、别名、公开目录和 `TaskSpec` 没有悬空引用或旧入口回流：

```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.task_health --provider <source>
```

---

## 步骤 6：自动化门禁与重放验证

按影响范围运行测试和小区间重放：

```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run pytest tests/unit/stock_data/core/test_task_health.py tests/unit/stock_data/core/test_task_registry.py --no-cov
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run pytest tests/unit/stock_data/fetcher/ -q --no-cov
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=<source> ENDPOINT=<task_name>
make backfill-accept ENDPOINT=<task_name> SOURCE=<source> START=YYYY-MM-DD END=YYYY-MM-DD
```

验收时至少确认：RAW/Curated 主键集合、日期范围、字段类型、关键字段非空率、metadata 和样例倍率。若已有 Curated 口径错误，应先修 registry 与 `UnitNormalizer`，再从 RAW 重放 Curated，最后验收，不要修改 RAW 原值，也不要在分析层补偿倍率。
