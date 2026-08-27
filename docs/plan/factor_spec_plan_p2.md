# 因子引擎 Spec 驱动化实施计划（P2）

> 状态：已实施（决策点经确认后按推荐默认执行；见文末实施记录）。
> 前置：P0+P1 已完成并提交（`82f5db1`，因子资产化 + 单位/ID 收敛）。
> 范围：`src/stock_analytics/features` 及其单测；不触碰 `stock_data` / `stock_strategy` / `stock_reporting` 生产逻辑，不触碰 `stock_screen` 管线执行（其宽表生成不在 FactorEngine 范围）。
> 依据：全部对照 P1 落地后的源码与测试核实现状；外部规则以 [`../architecture/analytics-boundaries.md`](../architecture/analytics-boundaries.md) 为准。

## 0. 背景与目标

P1 建立了因子资产化地基：`FactorEngine` 的 26 个产出列 + `stock_screen` 的 10 个评分因子全部登记为 `FeatureSpec`，引擎尾部有 P1-2 列名硬校验（fail-closed）。但存在一个结构性缺陷（原计划"风险 2"）：

> **spec 是人工声明，可能跟不上算子改动**；注册与计算之间靠 P1-2 的"列名集合 ⊆ 注册集合"兜底，无法防止"算子改了参数/产出列但 spec 没同步"的漂移，也无法让"新增因子"脱离引擎代码。

P2 目标：

1. **消除声明与计算漂移**：因子计算由 spec（步骤表）驱动，而非硬编码 12 段调用；步骤表与列级 spec 之间做强一致校验，任一不同步即报错。
2. **新增因子不改引擎**：新因子 = 新增一条步骤 + 若干列 spec，`compute_all_factors` 代码零改动。
3. **行为兼容**：`compute_all_factors` 签名、26 个产出列、列顺序、`normalize`/`winsorize`/`standardize_zscore` 行为与 P1 完全一致；存量测试全部保持全绿。

术语沿用 P0/P1 计划：算子（ primitives，无状态函数）→ 指标（metrics，单实体时序）→ 因子（features 宽表列，`kind=FACTOR`）→ 策略。P2 只改"因子如何被调度计算"，不改变因子语义。

## 1. 现状核对（P1 落地后源码事实）

### 1.1 引擎现状

`FactorEngine.compute_all_factors`（`features/factors.py:122-186`）硬编码 12 段算子调用，产出 26 列：

| # | 算子调用（现硬编码） | 产出列（26） |
| :-: | :--- | :--- |
| 1 | `calculate_momentum(price_col=close)` | `mom_20d/60d/120d/250d` |
| 2 | `calculate_short_term_reversal(price_col=close)` | `reversal_5d` |
| 3 | `calculate_distance_to_high(price_col=close)` | `dist_to_high_250d` |
| 4 | `calculate_ema_spread(price_col=close)` | `ema_spread_12_26` |
| 5 | `calculate_realized_volatility(price_col=close)` | `realized_vol_20d/60d` |
| 6 | `calculate_atr(close_col=close)` | `atr_14d`、`atr_ratio_14d` |
| 7 | `calculate_bollinger_bandwidth(price_col=close)` | `bollinger_bandwidth_20d`、`bollinger_percent_b_20d` |
| 8 | `calculate_amihud_illiquidity(price_col=close)` | `amihud_illiq_20d` |
| 9 | `calculate_turnover_factors()` | `turnover_mean/std_5d/20d/60d` |
| 10 | `calculate_volume_surprise()` | `volume_surprise_5_20` |
| 11 | `calculate_main_moneyflow_factors()` | `main_inflow_ratio`、`_5d`、`_20d` |
| 12 | `calculate_rolling_percentile()` | `pe_ttm_percentile_1250d`、`pb_percentile_1250d` |

要点：

- 12 个算子全部已从 `stock_analytics.primitives` 导出（`primitives/__init__.py` `__all__`），无未导出的依赖。
- 每步调用均只依赖基础输入列（`_INPUT_BASE_COLUMNS`）或本步自产中间列（如 `main_inflow_ratio` 由 `calculate_main_moneyflow_factors` 内部自产），**步间无跨步数据依赖**，因此执行顺序 = 声明顺序。
- 引擎当前无业务调用点（全仓 grep 仅测试与文档引用），重构风险面小。
- 空表早退（`factors.py:139-140`）、派生列硬校验（`factors.py:162-164`）、normalize 分支（`factors.py:166-184`）均为需保留的既有行为。

