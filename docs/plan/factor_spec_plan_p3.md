# 兼容重导出门面收敛实施计划（P3）

> 状态：已完成（`df9903f` 迁移、`df3dd1d` 删除）。
> 前置：P0+P1（`82f5db1`）、P2（`b1fe26d`）已完成并提交。
> 范围：`src/stock_analytics/pipelines/market_temperature/` 与 `pipelines/industry_structure/` 下的**共享事实兼容门面**（34 个纯重导出文件）及其调用方迁移；不触碰真实业务编排模块、`report_consistency.py`、`stock_screen/rules.py`、`catalog_compat.py`、`src/stock/`。
> 依据：全部对照源码、消费方 grep 与边界门禁核实现状；架构规则以 [`../architecture/analytics-boundaries.md`](../architecture/analytics-boundaries.md) 为准。

## 0. 背景与目标

早前的一次架构迁移（见 `docs/architecture/analytics-boundaries.md` "大管线拆分约束"）把市场温度与行业结构的**共享事实计算**从 `pipelines/<domain>/` 下沉到 `marts/shared/<domain>/`，原 `pipelines.<domain>` 下的同名模块只保留**兼容重导出**（facade）以兼容存量调用方。约束原文："实现文件可以保留兼容导出，但不作为新的外部依赖入口。拆分大文件时应优先保留这些兼容门面，再逐步迁移调用方。"

P3 目标：**收尾这次迁移**——把剩余调用方从旧门面路径迁到新实现路径，然后删除兼容门面，收敛为单一导入路径。这是债务清理，不改变任何事实 Schema、metric ID、score key 与日期截断规则（门面是纯重导出，删除门面等价于把所有 `pipelines.<domain>.<mod>` 引用改写为 `marts.shared.<domain>.<mod>`，行为零变化）。

**与 P1/P2 无关**：P1/P2 刻意不改任何消费方（D1 不改存量 ID）；P3 的"消费方"是更早那场 market_temperature/industry_structure 拆分的遗留引用。

## 1. 现状核对（源码事实）

### 1.1 门面清单与目标实现位置

门面模块 = docstring 为"…兼容门面"、正文仅 `from marts.shared.<domain>.<mod> import *` + `__getattr__` 转发的纯重导出文件。全部核对：`pipelines/market_temperature/` 20 个 + `pipelines/industry_structure/` 14 个 = **34 个**。

| 域 | 门面模块（20/14） | 目标实现位置 |
| :--- | :--- | :--- |
| market_temperature | `amount_concentration, cache, derived, derived_external, derived_fundamental, derived_helpers, derived_macro, derived_options, derived_sentiment, derived_settlement_iv, domain_mart_facts, external_risk_facts, fact_watermarks, facts, facts_mart, facts_schema, metric_facts, metric_windows, optional_facts, short_term` | `marts/shared/market_temperature/<同名单>.py`（19 个）；**`cache` 无对应物**——它是对 `features/dataset_cache.py` 的 `CachedCatalog/DatasetFrameCache` 纯重导出 |
| industry_structure | `classifier, industry_mapping, panel, panel_aggregations, panel_batch, panel_batch_inputs, panel_fundamental, panel_metrics, panel_metrics_batch, panel_moneyflow, panel_normalization, panel_schema, panel_sources, pb_roe` | `marts/shared/industry_structure/<同名单>.py`（14 个均有） |

注：`pipelines/industry_structure/fact_watermarks.py` 与 `facts.py` 是**真实业务模块**（含逻辑），不在门面清单内——但它们导入了 `market_temperature.cache` 门面，属于待迁消费方。

### 1.2 消费方清单（全仓 grep，含相对导入复核：无相对导入引用门面）

**src 内 6 处**（生产代码，必须迁移）：

| 消费方 | 门面引用 |
| :--- | :--- |
| `pipelines/market_temperature/pipeline.py` | `market_temperature.facts`、`market_temperature.cache` |
| `pipelines/industry_structure/pipeline.py` | `industry_structure.panel`、`market_temperature.cache` |
| `pipelines/industry_structure/scoring.py` | `industry_structure.panel` |
| `pipelines/industry_structure/facts.py` | `market_temperature.cache` |
| `pipelines/industry_structure/fact_watermarks.py` | `market_temperature.cache` |
| `pipelines/multi_date.py` | `market_temperature.cache`、`market_temperature.facts_mart` |

**tests 内约 15 个文件**：`metrics/test_datasets.py`、`marts/test_analytics_marts.py`（cache）；`pipelines/market_temperature/` 下 `test_cache/test_facts/test_scoring/test_templates/test_derived/test_settlement_iv/test_domain_mart_facts/test_fact_watermarks/test_facts_mart/test_facts_mart_contract`；`pipelines/industry_structure/` 下 `test_classifier_and_pb_roe/test_panel/test_panel_sources/test_panel_metrics`。

