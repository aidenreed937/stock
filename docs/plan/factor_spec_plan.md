# 因子资产化与 ID/单位收敛实施计划（P0 + P1）

> 状态：规划中，待 P0/P1 决策点拍板后开工。
> 范围：`src/stock_analytics` 及其单测；不触碰 `stock_data` / `stock_strategy` / `stock_reporting` 的生产逻辑（存量消费方不改名，见 3.1）。
> 依据：全部对照源码与测试核实现状，外部规则以 [`../architecture/domain-responsibilities.md`](../architecture/domain-responsibilities.md) 与 [`../architecture/analytics-boundaries.md`](../architecture/analytics-boundaries.md) 为准。

## 0. 背景与目标

### 0.1 背景规范：指标/因子/算子与量化研究基本单元

本计划的方法论基线，作为后续术语与验收口径的前提：

- **量化研究的基本单元是因子**，准确说是带时间维度的截面因子面板（`标的 × 日期 → 因子值`）。判据：基本单元必须是最小且**可检验、可排序、可组合**的载体——只有因子满足；指标不能，算子更不能。
- 加工链与四者边界：

```text
算子(primitives)   怎么算    —— 无状态函数，无业务语义，无截面
指标(metrics)      是什么状态 —— 单实体时序值（长表），描述"现在如何"，无预测义务
因子(features)     谁更好     —— 截面可排序、声明方向与单位、须经 IC/分层检验
策略(strategy)     怎么做     —— 因子的函数（打分/加权 → 信号/组合），须经回测
```

- **指标与因子的区别不在公式，而在用途、截面、检验三条**：同一数值（如 `rsi_14d`）可同时是指标（个股时序状态）与因子（全市场截面排序对象）；只有声明了方向并通过 `rank_ic`/`quantile_summary` 检验的截面暴露才能称为因子，否则它只是指标。
- 项目落点对照：

| 概念 | 落点 | 输出形态 | 截面 | 检验义务 |
| :--- | :--- | :--- | :--- | :--- |
| 算子 | `primitives` | 函数 | 否 | 否 |
| 指标 | `metrics`（长表 `date,symbol,value`） | 单实体时序 | 否 | 否 |
| 因子 | `features`（宽表列，`kind=FACTOR`） | 截面暴露 | 是 | 应经 IC/分位数 |
| 策略 | `stock_strategy`（信号/组合/回测） | 信号 | — | 回测 |

- 对本计划的含义：P1 是"立载体"（赋予 ID/单位/方向/版本），P4 是"立检验"（决定哪些因子有资格进入策略）；两者完成前，因子与指标无实质区别，"因子组合成策略"缺乏可依赖的输入。
- **单位统一原则（计算/存储层 vs 解读展示层）**：计算与存储层使用"最小自然单位 + `unit` 元数据"，百分比只作为解读展示格式，`×100` 仅允许发生在 `stock_reporting`。比率类（收益/动量/乖离/波动率/占比/换手率）内部一律小数 `RATIO`（`0.03`）；有界排位类（RSI、滚动分位）与绝对量（ATR、Amihud 缩放值、金额、成交量）保留自然单位并声明标度，不强制转小数。

### 0.2 现状与本计划目标

前四轮审计确认两条结论：

1. `stock_analytics` 已有三层规范骨架（`MetricSpec`+`MetricEngine`、`FeatureSpec`+`FeatureRegistry`、`primitives` 纯算子），但**因子层没有接入规范**——`FactorEngine.compute_all_factors` 是硬编码管道且无业务调用点，`FeatureRegistry` 中没有 STOCK 粒度的 FACTOR 条目，产出的因子列"有名字、无单位、无方向、无版本"。
2. 同一 `return_20d` 这类 ID 在多个实体粒度上重复出现且单位不同，形成跨层语义漂移（见 2.3）。

本计划分两步：

- **P0 单位与 ID 收敛**：给 metrics 指标补单位元数据；建立 ID 语义登记与命名规范；**不改存量 ID**。
- **P1 因子资产化**：把 `FactorEngine` 的 23 个产出列与 `stock_screen` 评分因子登记进 `FeatureRegistry`，让因子可发现、可校验、有单位和方向。

长期目标（P2–P4，不纳入本计划范围）是"因子组合成策略"：因子资产化（P1）→ 因子质量评估闭环（P4）→ 在 `stock_strategy` 侧组合与回测。本计划只做资产化地基。

### 0.3 本版口径变更摘要

