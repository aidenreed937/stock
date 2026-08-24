# 量化分析引擎升级计划与验收记录：因子检验、截面中性化/正交化、轮动动量、杜邦拆解与双轨统一

> 对应 Gemini 评审提出的 4 大方向 5 项优化（Gap1 中性化/正交化、Gap2 因子检验、Gap3 双轨统一、Gap4 轮动动量 + 杜邦）。
> 状态：**Phase 1～5 已全部落地**。本文保留实施过程、验证基线和后续候选项，当前职责边界以 [`../architecture/domain-responsibilities.md`](../architecture/domain-responsibilities.md) 为准。
> 本计划全部可行性均已对照仓库源码与本地 Curated 真实数据验证（Ground Truth First），无外部检索依赖。

## 0. 现状核对（Gemini 评审 vs 源码事实）

| # | Gemini 主张 | 核对结果 |
| :-: | :--- | :--- |
| 1 | `cross_sectional_ols` 仅一元、无行业+市值联合中性化、无正交化 | ✅ 属实（`cross_sectional.py:167-190` 一元闭式解，仅支持 `group_by`） |
| 2 | 无 Rank IC/ICIR/t、无分层单调性/多空 Spread | ✅ 属实（全库 grep 无 Spearman/ICIR/分层检验；`FeatureKind.LABEL` 仅设计占位） |
| 3 | metrics 仅"宏观聚合"、features 仅"个股截面"，双轨并存 | ⚠️ 部分过时：metrics 现为**多实体**体系（9 Domain，含 INDUSTRY/DERIVATIVES，且 performance/trend/valuation/volatility 为 STOCK 粒度）；`marts/market_temperature.py` 已是官方整合入口 |
| 4 | 无 RPS/加权动量/动量加速度；无杜邦拆解 | ✅ 属实（`momentum.py` 仅多周期动量/反转/距高/EMA 扩散；全库无杜邦） |

**数据可行性（已逐一验证本地 Curated 表）**：

- `index_member`（20.2 万行：`con_code`×`index_code`+`in_date`/`out_date` 时点成分）+ `index_classify`（SW 行业树，含 L1 代码/名称）→ **个股时点行业映射**，支撑中性化。
- `stock_daily_bar` + `daily_basic`（`pe_ttm`/`pb`/`circ_mv`/`turnover_rate`）→ 支撑 IC/分层检验与市值协变量。
- `fund_daily`（26 只核心 ETF，`close`/`pct_chg`）、`sw_daily`（31 个 L1 行业）→ 支撑轮动动量/RPS。
- `income`（`revenue`/`n_income`/`end_date`/`report_type`/`f_ann_date`）、`balancesheet`（`total_assets`/`total_hldr_eqy_exc_min_int`）、`cashflow`（`n_cashflow_act`/`free_cashflow`）、`fina_indicator`（预计算 `roe`/`netprofit_margin`/`assets_turn`/`assets_to_eqt`/`netprofit_yoy` 可交叉验证）→ 支撑杜邦与财报质量。
- `scipy>=1.18.0` 已是 pyproject 直接依赖（含 `linalg`/`stats`），正交化无需新增依赖。

---

## 模块一（P0）：因子有效性检验体系

> 目标：建立"因子好坏"的客观评价标准，避免把无效特征送入策略。

### 新文件 `src/stock_analytics/primitives/factor_evaluation.py` + `factor_quantile.py`（纯函数，零业务依赖）

> 类规模门禁要求新文件 ≤400 行，故拆为两个模块：`factor_evaluation.py`（前向收益 + Rank IC 评估）与 `factor_quantile.py`（分层 + 多空组合）。