**零消费方门面**（纯删除，无需迁移）：market_temperature 11 个（`amount_concentration, derived_external, derived_fundamental, derived_helpers, derived_macro, derived_sentiment, facts_schema, metric_facts, metric_windows, optional_facts, short_term`）；industry_structure 8 个（`panel_aggregations, panel_batch, panel_batch_inputs, panel_fundamental, panel_metrics, panel_moneyflow, panel_normalization, panel_schema`）。

### 1.3 边界门禁现状（`scripts/lint_analytics_boundaries.py`）

- `LAYER_FORBIDDEN["marts"] = {"pipelines", "realtime"}`：`marts/shared/*` 不得反向导入 `pipelines`（lint 当前全绿，保证目标实现不依赖旧门面）；
- `pipelines → marts` 方向**不受限**（pipeline 不是被检查的源层）：迁移后真实模块直接导入 `marts.shared.*` 不触发任何违规；
- 外部消费者（`stock_cli`/`stock_strategy`）只允许 2-dot `pipelines.<domain>` 包入口或 PUBLIC_ROOTS：已核实 stock_cli 只用 `pipelines.market_temperature` / `pipelines.report_consistency` 两个 2-dot **包级/单文件入口**，均不指向待删门面，删除不受影响；
- 预期删除门面后**边界 lint 零改动**（删除只减少文件；`__all__` 导出检查不受影响）。

### 1.4 范围外"门面"（刻意保留，本轮不动）

| 文件 | 性质 | 保留理由 |
| :--- | :--- | :--- |
| `pipelines/report_consistency.py` | 单文件 2-dot 门面 | 是 `stock_cli` 唯一合法外部入口（`stock_cli/report_consistency.py:11`），删除会破坏边界白名单；不属于 marts 下沉迁移 |
| `pipelines/stock_screen/rules.py` | fundamental_rules 纯函数门面 | 属于 stock_screen 内部组织，非 marts 下沉 |
| `catalog_compat.py` | DataCatalog 兼容加载器门面 | 刻意保留的稳定兼容层 |
| `src/stock/` | 全库向后兼容门面包 | 仓库既有设计（`domain-responsibilities.md:31`） |

## 2. 核心决策点（待拍板，括号内为推荐默认）

| # | 决策 | 推荐默认 | 影响 |
| :-: | :--- | :--- | :--- |
| D1 | 迁移后的规范导入路径 | **`stock_analytics.marts.shared.<domain>.<module>`**（cache 例外 → `stock_analytics.features.dataset_cache`） | 与实现位置一一对应、内部消费者（pipelines/tests）lint 清洁；不对外部消费者暴露（外部只用 2-dot 包入口，不受影响） |
| D2 | 删除节奏 | **分两步提交**：① 迁移消费方（门面保留、双路径并存、全绿）② 删除 34 个门面 + grep 无遗留 | 每个 commit 独立可验证、可回滚；避免"迁移与删除"纠缠在一个大 commit |
| D3 | 零消费方门面处理 | **同批直接删除**（11+8 个），无需迁移 | 已 grep 确认无任何 import 引用；删除前在验收中再跑一次全仓 grep 兜底 |
| D4 | 部门面删除后的 import 规范 | **在 `analytics-boundaries.md` 补一句"共享事实一律从 `marts/shared/<domain>` 导入，`pipelines.<domain>` 下不再保留同门面"** | 把"门面是过渡品"固化为显式规则，防回潮 |

## 3. 实施任务

- **P3-1 迁移 src 消费方**（6 处，机械替换路径）：
  - `market_temperature/pipeline.py`：`market_temperature.facts` → `marts.shared.market_temperature.facts`；`market_temperature.cache` → `features.dataset_cache`；
  - `industry_structure/pipeline.py`：`industry_structure.panel` → `marts.shared.industry_structure.panel`；`market_temperature.cache` → `features.dataset_cache`；
  - `industry_structure/scoring.py`：`industry_structure.panel` → `marts.shared.industry_structure.panel`；
  - `industry_structure/facts.py`、`industry_structure/fact_watermarks.py`：`market_temperature.cache` → `features.dataset_cache`；
  - `multi_date.py`：`market_temperature.cache` → `features.dataset_cache`；`market_temperature.facts_mart` → `marts.shared.market_temperature.facts_mart`。