### 1.2 spec 现状

- `FeatureSpec`（`features/spec.py:45-65`）已预留 `inputs: tuple[str, ...]` 与 `transform: str` 字段，P1 仅把 `inputs` 填为人类可读字符串（如 `("calculate_momentum(price_col=close, windows=(20,60,120,250))",)`），未做任何机器可执行语义。
- `FACTOR_ENGINE_SPECS`（`features/builtin_factor_specs.py:67-293`）：26 条列级 spec（kind=FACTOR、entity_type=STOCK、unit/direction/lookback_days/required_datasets/required_columns 已齐）。
- `FeatureRegistry.register_builtins()`（`features/registry.py:86-91`）注册 26 + 10 + MARKET specs。
- P1 的 `ensure_factor_columns_registered`（`factors.py:41-63`）仅做"产出列 ⊆ 注册列"单向校验。

### 1.3 缺口

1. 计算流程仍是硬编码，spec 只是旁路元数据 —— 新增/修改因子必须改 `factors.py` 正文。
2. 无"步骤 ↔ 列 spec"双集合双向一致性校验 —— 算子改产出列名但 spec 未同步时，只有 P1-2 的单向校验兜底，且只能发现"多算未登记"，不能发现"spec 声明了但引擎没算"。
3. `inputs` 字段承载的是描述性字符串，无机器可读的参数结构，无法直接驱动执行。

## 2. 核心决策点（待拍板，括号内为推荐默认）

| # | 决策 | 推荐默认 | 影响 |
| :-: | :--- | :--- | :--- |
| D1 | 步骤表规范放哪 | **新建 `features/factor_steps.py`**，列级 spec 留在 `builtin_factor_specs.py` | 元数据（列 spec）与执行计划（步骤表）分离，`registry.py` 零改动；若并入同文件则单文件膨胀且职责混杂 |
| D2 | 步骤参数承载方式 | **结构化 `FactorStep` dataclass**（`operator` 名 + `params: Mapping[str, object]` + `produces` 产出列），算子名经显式静态映射表解析 | 静态可校验、可序列化；不引入表达式解析/eval/动态 import |
| D3 | 步骤缺失输入列时行为 | **沿用现状 fail-open**：算子内部自行兜底（缺列返回原表），引擎不做全局输入列强制校验 | 零行为变化、零回归风险；fail-closed 需新增全局校验且改变现有容错语义 |
| D4 | 步骤执行顺序 | **声明顺序即执行顺序**，不做依赖拓扑解析 | 当前 12 步线性无跨步依赖，引入拓扑属于过度设计；文档声明"步骤表有序" |

若对任一默认有异议，开工前调整本表即可。以下设计均按推荐默认展开。

## 3. 设计

### 3.1 `FactorStep` 契约（`features/factor_steps.py` 新增）

```python
@dataclass(frozen=True, slots=True)
class FactorStep:
    step_id: str  # 如 "momentum"
    operator: str  # primitives 函数名，如 "calculate_momentum"
    params: Mapping[str, object]  # 传给算子的 kwargs（静态校验用，冻结）
    produces: tuple[str, ...]  # 本步产出的 1..N 个因子列名
```

约束（由 `validate_factor_engine_steps()` 静态校验，fail-closed）：

1. `operator` 必须存在于 `_FACTOR_OPERATORS` 显式映射表（12 个，与 `primitives.__all__` 对应）；
2. `produces` 非空、不含 `_INPUT_BASE_COLUMNS` 任意列、跨步骤全局不重复；
3. **步骤表 `produces` 并集 == `FACTOR_ENGINE_SPECS` 的 `feature_id` 集合**（双集合双向一致：既不允许"引擎算了但没 spec"，也不允许"spec 登记了但引擎没算"）；
4. 每个产出的列名必须在 `FeatureRegistry` 中登记为 `kind=FACTOR, entity_type=STOCK`（复用 P1 的 `ensure_factor_columns_registered` 逻辑）。

### 3.2 `FACTOR_ENGINE_STEPS`：12 步登记表（按 1.1 表逐行翻译）

每步 `params` 与现状 `factors.py` 的调用完全一致（含默认参数语义，不新增 `as_percentage=True` 之类改变量纲的参数）：