| 函数 | 模块 | 说明 |
| :--- | :--- | :--- |
| `add_forward_returns(df, horizons=(1,5,20), price_col="close")` | factor_evaluation | 按 `symbol` 排序后 `shift(-h)` 生成 `fwd_ret_{h}d = P_{t+h}/P_t - 1`（百分数）；h 日不足样本输出 null（fail-closed） |
| `rank_ic_series(df, factor_col, forward_cols, group_col="trade_date")` | factor_evaluation | 每日截面内 `pl.corr(method="spearman")`（因子 vs 各 horizon 前向收益），输出 date×horizon 的 IC 长表；polars 无法计算的截面（全 null/零方差）返回 NaN 已归一为 null |
| `ic_summary(ic_df)` | factor_evaluation | 每 horizon：IC 均值、IC 标准差、**ICIR = Mean/Std**（附年化变体 ×√252，双口径注明）、**t = Mean/(Std/√T)**、IC>0 占比、累积 IC 终点值 |
| `ic_decay(ic_df)` | factor_evaluation | horizon 1..N 的 IC 均值衰减曲线数据（因子信息半衰期观察） |
| `cumulative_ic(ic_df)` | factor_evaluation | 按 horizon 输出 IC 随时间累积序列（供累积 IC 图） |
| `quantile_forward_returns(df, factor_col, forward_col, n_bins=5, group_col="trade_date")` | factor_quantile | 复用 `quantile_bucket` 每日分 n 组，输出各组前向收益均值/中位数面板 |
| `quantile_summary(...)` | factor_quantile | 各组平均收益、**单调性**（组序号 vs 组收益的 Spearman）、**多空 Spread = Top − Bottom**、累计多空收益与最大回撤 |

### 权威依据
- Rank IC（Spearman 秩相关）与 ICIR、t 检验为业界标准因子检验框架（Alphalens / 华泰金工《多因子选股系列之因子测试》）。
- **ICIR 口径**：华泰金工等常见口径为 `Mean(IC)/Std(IC)` 不年化；年化变体 `×√252` 仅作日频序列的辅助信息，计划双口径输出并在字段名注明（`icir` / `icir_annualized`）。
- 前向收益不换仓、不计费（纯检验口径），多空 Spread 同理，均以名义收益呈现。

### 测试与验证
- 单测：`tests/unit/stock_analytics/primitives/test_factor_evaluation.py`（15 用例）+ `test_factor_quantile.py`（7 用例）覆盖已知相关性 Spearman/IC 数值、双口径 ICIR、t 统计量、衰减、累积 IC、分层单调性、多空回撤、空/缺失 fail-closed，以及 polars `pl.corr` 无法计算时返回 NaN 的归一化处理（`rank_ic_series` 将 NaN 统一归 null）。
- 真实数据基线：`scripts/validate_factor_evaluation_baseline.py`（2025-08-01 ~ 2026-08-21，5576 只个股，257 交易日）。

#### Phase 1 真实数据基线（Ground Truth 记录）

面板：`stock_daily_bar`×`daily_basic`，前向收益 1/5/20 日，复权前收盘价（基线口径，未含换仓/费用）。

| 因子 | horizon | n | IC 均值 | ICIR | ICIR 年化 | t 统计量 | IC>0 占比 | cum IC |
| :--- | :---: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| pe_ttm | 1d | 217 | -0.0159 | -0.084 | -1.331 | -1.23 | 0.46 | -3.451 |
| pe_ttm | 5d | 213 | -0.0216 | -0.116 | -1.835 | -1.69 | 0.47 | -4.591 |
| pe_ttm | 20d | 198 | -0.0576 | -0.330 | -5.246 | **-4.65** | 0.32 | -11.396 |
| turnover_rate | 1d | 256 | -0.0601 | -0.314 | -4.992 | **-5.03** | 0.37 | -15.382 |
| turnover_rate | 5d | 252 | -0.0718 | -0.386 | -6.129 | **-6.13** | 0.35 | -18.089 |
| turnover_rate | 20d | 237 | -0.1096 | -0.618 | -9.810 | **-9.51** | 0.26 | -25.965 |
| mom_20d | 1d | 256 | -0.0364 | -0.226 | -3.586 | **-3.61** | 0.41 | -9.311 |
| mom_20d | 5d | 252 | -0.0470 | -0.298 | -4.732 | **-4.73** | 0.38 | -11.850 |
| mom_20d | 20d | 237 | -0.0541 | -0.381 | -6.043 | **-5.86** | 0.37 | -12.819 |

5 分组分层与多空组合（fwd_ret_20d）：

| 因子 | bucket1 | bucket2 | bucket3 | bucket4 | bucket5 | 单调性 | Top-Bottom | 多空累计最大回撤 |
| :--- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| pe_ttm | -0.003% | -0.273% | -0.263% | +0.410% | -0.570% | -0.30 | -0.567% | -372.7 点 |
| turnover_rate | +0.297% | +0.398% | +0.474% | +0.248% | -0.956% | -0.60 | -1.248% | -475.9 点 |
| mom_20d | -0.066% | +0.176% | +0.181% | +0.075% | +0.107% | +0.20 | +0.183% | -386.6 点 |