- **0.1 背景规范新增"单位统一原则"**：计算/存储层使用最小自然单位 + `unit` 元数据，百分比只作解读展示格式，`×100` 只发生在 `stock_reporting`；比率类一律小数，排位类（RSI、滚动分位）与绝对量（ATR、Amihud 缩放值、金额、成交量）保留自然单位并声明标度。
- **P0 拆分为三段**（详见 3.2–3.4）：
  - **P0-a 元数据声明**（低风险）：`MetricSpec` 补 `unit`，只声明现状量纲，不改变数值；
  - **P0-b 比率类算子统一小数制**（中风险）：`momentum.py:27,54,82,103`、`liquidity.py:102`、`volatility.py:111,143`、`moneyflow.py:82-89` 移除 `×100`，`FactorEngine` 同步口径；排位类/绝对量/透传字段不改；
  - **P0-c ID 登记**：原 P0-2 内容，命名规范同步更新（新增比率类不再使用 `_pct` 后缀）。
- **一致性联动**：D3 决策点、P1-1 的 `unit` 填法、测试与门禁、验收标准均已按"小数制"口径同步更新（验收新增：grep 无 `* 100.0` 残留）。

## 1. 现状核对（源码事实）

### 1.1 三层规范现状

| 层 | 规范 | 状态 |
| :--- | :--- | :--- |
| `metrics` | `MetricSpec`+`MetricRegistry`+`MetricEngine`+`calculators` | 已闭环，67 个指标注册，25 处 `MetricSpec(` 构造点（14 个文件），但 **`MetricSpec` 无单位字段**（`metrics/spec.py:43-55`） |
| `features` | `FeatureSpec`+`FeatureRegistry`+`FeatureStore`+`MarketDailyBuilder` | MARKET 宽表已闭环；`FeatureKind.FACTOR` 槽位**空置**；`FeatureSpec` 有 `unit`/`direction`/`definition_version` 字段（`features/spec.py:46-65`） |
| `primitives` | 40 个无状态算子 | 健康；`factor_evaluation.py`/`factor_quantile.py` 评估算子已存在但无管线调用 |

### 1.2 因子产出现状

`FactorEngine.compute_all_factors`（`features/factors.py:77-137`）硬编码调用 12 段算子，产出 23 列（normalize 时另附 zscore 列），列名与单位如下：

| 产出列 | 单位 | 产出列 | 单位 |
| :--- | :--- | :--- | :--- |
| `mom_20d/60d/120d/250d` | 百分数 | `amihud_illiq_20d` | ×1e8 绝对量 |
| `reversal_5d` | 百分数 | `turnover_mean_5d/20d/60d` | 换手率同单位 |
| `dist_to_high_250d` | 百分数 | `turnover_std_5d/20d/60d` | 换手率同单位 |
| `ema_spread_12_26` | 百分数 | `volume_surprise_5_20` | 百分数 |
| `realized_vol_20d/60d` | 小数制 | `main_inflow_ratio` | 比值 |
| `atr_14d` | 价格单位 | `main_inflow_ratio_5d/20d` | 比值 |
| `atr_ratio_14d` | 百分数 | `pe_ttm_percentile_1250d` | 0–100 |
| `bollinger_bandwidth_20d` | 百分数 | `pb_percentile_1250d` | 0–100 |
| `bollinger_percent_b_20d` | 0–1 | | |

同一宽表内混有百分数、小数、比值、绝对量、0–100 五种量纲；`normalize=True` 时先 winsorize 再 zscore（`factors.py:134-135`），winsorize 的 0.01/0.99 分位段（`factors.py:28-29`）对绝对量与百分数语义不同。

### 1.3 ID 冲突现状（不再只是"三处"）

`return_20d` 在库内由 4 个实体粒度 × 2 种单位共用：

| 位置 | 实体粒度 | 单位 | 公式 |
| :--- | :--- | :--- | :--- |
| `metrics/calculators/performance.py:87`（`_return_expr` 无 ×100） | STOCK | 小数 | `close/shift(20)-1` |
| `features/builders/market_daily_ops.py:91` | MARKET | 小数 | 对 STOCK `return_20d` 取 `median()` |
| `marts/shared/industry_structure/panel_batch.py:165` | INDUSTRY | 百分数 | `(...)*100` |
| `pipelines/stock_screen/factors.py:100` | STOCK | 百分数 | `(...)*100` |

另有同质冲突：`rsi_14d`（`metrics/calculators/trend.py:101` STOCK 0–100 vs `features/builtin_specs.py:123-134` MARKET 中位数）、`ma_bias_20d`（`trend.py:100` STOCK 小数 vs `builtin_specs.py:135-146` MARKET 中位数）、同族异名 `realized_vol_20d`（FactorEngine）vs `realized_volatility_20d`（`metrics/calculators/volatility.py:115`）、`dist_to_high_250d`（FactorEngine 百分数）/`distance_to_252d_high`（`trend.py:102` 小数）。

