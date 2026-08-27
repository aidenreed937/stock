# Factor Spec P4：因子评估闭环接线 + 单位枚举下沉 stock_core

> 状态：已完成（P4A `a457078`、P4B `4da1fe7`）。
> 前置：P0+P1（`82f5db1`）、P2（`b1fe26d`）、P3（`df9903f` + `df3dd1d` + `f9a102c`）已完成并提交。

## 1. 背景与目标

P0 计划第 8 节与 P2/P3 计划的"后续候选项"一致指向两件事：

1. **P4A 单位枚举合并下沉 `stock_core`**：`features/spec.py` 与 `metrics/spec.py` 各自定义了
   一套成员完全相同的单位枚举（`FeatureUnit` / `MetricUnit`，各 10 个成员、值一致），
   靠 docstring 互相"对齐"维持一致。下沉到最底层 `stock_core`，收敛为单一事实源，
   消除双枚举漂移风险，并让 `stock_data`、`stock_reporting`、`stock_strategy` 未来可复用。
2. **P4B 因子评估闭环接线（因子准入报告管线）**：`primitives/factor_evaluation.py` 与
   `primitives/factor_quantile.py`（共 458 行纯函数原语：Rank IC / ICIR / t 统计量 /
   IC 衰减 / 分层单调性 / 多空价差）已存在但**无任何管线调用**。P0 计划定位 P4 为
   "立检验"——用评估原语 + 已注册的 FactorSpec 元数据，产出"因子准入报告"，
   为远期"因子组合成策略"提供质量门槛（P0 计划 `factor_spec_plan.md:33`）。

长期链路（P0 计划 `:48`）：因子资产化（P1）→ 因子质量评估闭环（P4）→
`stock_strategy` 侧组合与回测。**本计划只做评估闭环，不做组合器**。

## 2. 范围

- **P4A**：删除 `FeatureUnit` / `MetricUnit` 两处定义，统一为 `stock_core` 单一枚举；
  消费方（src 153 处 + tests 7 处引用）通过 `import-as` 别名**零改动**延续 `FeatureUnit` /
  `MetricUnit` 名字。值、成员、语义零变化。
- **P4B**：新增 `pipelines/factor_research/` 因子准入报告管线：加载 `stock_daily_bar`
  历史面板 → `FactorEngine.compute_all_factors` → 前向收益 → IC/分位数评估 →
  准入判定 → artifact + manifest 落盘（`quant_brief` 模式）；挂载 `stock_cli` 命令。
- **不做**：不做 `stock_strategy` 组合器/回测；不改任何因子列名、FeatureSpec 注册内容与
  存量 ID；不新增数据源；不重构 `primitives/factor_evaluation.py` / `factor_quantile.py`
  现有算子；不动 `stock_core/contracts.py` 的字段级 `units: dict[str, str]` 映射。

## 3. 现状盘点（关键事实）

| 项 | 位置 | 事实 |
|---|---|---|
| 单位枚举定义 | `src/stock_analytics/features/spec.py:30` | `FeatureUnit(StrEnum)` 10 成员：CNY/SHARES/COUNT/RATIO/PERCENT/PERCENTILE/ZSCORE/SCORE_0_100/BOOLEAN/UNKNOWN |
| 单位枚举定义 | `src/stock_analytics/metrics/spec.py:40` | `MetricUnit(StrEnum)` 同 10 成员、值完全一致；docstring 自述"与 FeatureUnit 对齐" |
| 单位枚举消费方 | 全仓 | src 153 处引用（metrics 13 个 calculators、features spec/builtin_specs 等）+ tests 7 处 |
| 字段级单位映射 | `src/stock_core/contracts.py:88` 等 | `units: dict[str, str]` 自由字符串，描述"源字段单位"（quote_currency/shares/ratio…），语义与指标枚举不同 |
| 因子原语（无调用） | `primitives/factor_evaluation.py` | `add_forward_returns` / `rank_ic_series` / `ic_summary` / `ic_decay` / `cumulative_ic`，248 行，纯函数，fail-closed |
| 因子原语（无调用） | `primitives/factor_quantile.py` | `quantile_forward_returns` / `quantile_summary`，210 行，分层单调性 + 多空价差 |
| 因子计算引擎 | `features/factors.py:99` | `compute_all_factors` spec 驱动（12 步 `FACTOR_ENGINE_STEPS`），派生列 ⊆ 注册 spec 硬校验 |
| 因子元数据 | `features/builtin_factor_specs.py` | 37 个 `_factor_spec`：26 个宽表因子列 + 11 个 stock_screen 评分因子，含 unit/direction/version |
| 报告管线模板 | `pipelines/quant_brief/` | `pipeline.py`（RunResult dataclass + `run_quant_brief`）+ `artifacts.py` + manifest + latest |
| CLI 模式 | `src/stock_cli/quant_brief.py` 等 | 每管线一个 `stock_cli/<name>.py` 模块，`main.py` 注册子命令 |
| 评估输入数据 | `stock_daily_bar`（curated） | 仅有**未复权** `close`；全仓无 `close_adj` / `adj_close`（复权价缺口，见风险 1） |