| step_id | operator | params（现状调用） | produces |
| --- | --- | --- | --- |
| momentum | calculate_momentum | `{"price_col": "close"}` | 4 |
| reversal | calculate_short_term_reversal | `{"price_col": "close"}` | 1 |
| dist_to_high | calculate_distance_to_high | `{"price_col": "close"}` | 1 |
| ema_spread | calculate_ema_spread | `{"price_col": "close"}` | 1 |
| realized_vol | calculate_realized_volatility | `{"price_col": "close"}` | 2 |
| atr | calculate_atr | `{"close_col": "close"}` | 2 |
| bollinger | calculate_bollinger_bandwidth | `{"price_col": "close"}` | 2 |
| amihud | calculate_amihud_illiquidity | `{"price_col": "close"}` | 1 |
| turnover | calculate_turnover_factors | `{}` | 6 |
| volume_surprise | calculate_volume_surprise | `{}` | 1 |
| moneyflow | calculate_main_moneyflow_factors | `{}` | 3 |
| percentile | calculate_rolling_percentile | `{}` | 2 |

注：`compute_all_factors` 现调用 `calculate_momentum(res, price_col=price_col)` 等传入了引擎参数 `price_col`，步骤表 params 中的 `"close"` 是引擎默认值的展开；实现时引擎把调用参数（`price_col`）注入步骤 params，保持 `price_col=` 入参可自定义的行为不变（详见 3.3）。

### 3.3 引擎改造（`features/factors.py`）

- 新增模块级显式映射 `_FACTOR_OPERATORS: dict[str, Callable[[pl.DataFrame], pl.DataFrame]]`，将 12 个算子名映射到 `primitives` 函数；**拒绝动态 import / eval**。
- `compute_all_factors` 主体替换为：

```python
res = df
for step in FACTOR_ENGINE_STEPS:
    injected = {**step.params}
    if "price_col" in injected and injected["price_col"] == "close":
        injected["price_col"] = price_col  # 跟随引擎入参（bollinger/atr 等等价列名按现状规则展开）
    res = _FACTOR_OPERATORS[step.operator](res, **injected)
```

- **保留不动**：`winsorize` / `standardize_zscore` / `normalize` 分支、空表早退、`_INPUT_BASE_COLUMNS`、派生列硬校验（`ensure_factor_columns_registered`）调用。
- 引擎读取模块级 `FACTOR_ENGINE_STEPS`（调用时查模块属性），便于测试 monkeypatch 注入临时步骤验证可扩展性。
- `spec.py` 零改动；`FeatureSpec.inputs` 字符串保留作为人类可读注释，不承载执行语义。

### 3.4 新增因子流程（P2 交付后的标准动作）

1. 在 `factor_steps.py` 追加一条 `FactorStep`（算子 + 参数 + 产出列）；
2. 在 `builtin_factor_specs.py` 为产出列补充 `FeatureSpec`（unit/direction/lookback/inputs 等）；
3. 运行静态校验（单测覆盖 `validate_factor_engine_steps()`）：step 并集 == 列 spec 集合，缺一即抛 `DataValidationError`。
4. 引擎代码零改动。

## 4. 实施任务

- **P2-1** 新建 `src/stock_analytics/features/factor_steps.py`：`FactorStep` dataclass、`_FACTOR_OPERATORS` 映射、`FACTOR_ENGINE_STEPS` 12 步登记表、`validate_factor_engine_steps()` 静态校验函数。
- **P2-2** 重写 `features/factors.py` 的 `compute_all_factors` 主干为 spec 驱动循环；保留 3.3 所列全部既有行为；`_INPUT_BASE_COLUMNS` 与 `ensure_factor_columns_registered` 不动。
- **P2-3** `builtin_factor_specs.py`：不改 26 条 spec 内容；仅在模块 docstring 补充"列 spec 与 factor_steps.FACTOR_ENGINE_STEPS 强一致"指引（可选）。
- **P2-4** 测试（`tests/unit/stock_analytics/features/test_factors.py` 扩展 + 新增 `test_factor_steps.py`）：
  - 静态：`validate_factor_engine_steps()` 通过；`produces` 并集与 26 列 spec 双集合相等；跨步无重复产出列；步骤数 == 12；
  - 行为：既有 26 列测试（`test_factor_engine_all_and_normalization` / `test_all_factor_engine_outputs_have_registered_spec` 等）保持全绿；断言产出列顺序与步骤表顺序一致；
  - 扩展性：monkeypatch 注入临时 step + 注册临时列 spec，断言引擎自动产出新列；移除任一列 spec 后静态校验抛 `DataValidationError`（fail-closed 双向）。