解读（机制推断，仅本区间样本）：
- **换手率因子反转最显著**：高换手组（bucket5）20 日平均收益 -0.956%，Top-Bottom 达 -1.25%/20日，t=-9.51，与 A 股短期反转/流动性溢价认知一致；
- **20 日动量呈反转**：t=-5.86，A 股短线动量反转为常见特征；
- **低估值因子**：20 日维度显著（t=-4.65），但 5 分组非严格单调（bucket4 偏高），单调性仅 -0.30；
- **数据质量备注**：`daily_basic.pe_ttm` 在约 39 个交易日整日缺失（如 2026-04-08~14），故 pe_ttm 有效 n 少于其他因子——如实记录，非计算错误；
- 多空"累计最大回撤"单位为**累计点差**（每日 Top-Bottom 百分点的累加），非复利百分比，仅作相对形态参考。

### 提交
- `feat(analytics): add rank IC / ICIR and quantile monotonicity factor evaluation`（Phase 1）

---

## 模块二（P1）：行业+市值联合中性化 与 对称正交化

> 目标：产出无行业/市值暴露的纯净 Alpha 因子，消除多因子共线性。

### 2a. 联合中性化 `cross_sectional_neutralize`（新文件 `primitives/neutralization.py`）

> 实现位置调整：因类规模门禁（存量文件不可膨胀），新建独立模块 `primitives/neutralization.py`，而非扩展 `cross_sectional.py`。

```
y 因子被以下联合回归剥离残差：
    y = α + Σ_industry β_k·D_k(行业哑变量) + Σ_c γ_c·X_c(连续协变量, 如 ln(circ_mv)) + ε
    Alpha = ε
```

- **实现：Frisch-Waugh-Lovell 定理两步法（纯 Polars `over()` 向量化）**，零新依赖：
  1. 目标与各协变量分别对行业哑变量（group×industry 组内去均值）取残差；
  2. 残差协变量彼此 Gram-Schmidt 正交化（记录转换系数矩阵 L）；
  3. 目标残差对正交基回归得基系数 beta_i；
  4. 倒序回代 `b_i = beta_i − Σ_{j>i} a_{ji}·b_j` 还原原始协变量空间系数（与一次性 OLS 系数一致）；
  5. 输出残差 `ε = y_res − Σ beta_i·u_i` 与各协变量系数列。
- 该残差与"一次性多元最小二乘"**严格等价**（FWL 定理），按截面日期分组独立回归。
- 输入：`target_col`、`industry_col`、`covariates`（如 `ln_circ_mv`）、`group_col="trade_date"`，可选 `output_col`。
- 行业映射由调用方提供（`index_member` 按 `in_date/out_date` 时点 join + `index_classify` 取 L1），primitives 只消费已映射列，保持纯函数。

### 2b. 对称正交化 `cross_sectional_orthogonalize`（同上模块）

```
对每日期截面因子矩阵 X（已去均值，成对删除缺失）做 SVD 白化：
    X = U·S·Vᵀ  →  Z = U·Vᵀ = X·(XᵀX)^(-1/2)
    ZᵀZ = I（因子两两不相关且方差为 1，对称、无顺序依赖）
```

- 实现：按 `group_col` 逐组 `scipy.linalg.svd`（`scipy` 已是直接依赖）；样本不足（<因子数+1）或奇异（`S[-1] < 1e-10·S[0]`）时该截面输出 null（fail-closed）。
- 采用 SVD 白化 `Z = U·Vᵀ`（Löwdin 对称正交化），无顺序依赖。

### 权威依据
- FWL 定理（Frisch–Waugh–Lovell，1933/1963）保证两步残差化 = 联合回归残差。
- 对称正交化即 Löwdin 正交化；SVD 白化（`X(XᵀX)^{-1/2}`）为量化多因子正交化通行做法（国泰君安/华泰金工多因子研报）。

### 测试与验证
- 单测：`tests/unit/stock_analytics/primitives/test_neutralization.py`（13 用例）——构造带行业均值差 + 协变量相关的人工因子，与 numpy 一次性多元最小二乘对照（残差与系数误差 <1e-9）；正交化后协方差矩阵 ≈ 单位阵（<1e-9）；秩亏/样本不足/行业缺失 fail-closed；单协变量与多协变量全覆盖。
- 真实数据：`scripts/validate_neutralization_baseline.py`（2025-08 ~ 2026-08，5209 股，257 交易日，L1 行业映射全覆盖）。