**影响面**：`return_20d|return_60d|rsi_14d|ma_bias_20d|rel_return_*` ID 家族全库 347 处引用，贯穿 `metrics`/`features`/`marts`/`pipelines`/`stock_reporting`/测试。这正是 P0 不执行全库改名的原因（见 3.1）。

## 2. 核心决策点（待拍板，括号内为推荐默认）

| # | 决策 | 推荐默认 | 影响 |
| :-: | :--- | :--- | :--- |
| D1 | 存量 `return_20d` 等冲突 ID 本轮是否改名 | **不改，仅登记** | 改则触及 347 处引用、跨五层，风险远超收益；不改不阻塞 P1（P1 只新增 ID） |
| D2 | `MetricSpec` 单位枚举放哪 | **metrics 内新建 `MetricUnit`**，取值与 `FeatureUnit` 对齐 | 若复用 `FeatureUnit` 会违反 metrics→features 依赖门禁（`analytics-boundaries.md:21`）；合并到 `stock_core` 留作后序候选 |
| D3 | 新因子命名规范 | **新 ID 保持简洁但全局唯一**；单位统一小数制后新增比率类不再使用 `_pct` 后缀，跨层同根仅在登记表用 `_median`/`_pct` 标注存量 | 只约束"新增"，不含存量 |
| D4 | 因子方向 `direction` | **按金融常识给默认值**（如 `mom_*`=positive、`reversal`=negative、`realized_vol`=negative），登记表标注"默认值待投研复核" | 方向是资产化必需的机器可读字段，先落地数值，口径复核可在评审后单独调整 |
| D5 | `stock_screen` 评分因子 kind | 登记为 `FeatureKind.SCORE`/`FACTOR` 均可，建议 `FACTOR`（其语义是截面因子），`entity_type=STOCK` | 只登记不改其内部列名 |

若你对任一默认有异议，开工前调整本表即可。

## 3. P0：单位与 ID 收敛

按"先声明、后迁移"拆为 P0-a（元数据声明，低风险）、P0-b（比率类口径迁移，中风险）、P0-c（ID 登记）：

- **P0-a**：`MetricSpec` 补 `unit`，只声明当前量纲，不改数值。
- **P0-b**：比率类算子统一为小数制，把散落各算子的 `×100` 收敛到展示层。
- **P0-c**：ID 语义登记表与命名规范。

### 3.1 明确不做

- **不改名存量 `return_20d`/`rsi_14d`/`ma_bias_20d`/`realized_vol*`/`dist_to_high*`**。347 处引用且消费方单位假设不一致（`stock_reporting/interpretation/quant_brief/formatting.py:123` 把行业 `return_20d` 当百分数，`features/builtin_specs.py:112-122` 的 MARKET `return_20d` 是小数中位数），本轮改名不可控。
- 不引入新的依赖、不动数据 Schema；`stock_reporting` 消费逻辑不改，保持"展示层负责 ×100/加 %"的既有约定。

### 3.2 P0-a：`MetricSpec` 增加 `unit` 字段

- 本任务只声明当前量纲，不伴随任何数值改动。
- 在 `metrics/spec.py` 新增 `MetricUnit(StrEnum)`，取值与 `features/spec.py:30-42` 的 `FeatureUnit` 对齐：`CNY/SHARES/COUNT/RATIO/PERCENT/PERCENTILE/ZSCORE/SCORE_0_100/BOOLEAN/UNKNOWN`。
- `MetricSpec` 增加 `unit: MetricUnit = MetricUnit.UNKNOWN`（默认 UNKNOWN，fail-open 不破坏现有构造）。
- 给 25 处 `MetricSpec(` 构造点（14 个文件：`performance/trend/volatility/liquidity/valuation/flow/flow_market/flow_extensions/breadth/macro/industry/derivatives`）补写 `unit`；借助各文件已有的 `_spec()` 辅助函数，逐文件一次改完。
- 关键映射（实现推断）：`return_*`→RATIO；`ma_bias_20d`/`distance_to_252d_high`→RATIO；`rsi_14d`→PERCENT（0–100 自然区间）；`realized_volatility_20d`/`downside_volatility_20d`/`max_drawdown_60d`→RATIO；`sw_industry_pct_change`→PERCENT（透传源字段，不改值）；`sw_industry_amount_yi`→CNY；其余按模块语义填写。
- 单测：`tests/unit/stock_analytics/metrics/test_registry.py` 增加"每个内置 metric 的 unit != UNKNOWN"断言。