## 4. 决策点

| 编号 | 决策点 | 默认执行 | 备选 |
|---|---|---|---|
| D1 | 统一枚举命名与位置 | `stock_core/units.py` 定义 `class Unit(StrEnum)`，10 成员原样平移 | `AnalyticsUnit`；位置 `stock_core/constants.py` |
| D2 | 兼容方式 | `features/spec.py` / `metrics/spec.py` 改 `from stock_core.units import Unit as FeatureUnit / MetricUnit`（消费方零改动） | 全量重命名 153 处引用为 `Unit`（改动面大、收益低，不推荐） |
| D3 | `contracts.py` 字段单位映射是否纳入 | **不纳入**：`units: dict[str, str]` 是"字段级单位"（可含 quote_currency 等复合串），与指标/特征单位枚举语义不同 | 改为枚举并校验值（扩大范围触碰 stock_data 层，本期不做） |
| D4 | 评估因子池 | 26 个宽表因子列中**可横截面排序**的子集：过滤 `unit ∈ {RATIO, PERCENT, PERCENTILE, ZSCORE, SCORE_0_100}` 且 `direction ≠ neutral`，由 spec 数据驱动 + config 白名单可覆盖；排除 CNY/SHARES 含量纲列（如 `atr_14d`） | 全部 26 列；仅 stock_screen 11 个评分因子 |
| D5 | 评估输入与价格口径 | 自包含现算：`stock_daily_bar` 历史面板 → `compute_all_factors`；前向收益用未复权 `close`，报告标注"未复权口径，除权日可能失真"并在报告中输出除权检测提示 | 阻塞等复权价数据（扩大范围到 stock_data，本期不做）；消费 stock_screen 已落盘宽表产物 |
| D6 | 评估参数与准入阈值 | `config/analytics/factor_research.yaml`：历史窗口默认 2 年、horizons `(1, 5, 20)`、分箱 5、门槛默认 ICIR ≥ 0.5 / t ≥ 2 / 多空年化 > 0；样本不足 fail-closed 输出缺失 | 阈值写死代码（不灵活，不推荐） |
| D7 | 产出形态 | markdown（人类可读）+ json（机器可读）+ manifest + latest，落 `data/analytics/factor_research/`（quant_brief 模式） | 仅内存返回 + 打印（无持久化，不推荐） |
| D8 | CLI | 本轮挂载 `stock-cli factor-research` 子命令（标准注册：`stock_cli/factor_research.py` + `main.py`） | 先库函数、CLI 单独排期 |

## 5. 任务分解

### P4A 单位枚举下沉（先做，纯重构、低风险小提交）

- **P4A-1** `src/stock_core/units.py`：新建 `Unit(StrEnum)`，10 成员原样平移（值不变）；
  `tests/unit/stock_core/test_units.py` 锁定成员全集与值。
- **P4A-2** `features/spec.py` 与 `metrics/spec.py`：删除本地枚举定义，改
  `from stock_core.units import Unit as FeatureUnit / MetricUnit`；`__all__` / re-export 保持
  `FeatureUnit` / `MetricUnit` 名字可见；全仓引用 160 处无需改动。
- **P4A-3** 验证：`grep -rn "class FeatureUnit\|class MetricUnit"` 仅命（若命中）兼容注释；
  定向测试（features/metrics）+ 全量 `tests/unit/stock_analytics` + `make lint`（边界检查确认
  stock_core 下沉不新增违规，且 metrics 不再依赖 features 单位定义）。
- **P4A-4** 文档：`docs/architecture/analytics-boundaries.md`（或 domain-responsibilities）
  补一句"指标/特征单位枚举唯一事实源 `stock_core.units.Unit`"。
- 提交：`refactor(analytics): 单位枚举合并下沉 stock_core（P4A）`

### P4B 因子评估闭环（后做，新增管线）

- **P4B-1** `config/analytics/factor_research.yaml` + 加载器（参照 `quant_brief` config 模式）：
  评估窗口、horizons、分箱数、准入阈值、因子池白名单（空 = 按 D4 规则由 spec 驱动）。
- **P4B-2** `pipelines/factor_research/pipeline.py`：`FactorResearchRunResult` + `run_factor_research`
  编排——数据可回溯性检查（窗口覆盖不足 fail-closed）→ `compute_all_factors` →
  `add_forward_returns` → `rank_ic_series` + `ic_summary` + `ic_decay` →
  `quantile_forward_returns` + `quantile_summary` → 准入判定（对照 config 阈值）→ 组装报告数据。
- **P4B-3** `pipelines/factor_research/artifacts.py`：RunPaths + `write_artifacts`
  （markdown 表：因子 × {IC/ICIR/t/衰减/分层单调性/多空价差/准入结论}；json 全量统计量；manifest + latest）。
- **P4B-4** 测试：mock 面板端到端（小样本手工可算的 IC/分层数字与原语单测对齐）；
  窗口覆盖不足报错、缺失 fail-closed、门槛判定边界、manifest 落盘。