#### Phase 2 真实数据基线（Ground Truth 记录）

`pe_ttm` 用申万 L1 行业（32 个）+ `ln(circ_mv)` 联合中性化（`scripts/validate_neutralization_baseline.py`）：

| 因子 | vs ln_circ_mv Rank IC (t) | vs fwd_ret_20d Rank IC (t) |
| :--- | :---: | :---: |
| pe_ttm（原始） | **-0.192 (t=-54.5)** | -0.052 (t=-4.08) |
| pe_ttm_neutral（中性化后） | **+0.052 (t=+4.74)** | -0.002 (t=-0.53) |

解读（机制推断，仅本区间样本）：
- **市值暴露剥离成功**：中性化后与 ln_circ_mv 的 Rank IC 从 -0.192（强负，t=-54.5）降至 +0.052（微弱正），市值共线性被大幅消除；
- **原始预测力主要来自市值暴露**：pe_ttm 的 20 日预测力（t=-4.08）在中性化后消失（t=-0.53），说明 A 股低估值因子的短期有效性高度耦合"低估值≈大市值"这一暴露——剥离后纯估值 Alpha 微弱。这正是联合中性化价值所在：识别因子暴露来源，避免把小市值风格误当 Alpha。

### 提交
- `feat(analytics): add joint industry-mv neutralization and symmetric orthogonalization`（Phase 2）

---

## 模块三（P1）：ETF/行业轮动动量（加权动量 / 动量加速度 / RPS）

> 目标：为 26 只核心 ETF 与申万 31 行业提供标准轮动特征。
> 状态：✅ 已落地（Phase 3）。

### 新文件 `src/stock_analytics/primitives/rotation.py`（≤400 行）

> 实现位置调整：存量 `momentum.py` 不可膨胀（类规模门禁），故新建独立模块 `rotation.py`。

| 函数 | 公式 / 说明 |
| :--- | :--- |
| `calculate_weighted_momentum(df, windows=(20,60,120), weights=(0.5,0.3,0.2), price_col="close")` | `score = Σ wᵢ·R_{wᵢ}`（R 为 N 日收益率百分数），权重自动归一化；长度不匹配/权重和≤0 raise ValueError；输出 `weighted_momentum` |
| `calculate_momentum_acceleration(df, fast=20, slow=60, price_col="close")` | `accel = R_fast − R_slow`（短期斜率 vs 长期斜率，动量增强/衰减的二阶信息），输出 `momentum_acceleration_{fast}_{slow}` |
| `calculate_rps(df, window=60, price_col="close", group_col="trade_date")` | 每交易日截面内 N 日收益的百分位排名 `RPS = Rank_min(x)/Count × 100`（0~100）；先物化收益列再排名（避免 polars 嵌套 window 语义失效） |

- 适用数据：`fund_daily`（ETF，`symbol` 粒度）、`sw_daily`（行业，`industry_code` 粒度）；RPS 按 `group_col="trade_date"` 截面分组。

### 权威依据
- 多周期加权动量：Carhart (1997) 动量及多周期复合动量通行做法；
- 动量加速度（二阶动量）：动量因子增强研究的常规衍生量；
- RPS 相对强弱：William O'Neil CANSLIM 体系中的 Relative Strength（RS/RPS 百分位）。

### 测试与验证
- 单测：`tests/unit/stock_analytics/primitives/test_rotation.py`（18 用例）——加权动量数值/权重归一化/长度不匹配 raise、加速度数值与符号、RPS 最高=100/最低分位/并列 min-rank/多日期独立/缺失 null、symbol 分支、空帧/缺列 fail-closed。
- 真实数据冒烟（本地 Curated 黄金表，2026-08-21 最新）：
  - **26 只核心 ETF 60 日 RPS Top5**：港股创新药ETF 100 / 创新药ETF 96.2 / 银行ETF 92.3 / 红利ETF 88.5 / 标普500ETF 84.6；weighted_momentum Top5 = 港股创新药 15.78 / 创新药 10.71 / 标普500 7.46 / 纳指 6.04 / 红利 5.56（RPS 与加权动量强弱方向一致）；
  - **申万 31 行业 60 日 RPS Top5**：医药生物 100 / 银行 96.8 / 煤炭 93.5 / 石油石化 90.3 / 非银金融 87.1；最弱 3：电力设备 3.2 / 国防军工 6.5 / 汽车 9.7；
  - 数值自洽性：26 标的 RPS 步进 100/26≈3.85、31 行业步进 100/31≈3.23，与 `Rank_min/Count×100` 定义吻合。