- **P3-2 迁移 tests 消费方**（约 15 个文件，同上映射）；迁移后定向测试全绿（此时门面仍在，双路径并存）。
- **P3-3 删除门面**：删除 34 个文件；全仓 grep `pipelines\.(market_temperature|industry_structure)\.(门面模块)\b` 与 `pipelines.market_temperature.cache` 等确认零遗留；跑边界 lint 确认零改动。
- **P3-4 文档**：`analytics-boundaries.md` 补 D4 规则；本计划文末补实施记录与验收勾选。
- **提交**（D2）：`refactor(analytics): 迁移 marts/pipelines 兼容门面调用方` → `refactor(analytics): 删除 market_temperature/industry_structure 兼容门面（P3 收尾）`。

## 4. 测试与门禁

- 定向：`make test TEST_PATH=tests/unit/stock_analytics/pipelines`（含 market_temperature/industry_structure 全部测试）；再跑 `tests/unit/stock_analytics/marts`、`tests/unit/stock_analytics/metrics`（cache 迁移影响 `test_datasets.py`）与 `tests/unit/stock_analytics` 全量。
- 静态：`make lint`（ruff / mypy / 类规模 / 三个边界检查，重点确认 lint_analytics_boundaries 不新增违规）。
- 全仓兜底：grep 门面模块名无 import 遗留。

## 5. 验收标准

- [x] `src` 与 `tests` 中不再出现任何 `pipelines.market_temperature.<门面>` / `pipelines.industry_structure.<门面>` 导入（grep 零命中）。
- [x] 34 个兼容门面文件全部删除；`pipelines/market_temperature/` 与 `pipelines/industry_structure/` 仅剩真实业务模块。
- [x] `marts/shared/<domain>` 路径成为共享事实唯一导入源；`cache` 统一走 `features.dataset_cache`。
- [x] `tests/unit/stock_analytics` 全绿；`make lint` 全绿且 `lint_analytics_boundaries.py` 零改动。
- [x] `stock_cli`/`stock_strategy` 外部消费者零改动（2-dot 包入口不受影响）；`src/stock/`、`catalog_compat.py`、`report_consistency.py`、`stock_screen/rules.py` 原样保留。
- [x] 无任何事实 Schema / metric ID / score key / 日期截断规则行为变化（门面为纯重导出，行为等价）。

## 6. 风险与不做什么

- **风险 1 漏迁引用**：迁移 commit 后门面仍在、测试全绿，不代表后续删除安全——用 P3-3 的全仓 grep 兜底；若 grep 发现遗漏则先补迁移再删（fail-closed）。
- **风险 2 lint 意外违规**：若删除后 `lint_analytics_boundaries` 报新违规（例如某真实模块仍经包级 `__init__` 依赖门面），先修正导入路径再继续，不绕过 lint。
- **风险 3 行为漂移误判**：门面是 `import *` + `__getattr__` 纯转发，与 `marts/shared` 目标 1:1；迁移不改变任何运行时对象身份。
- **不做**：不删 `report_consistency.py` / `report_consistency_checks.py` / `stock_screen/rules.py` / `catalog_compat.py` / `src/stock/`；不重构 `marts/shared` 内部实现；不触碰 `pipelines/market_temperature/{pipeline,snapshot,history,context,scoring,score_components,freshness,metric_temperature,artifacts,...}` 等真实编排模块的逻辑；不新增依赖；不改数据 Schema 与产物契约。

## 7. 后续可选（不在本轮）

- `report_consistency.py` 单文件门面收口（需先给 stock_cli 设计合法迁移入口，触碰边界白名单，单独排期）。
- `stock_screen/rules.py` 门面收口（内部重构，与 marts 迁移无关）。
- P4：因子评估闭环接线；单位枚举合并下沉 `stock_core`。

## 8. 实施记录

- `df9903f` `refactor(analytics): 迁移 marts/pipelines 兼容门面调用方`：迁移 6 个 src 消费方 + 16 个 test 消费方（共 22 文件），门面保留、双路径并存；`ruff --fix` 修正 `multi_date.py` 导入排序；全量 `tests/unit/stock_analytics` 585 通过，`make lint` 通过。
- `df3dd1d` `refactor(analytics): 删除 market_temperature/industry_structure 兼容门面（P3 收尾）`：删除 34 个门面文件（MT 20 + IS 14）；删除前全仓 grep 门面路径零遗留（仅命中真实模块 `industry_structure.facts/fact_watermarks`，保留）；删除后 `make lint` 通过、`tests/unit/stock_analytics` 全绿。
- `analytics-boundaries.md` 已按 D4 更新：共享事实一律从 `marts/shared/<domain>` 导入，`pipelines.<domain>` 不再保留同名兼容门面。