### 3.3 P0-b：比率类算子统一小数制（口径迁移）

- 目标：比率类产出（收益/动量/乖离/波动率/占比/换手率/成交量突增/布林带宽/ATR 比率/资金占比）在 primitives 与 `FactorEngine` 内部统一输出小数 `RATIO`；`×100` 只发生在 `stock_reporting` 展示层。
- 现口径与改法（含同步单测期望值）：
  - `primitives/momentum.py:27,54,82,103`：`mom_*d`、`reversal_*d`、`dist_to_high_*d`、`ema_spread_*` 移除 `* 100.0`；
  - `primitives/liquidity.py:102`：`volume_surprise` 移除 `* 100.0`；
  - `primitives/volatility.py:111,143`：`atr_ratio`、`bollinger_bandwidth` 移除 `* 100.0`（`realized_vol` 已默认小数，`volatility.py:54-56` 保留 `as_percentage` 开关但默认不变）；
  - `primitives/moneyflow.py:82-89`：`margin_growth_*d` 移除 `* 100.0`（`main_inflow_ratio` 已是比值）；
  - `FactorEngine.compute_all_factors` 同步口径，1.2 节产出单位表按"小数 RATIO"更新。
- 同步测试：更新受影响 primitives 单测（momentum/volatility/liquidity/moneyflow）与 `tests/unit/stock_analytics/features/test_factors.py` 的数值期望。
- 不改：排位类 `rsi_14d`、`pe_ttm_percentile_1250d`/`pb_percentile_1250d`；绝对量 `atr_14d`、`amihud_illiq_20d`；metrics 层透传字段（如 `sw_industry_pct_change`）沿用源口径、靠 unit 声明。
- 验收：grep 确认上述 primitives 比率类算子里无 `* 100.0` 残留（展示层与源数据透传除外）；受影响单测全绿。

### 3.4 P0-c：ID 语义登记表与命名规范

- 新增 `config/` 或 `docs/` 下的机器可读登记表（建议 `config/analytics/feature_id_registry.yaml`；若 `config/` 无 analytics 子目录则在计划执行时与现有 `config/` 约定对齐），登记**存量冲突 ID** 的完整语义：`id / entity_type / unit / definition / producers / consumers / conflict_note`。
- 登记条目至少覆盖 1.3 节全部冲突 ID 家族，以及 `return_20d` 四粒度明细。
- 在 `docs/plan/` 本文件保留冲突清单正文（作为人工查阅入口），YAML 作为机器可查源。
- 命名规范（约束新增）写入同一 YAML 或 `docs/`：单位统一小数制后，新增比率类 ID 不使用 `_pct` 后缀；跨层同根仅在登记表用 `_median`/`_pct` 标注存量；横截面因子默认不带实体前缀但必须靠 `entity_type` 区分。
- 单测：新增一条轻量测试，读 YAML 并断言无重复 `(id, entity_type, unit)` 三元组。

## 4. P1：因子资产化

### 4.1 任务 P1-1：`FactorEngine` 23 列注册为 `FeatureSpec`

- 新建 `src/stock_analytics/features/builtin_factor_specs.py`，为 1.2 节的 23 列逐一定义 `FeatureSpec`：
  - `feature_id` = 因子列名；`kind=FACTOR`；`entity_type=STOCK`；
  - `unit` 按 P0-b 迁移后的量纲填写（比率类统一→`RATIO`；`bollinger_percent_b_20d`→`RATIO`；`pe_ttm_percentile_1250d`/`pb_percentile_1250d`→`PERCENTILE`；`atr_14d`→绝对量（价格单位）；`amihud_illiq_20d`→绝对量（暂记 `UNKNOWN` 并在 aliases 注 ×1e8 标度））；
  - `direction` 按 D4 默认填写；`lookback_days` 按窗口填（mom 250 / reversal 5 / dist_to_high 250 / ema_spread 26 / realized_vol 60 / atr 14 / bollinger 20 / amihud 20 / turnover 60 / volume_surprise 20 / main_inflow 20 / percentile 1250）；
  - `inputs` 记录算子与关键参数（如 `calculate_momentum(price_col=close, windows=20,60,120,250)`）；
  - `required_datasets`/`required_columns` 按算子输入填（`stock_daily_bar`：`trade_date,symbol,open,high,low,close,volume,amount,turnover_rate,net_mf_amount`；`daily_basic`：`pe_ttm,pb`）。