### 提交
- `feat(analytics): add weighted momentum, momentum acceleration and RPS`（Phase 3）

---

## 模块四（P2）：杜邦拆解与财报质量特征

> 目标：利用本地四张财报表（`income`/`balancesheet`/`cashflow`/`fina_indicator`）丰富基本面特征。
> 状态：✅ 已落地（Phase 4）。

### 新文件 `src/stock_analytics/primitives/fundamental.py`（纯函数，输入标准化财报长表）

| 函数 | 公式 / 说明 |
| :--- | :--- |
| `dupond_decomposition(df, ...)` | `杜邦ROE = 销售净利率 × 总资产周转率 × 权益乘数` = `(n_income/revenue) × (revenue/total_assets) × (total_assets/total_hldr_eqy_exc_min_int)`；输出 `net_profit_margin`/`asset_turnover`/`equity_multiplier`/`roe_dupont`；分母 ≤0 → null（fail-closed） |
| `earnings_quality(df, ...)` | `OCF/净利润`（盈利现金含量，`n_cashflow_act/n_income`）；净利润 ≤0 → null；FCF 收益率需市值 join 由调用方注入 |
| `growth_acceleration(df, metric_col, *, level_col="level")` | `ΔYoY = YoY_t − YoY_{t-1}`（营收/净利润同比增速的一阶差分）；输入契约为「实体键 + level + 指标」对齐长表（level=1 最新、level=2 上一期，期次由调用方负责），level=2 缺失 → null |

- **口径要点**：取 `report_type=1`（合并报表、累计口径；注意 Curated 表中为字符串 `"1"`），按 `end_date` 对齐、以 `f_ann_date` 为可用性时点（避免前视）；`fina_indicator` 的 `roe` 作为**交叉验证**（相对差容差内一致），不作为唯一来源。

### 权威依据
- 杜邦分解（DuPont Analysis）：ROE = 净利率 × 资产周转率 × 权益乘数（经典财务分析框架）；
- 盈利现金含量（OCF/净利润）：Sloan (1996) 应计质量相关文献背景。

### 测试与验证
- 单测：`tests/unit/stock_analytics/primitives/test_fundamental.py`（15 用例）——杜邦乘积恒等式、零/负分母 fail-closed、盈利质量数值、ΔYoY 与缺失、空表/缺列 fail-closed。
- 真实数据交叉验证（`report_type=1` 合并报表、已披露最新一期，与 `fina_indicator.roe` 对比，相对差全部 ≪ 0.5）：
  - **600519.SH 茅台** (2026-06-30)：净利率 0.5075 / 周转率 0.2935 / 乘数 1.2300 / **roe_dupont 0.1832** vs fina roe 17.95% → 相对差 2.0%（口径差异，如含少数股东权益/平均净资产，如实记录）
  - **000858.SZ 五粮液** (2026-03-31)：**roe_dupont 0.0650** vs 6.50% → 相对差 0.015%
  - **600036.SH 招行** (2026-03-31)：**roe_dupont 0.0297** vs 2.96% → 相对差 0.15%
- 冒烟数据注意点：`fina_indicator` 用 `ann_date`（无 `f_ann_date`）；`report_type` 为字符串。

### 提交
- `feat(analytics): add dupont decomposition and earnings quality features`（Phase 4）

---

## 模块五（P2）：统一 metrics/features 双轨调度架构

> 目标：消除双轨心智负担，明确边界，提供统一入口；**不破坏既有实现**（纯新增门面 + 文档）。
> 状态：✅ 已落地（Phase 5）。

### 5a. 定位文档
- **metrics**：多实体（MARKET/STOCK/INDUSTRY/DERIVATIVES/…）时序指标体系 —— `MetricRegistry`(67 指标, 9 Domain) + `MetricEngine.compute` 批量调度 + `load_metric_dataset` 统一加载，产出 `MetricResult`。
- **features**：个股截面特征库 —— `FeatureRegistry`/`FeatureSpec` 元数据 + `FactorEngine` 计算 + `FeatureStore` 物化宽表（29 个内置特征）。
- 两者不是同一层级的"重复实现"，而是**粒度/语义分工**：指标=多实体时序状态，特征=截面暴露；`marts/market_temperature.py` 是既有整合示范（唯一同时使用 MetricEngine + FeatureStore 的构建入口）。