- **P2-5** 本文档收尾：验收勾选、把"新增因子流程"（3.4）固定为开发约定。

## 5. 测试与门禁

- 定向：`make test TEST_PATH=tests/unit/stock_analytics/features`（pytest，需 `-o addopts="-ra -q --import-mode=importlib"` 规避覆盖率门禁与同名测试文件冲突，沿用 P1 做法）。
- 静态：`make lint`（ruff / mypy / class-size / 边界检查）。
- 全量（可选）：`make test`；不做 `make check` 不承诺。

## 6. 验收标准

- [x] `compute_all_factors` 主体不再包含 12 段硬编码算子调用，改为遍历 `FACTOR_ENGINE_STEPS` 执行。
- [x] 步骤表 `produces` 并集与 `FACTOR_ENGINE_SPECS` 的 26 个 `feature_id` 双集合相等，有单测锁定；任一方向不同步即抛 `DataValidationError`。
- [x] 既有 26 列行为测试全绿；产出列顺序与步骤表一致；`normalize=True` 分支与空表早退行为不变。
- [x] 新增因子仅需"加 step + 加列 spec"，有注入式测试证明引擎零改动可扩展。
- [x] `spec.py` / `registry.py` / `builtin_factor_specs.py` 的 26 条 spec 内容零改动；`make lint` 通过；无新增依赖。

## 9. 实施记录

- 决策点 D1–D4 全部按推荐默认执行（用户确认）。
- 新增 `src/stock_analytics/features/factor_steps.py`：`FactorStep` + `_FACTOR_OPERATORS` 静态映射 + `FACTOR_ENGINE_STEPS`（12 步）+ `run_factor_step`（价格参数注入）+ `validate_factor_engine_steps`（双集合强校验）；`_INPUT_BASE_COLUMNS` 随步骤表迁移至此（单一事实源）。
- 改写 `features/factors.py`：`compute_all_factors` 主干替换为步骤表循环，调用时读 `factor_steps.FACTOR_ENGINE_STEPS` 模块属性（便于扩展注入）；`winsorize`/`standardize_zscore`/normalize/空表早退/派生列硬校验全部保留。
- 新增 `tests/unit/stock_analytics/features/test_factor_steps.py`（6 个测试：双集合 bijection、缺步/幽灵 spec/未知算子均 fail-closed、列顺序、注入式扩展性）。
- 验证：`tests/unit/stock_analytics/features` 43 通过；`tests/unit/stock_analytics` 585 通过；`make lint` 全绿（ruff / mypy 524 文件 / 类规模 / 三个边界检查）。

## 7. 风险与不做什么

- **风险 1 步骤表与列 spec 漂移**：由 3.1 的静态校验 + P2-4 双向测试兜底，任一方向不同步即 fail-closed。
- **风险 2 算子签名变更后步骤表失效**：`_FACTOR_OPERATORS` 显式映射 + 单测直接调用步骤表覆盖，签名变更会在定向测试中立即暴露。
- **风险 3 price_col 注入语义**：步骤表 params 固化默认列名，引擎入参仅覆盖 `price_col`；若未来算子参数面扩大，需扩注入规则（本轮不做通用参数透传）。
- **不做**：不做通用 DAG/依赖拓扑解析（D4）；不做步骤并行与结果缓存；不做表达式 DSL/eval/动态 import；不把 `stock_screen` 管线改为 spec 驱动执行（其宽表由 `pipelines/stock_screen` 生成，不在 FactorEngine 职责）；不改任何列名/单位/方向/`FeatureSpec` 字段；不新增依赖；不改 `FeatureSpec.inputs` 语义与 `transform` 字段（仍预留）。

## 8. 后续候选项（不在本轮）

- P3：`marts`/`pipelines` 兼容重导出收敛（market_temperature 迁移收尾）。
- P4：因子评估闭环接线（`factor_evaluation.py`/`factor_quantile.py` → 因子准入报告管线），为"因子组合成策略"提供质量门槛。
- 单位枚举合并：`MetricUnit` 与 `FeatureUnit` 下沉 `stock_core`，消除双枚举。
- 可选演进：`transform` 字段结构化，使 MARKET builder 与 FactorEngine 共享同一套声明式驱动（当前 MARKET 侧由 `market_daily_ops.py` 各自的 spec 驱动，风格不同，不并入本轮）。