- 注册入口：`features/registry.py` 的 `register_builtins()` 追加因子 spec 组，或新增 `register_builtin_factors()` 并在 `features/__init__.py` 调用；保持与现有 MARKET spec 注册一致的风格。
- 命名冲突检查已在 D1/D3 规避：23 列中 `realized_vol_20d/60d` 与 metrics `realized_volatility_20d` 同族异名（保留原列名，登记表记 aliases），其余列与 metrics 存量无同名。

### 4.2 任务 P1-2：`compute_all_factors` 列名校验

- 在 `FactorEngine.compute_all_factors` 尾部（或包一层校验函数）新增硬校验：产出列集合 ⊆ `FeatureRegistry` 中 `kind in {FACTOR}` 且 `entity_type=STOCK` 的 `feature_id` 集合，不匹配即抛 `DataValidationError`（fail-closed）。
- 不把引擎改为 spec 驱动的动态调度（那是 P2，且当前无下游，冻结）。

### 4.3 任务 P1-3：`stock_screen` 评分因子登记

- 为 `pipelines/stock_screen/factors.py:15-42` 的 11 个评分因子补充 `FeatureSpec`（kind=FACTOR、entity_type=STOCK，`direction`/`unit` 按上表）。
- 内部列名**不改**（其 `return_20d` 语义已在登记表记为冲突存量）；仅登记"其宽表输出哪些列、各列语义"，为后续 stock_screen 接评估闭环时提供元数据。
- 若 D5 选择 SCORE，则 kind 相应调整。

## 5. 测试与门禁

- P0-a 单测：`tests/unit/stock_analytics/metrics/test_registry.py`（unit 非 UNKNOWN 断言）；新增 ID 登记 YAML 读取测试。
- P0-b 测试：更新受影响 primitives 单测（momentum/volatility/liquidity/moneyflow）与 `tests/unit/stock_analytics/features/test_factors.py` 的数值期望，锁定新小数口径。
- P1 单测：扩展 `tests/unit/stock_analytics/features/test_factors.py`：
  - `compute_all_factors` 全部 23 列都有对应 `FeatureSpec`；
  - `list_features(kind=FACTOR, entity_type=STOCK)` 非空且列名与宽表一致；
  - 注册后内置 spec 无重复 `(feature_id, definition_version)`。
- 定向门禁：`make test TEST_PATH=tests/unit/stock_analytics/metrics`、`make test TEST_PATH=tests/unit/stock_analytics/features`，再 `make lint`。
- 全量门禁：`make check`（若时间允许）。

## 6. 验收标准

- [ ] `MetricSpec` 含 unit，67 个内置指标 unit 均非 UNKNOWN（有单测锁定）。
- [ ] 比率类 primitives 输出统一为小数制，grep 无 `* 100.0` 残留（展示层/透传除外），受影响单测按新口径全绿。
- [ ] ID 语义登记 YAML 落地，覆盖 1.3 节全部冲突条目，机器可读且无重复三元组。
- [ ] `list_features(kind=FACTOR, entity_type=STOCK)` 返回 23+ 条（FactorEngine）+ 11 条（stock_screen）。
- [ ] `compute_all_factors` 输出列与注册 spec 强一致，任一列未注册即抛错。
- [ ] 存量 `return_20d` 等 ID 未被改名，现有消费方测试全绿。
- [ ] `make lint` 与受影响单测通过；无新增依赖。

## 7. 风险与不做什么

- **风险 1 单位口径误填**：D4 中 direction/unit 的默认值来自实现推断，非投研定论；登记表显式标注"待复核"，不阻塞资产化。
- **风险 2 注册与计算漂移**：spec 是人工声明，可能跟不上算子改动；用 P1-2 的列名硬校验兜底，后续（P2）再做 spec 驱动生成。
- **风险 3 命名规范过约束**：只约束新增 ID，存量 ID 的冲突在 YAML 可见但不强制改，避免本轮波及 347 处引用。
- **不做**：不改存量 ID；不重构 `compute_all_factors` 为动态调度；不接入 IC/分位数评估闭环（P4）；不在 `stock_strategy` 侧新做组合器。

## 8. 后续候选项（不在本轮）

- P2：`FactorEngine` 从硬编码调度升级为 spec 驱动（`inputs`/`transform` 已预留字段）。
- P3：`marts`/`pipelines` 兼容重导出收敛（market_temperature 迁移收尾）。
- P4：因子评估闭环接线（`factor_evaluation.py`/`factor_quantile.py` → 新增因子准入报告管线），为"因子组合成策略"提供质量门槛。
- 单位枚举合并：`MetricUnit` 与 `FeatureUnit` 下沉 `stock_core`，消除双枚举。