### 5b. 统一顶层门面 `src/stock_analytics/api.py`（新增，纯门面不改动现有模块）
| 函数 | 说明 |
| :--- | :--- |
| `compute_metrics(metric_ids, context, *, registry, calculators) -> tuple[MetricResult, ...]` | 封装 `MetricEngine.compute`，可注入自定义注册表/计算器 |
| `compute_features(feature_ids, context, *, start_date, end_date) -> pl.DataFrame` | 从 `FeatureStore.market_daily` 物化宽表按列投影读取，**始终包含 trade_date** |
| `list_metrics(domain=..., entity_type=...) -> tuple[MetricSpec, ...]` | 统一指标目录（`MetricRegistry.select`） |
| `list_features(kind=..., entity_type=...) -> tuple[FeatureSpec, ...]` | 统一特征目录（`FeatureRegistry`） |
| `AnalyticsContext` | 统一 `target_date/start/end` + 底层 `MetricContext`/`FeatureStore` 的轻量门面上下文 |

- 新增模块对既有调用零影响；`stock_cli`/`marts` 仍可直连底层。
- 边界约束沿用 `scripts/lint_analytics_boundaries.py`：`api.py` 位于顶层（不受 `LAYER_FORBIDDEN` 限制），只聚合下层，不被下层反向依赖——边界检查已验证通过。

### 测试与验证
- 单测：`tests/unit/stock_analytics/test_analytics_api.py`（10 用例）——门面转发正确（注入自定义注册表/计算器）、未知指标抛 KeyError、日期上下文解析、特征列投影/日期过滤/空 Mart fail-closed、统一目录筛选（domain/entity_type/kind）。
- 真实数据冒烟（Ground Truth）：`list_metrics()` 返回 **67 个指标**（9 领域：PERFORMANCE 6 / BREADTH 7 / TREND 3 / VOLATILITY 3 / LIQUIDITY 6 / VALUATION 19 / FLOW 16 / MACRO 3 / DERIVATIVES 4）；`list_features()` 返回 **29 个特征**；`compute_metrics(['option_put_call_volume_ratio'], target_date=2026-08-21)` 返回 2727 行，最新值 0.920944（与 Phase 2 基线一致）。
- 回归：全量门禁通过（ruff / mypy 416 文件 / 边界 / 类规模 / 覆盖率 82.08%）。

### 提交
- `feat(analytics): add unified metrics/features facade`（Phase 5）

---

## 分期排期与提交

| 阶段 | 内容 | 提交建议 | 状态 |
| :---: | :--- | :--- | :---: |
| Phase 1 | 模块一 因子检验体系（primitives + 单测 + 真实数据基线） | `feat(analytics): add rank IC / ICIR and quantile monotonicity factor evaluation` | ✅ 已落地 |
| Phase 2 | 模块二 联合中性化 + 对称正交化 | `feat(analytics): add joint industry-mv neutralization and symmetric orthogonalization` | ✅ 已落地 |
| Phase 3 | 模块三 轮动动量（加权动量/加速度/RPS） | `feat(analytics): add weighted momentum, momentum acceleration and RPS` | ✅ 已落地 |
| Phase 4 | 模块四 杜邦拆解与财报质量 | `feat(analytics): add dupont decomposition and earnings quality features` | ✅ 已落地 |
| Phase 5 | 模块五 统一门面 + 架构文档 | `feat(analytics): add unified metrics/features facade` | ✅ 已落地 |

每阶段独立通过局部 pytest（`--no-cov` 保持 importlib 模式）+ 全量门禁后再提交；全部完成后更新本计划状态为"已落地"并附真实数据验证基线。

## 风险与保守性
- **无外部数据/网络依赖**：全部基于本地 Curated 黄金表与既有 scipy/polars。
- **纯函数分层**：primitives 保持零业务依赖；数据组装在调用方/测试，与现有 `cross_sectional.py` 风格一致。
- **P2 架构统一以"新增门面 + 文档"方式落地**，不动既有注册表/引擎内部，避免回归。
- **ICIR 双口径**与**杜邦交叉验证**均明示口径，防止"编造式"结论污染（AGENTS.md 三层信息分级）。