- **P4B-5** `stock_cli/factor_research.py` + `main.py` 注册 `factor-research` 子命令；
  文档（管线说明 + 决策记录）与 `analytics-boundaries.md` 外部门面补充 2-dot 入口。
- 提交：`feat(analytics): 因子准入评估报告管线 factor_research（P4B）`

## 6. 验收标准

- [x] `stock_core.units.Unit` 为全仓唯一单位枚举定义；`features/spec.py` 与 `metrics/spec.py`
      无独立枚举定义，`FeatureUnit`/`MetricUnit` 名经别名继续可用。
- [x] 160 处既有引用零改动全绿；`tests/unit/stock_analytics` 全量通过；`make lint` 全绿，
      边界 lint 零新增违规（metrics→features 依赖门禁不因枚举下沉而松动）。
- [x] `run_factor_research` 对 mock 面板输出确定性报告；IC/ICIR/分层/多空数字与
      `primitives` 原语单测一致；准入判定阈值（D6 默认值）生效且样本不足 fail-closed。
- [x] 产物 markdown + json + manifest + latest 落盘 `data/analytics/factor_research/`；
      `factor-research` 子命令可运行（mock 数据路径）。
- [x] `stock_cli`/`stock_strategy` 既有消费方零改动；不改存量 ID / 因子列名 / spec 注册内容。

## 7. 风险与不做什么

- **风险 1 无复权价**：全仓无 `close_adj`，前向收益用未复权 `close`，除权日收益会失真。
  处置：报告标注口径 + 输出除权检测提示（大单日涨跌异常列提醒）；复权价列为后续数据项
  （`stock_data` 侧单独排期，不阻塞本期评估闭环）。
- **风险 2 历史水位不足**：2 年评估窗口依赖 `stock_daily_bar` 可回溯性；窗口覆盖不足时
  管线直接报错（fail-closed），不产出空报告；因子池中上市时间不足的标的在窗口前期自然缺失。
- **风险 3 因子覆盖稀疏**：新股/新列早期缺失由原语 fail-closed 处理（输出缺失不推断）。
- **风险 4 阈值主观性**：ICIR/t/多空门槛为初值，报告同时输出统计量供人工复核；
  本版是"报告门槛"（结论性标注），**不做自动拦截策略准入**。
- **风险 5 双枚举合并遗漏**：若某处引用依赖"两个枚举类型可互换"的隐式行为，合并为同一
  类型后反而更安全；删除前用 `grep` 确认无 `isinstance`/类型标注依赖原定义对象身份。
- **不做**：不新增复权价数据（另排）；不做 `stock_strategy` 组合器/回测；不重构评估原语；
  不改 `contracts.py` 字段单位映射；不自动注册/注销任何 FeatureSpec（direction 修正靠后续
  投研复核，P0 计划 D4）。

## 8. 后续候选项（不在本轮）

- 复权价数据项（`stock_data` 侧），消除前向收益口径风险。
- 组合器 + 回测接线到 `stock_strategy`（准入报告作为输入门槛）。
- 准入结论回流：评估通过 → FeatureSpec 版本升级 / direction 修正 / 进入策略候选池。
- stock_screen 11 个评分因子接入同一评估管线（D4 因子池扩展）。

## 9. 实施记录

- `a457078` `refactor(analytics): 单位枚举合并下沉 stock_core（P4A）`：
  `stock_core/units.py` 定义唯一 `Unit` 枚举（10 成员原样平移）；
  `features/spec.py` / `metrics/spec.py` 改 `from stock_core.units import Unit as FeatureUnit/MetricUnit`
  别名，160 处既有引用零改动；`tests/unit/stock_core/test_units.py` 锁定成员全集；
  `domain-responsibilities.md` 补充单位枚举归属说明。全量测试 + `make lint` 全绿。
- `4da1fe7` `feat(analytics): 因子准入评估报告管线 factor_research（P4B）`：
  新增 `pipelines/factor_research/`（pipeline / artifacts / report / config 四模块 +
  包面 `DEFAULT_CONFIG_PATH`）+ `config/analytics/factor_research.yaml` +
  `stock_cli/factor_research.py` + Makefile `factor-research` target + 17 个测试。
  数据装配：`stock_daily_bar` 必需（fail-closed），`daily_basic` / `moneyflow` 缺失时补
  null 列不阻塞；因子池按 D4 规则（无量纲 unit + direction ≠ neutral，白名单可覆盖）
  从 `FACTOR_ENGINE_SPECS` 推导；准入判定方向感知（positive/negative），
  样本不足（< min_ic_days）判 insufficient。mock 面板验证 + `make test` 1406 通过 +
  `make lint` 全绿。
- `analytics-boundaries.md` 无需白名单改动：`pipelines.factor_research` 为 2-dot 外部
  入口自动放行；`stock_cli` 经包面导入 `DEFAULT_CONFIG_PATH`（不触碰 3-dot 深度）。
