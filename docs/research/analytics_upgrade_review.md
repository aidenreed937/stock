# 量化分析引擎升级回顾：5 阶段改造总结

> 对应 Gemini 评审提出的 4 大方向 5 项优化，本次全部落地。
> 关联计划文档：[`docs/plan/analytics_upgrade_plan.md`](../plan/analytics_upgrade_plan.md)。
> 状态：全部 5 阶段已完成并提交（`20b1ac3` ~ `ac96f8b`），工作区干净，全量门禁通过（ruff / mypy 417 文件 / 边界 lint / 类规模 / 覆盖率 82.08%）。

---

## 一、核心问题：本次改造解决什么

改造前，分析引擎"能生产指标"，但缺少**验证、净化、场景化、统一调度**四个环节。本次围绕 Gemini 评审的 4 大方向补齐了完整工具链：

| # | 解决的问题 | 改造前 | 改造后 |
| :-: | :--- | :--- | :--- |
| 1 | **无法科学验证因子好坏** | 能产几十个特征，但无法回答"哪个因子真有用"，无效因子可能被当 Alpha 进策略 | 因子检验体系（Rank IC / ICIR / t / 分层单调性 / 多空组合） |
| 2 | **因子混杂行业与市值暴露** | 仅一元 OLS + 行业分组 Z-Score，无法同时剥离行业与市值干扰 | FWL 联合中性化 + SVD 对称正交化 |
| 3 | **ETF/行业轮动无标准特征** | 仅普通多周期动量，无相对强弱与复合动量 | 加权动量 / 动量加速度 / RPS 截面百分位 |
| 4 | **只看价格不看财务质量** | 引擎几乎全是行情/估值因子 | 杜邦三因子拆解 / 盈利现金含量 / 增速加速度 |
| 5 | **metrics/features 双轨心智负担** | 两套注册表 + 两套上下文并行，调用方要分别记 API | 统一顶层门面 `api.py`（纯新增，零改动既有实现） |

---

## 二、各阶段交付与真实数据验证（Ground Truth First）

### Phase 1：因子有效性检验体系（`20b1ac3`）

**新增** `primitives/factor_evaluation.py` + `factor_quantile.py`（纯函数，按类规模门禁拆分两模块）：

- `add_forward_returns`：1/5/20 日前向收益
- `rank_ic_series`：每日截面 Spearman Rank IC（polars 无法计算的截面返回 NaN 已归一为 null）
- `ic_summary`：ICIR 双口径（不年化为主 + ×√252 年化辅助）、t 统计量、IC>0 占比、累积 IC
- `ic_decay` / `cumulative_ic`：信息衰减曲线数据
- `quantile_forward_returns` / `quantile_summary`：5/10 分组分层、单调性 Spearman、多空 Spread 与最大回撤

**真实数据基线**（2025-08-01 ~ 2026-08-21，5576 股，257 交易日）：

| 因子 | 20 日 IC | 20 日 t | 解读 |
| :--- | :---: | :---: | :--- |
| turnover_rate | -0.110 | **-9.51** | 高换手→未来跌，反转最显著 |
| mom_20d | -0.054 | **-5.86** | 短线动量反转（A 股特征） |
| pe_ttm | -0.058 | **-4.65** | 低估值 20 日维度有效，但分层非严格单调 |

数据质量备注：`daily_basic.pe_ttm` 约 39 个交易日整日缺失（如实记录，非计算错误）。

### Phase 2：行业+市值联合中性化 + 对称正交化（`a4cc8c1`）

**新增** `primitives/neutralization.py`（存量 `cross_sectional.py` 不可膨胀，新建独立模块）：

- `cross_sectional_neutralize`：FWL 两步法（行业哑变量组内去均值 + Gram-Schmidt 正交基 + 倒序回代），残差与系数与一次性多元 OLS 严格等价（误差 <1e-14）
- `cross_sectional_orthogonalize`：逐截面 SVD 白化 `Z = U·Vᵀ`，因子两两不相关且方差 1，无顺序依赖

**真实数据验证**（5209 股，L1 行业映射全覆盖）：

| 因子 | vs ln_circ_mv Rank IC (t) | vs fwd_ret_20d Rank IC (t) |
| :--- | :---: | :---: |
| pe_ttm（原始） | -0.192 (t=-54.5) | -0.052 (t=-4.08) |
| pe_ttm_neutral（中性化后） | +0.052 (t=+4.74) | -0.002 (t=-0.53) |

**核心发现**：pe_ttm 的短期预测力主要来自市值暴露——剥离后纯估值 Alpha 微弱。联合中性化的价值正在于识别暴露来源，避免把小市值风格误当 Alpha。

### Phase 3：轮动动量（加权动量 / 加速度 / RPS）（`b373b49`）

**新增** `primitives/rotation.py`（存量 `momentum.py` 不可膨胀）：

- `calculate_weighted_momentum`：多周期加权动量 `Σ wᵢ·Rᵢ`（Carhart 1997），权重自动归一化
- `calculate_momentum_acceleration`：`R_fast − R_slow` 动量二阶信息
- `calculate_rps`：截面相对强弱 `Rank_min/Count×100`（O'Neil CANSLIM），先物化收益列再排名（规避 polars 嵌套 window 语义失效）

**真实数据冒烟**（2026-08-21 最新）：
- 26 只核心 ETF 60 日 RPS Top5：港股创新药 100 / 创新药 96.2 / 银行 92.3 / 红利 88.5 / 标普500 84.6
- 申万 31 行业 60 日 RPS Top5：医药 100 / 银行 96.8 / 煤炭 93.5 / 石化 90.3 / 非银 87.1；最弱：电力设备 3.2 / 军工 6.5 / 汽车 9.7

### Phase 4：杜邦拆解与财报质量（`97bc5c7`）

**新增** `primitives/fundamental.py`：

- `dupond_decomposition`：净利率 × 周转率 × 权益乘数 → `roe_dupont`（分母 ≤0 → null fail-closed）
- `earnings_quality`：OCF/净利润 盈利现金含量（Sloan 1996 背景）
- `growth_acceleration`：ΔYoY 增速一阶差分（level 对齐长表）

**真实数据交叉验证**（`report_type=1` 合并报表，与 `fina_indicator.roe` 对比，相对差全部 ≪ 0.5）：

| 标的 | end_date | roe_dupont | fina roe | 相对差 |
| :--- | :--- | :---: | :---: | :---: |
| 600519.SH 茅台 | 2026-06-30 | 0.1832 | 17.95% | 2.0% |
| 000858.SZ 五粮液 | 2026-03-31 | 0.0650 | 6.50% | 0.015% |
| 600036.SH 招行 | 2026-03-31 | 0.0297 | 2.96% | 0.15% |

数据注意点：Curated 表中 `report_type` 为字符串 `"1"`；`fina_indicator` 用 `ann_date`（无 `f_ann_date`）。

### Phase 5：统一 metrics/features 门面（`ac96f8b`）

**新增** `src/stock_analytics/api.py`（纯门面，零改动既有实现，边界 lint 合规）：

- `compute_metrics(metric_ids, context, *, registry, calculators)`：封装 `MetricEngine.compute`
- `compute_features(feature_ids, context, *, start_date, end_date)`：从 `FeatureStore.market_daily` 按列投影读取，**始终包含 trade_date**
- `list_metrics(domain=, entity_type=)` / `list_features(kind=, entity_type=)`：统一目录
- `AnalyticsContext`：统一 `target_date/start/end` + 底层 `MetricContext`/`FeatureStore`

**真实数据冒烟**：`list_metrics()` = 67 指标（9 领域）、`list_features()` = 29 特征；`compute_metrics(PCR, 2026-08-21)` 返回 2727 行，最新值 0.920944 与既有基线一致。

---

## 三、架构原则与工程约束（本次遵循）

1. **纯函数分层**：所有新算子位于 `primitives/`，零业务依赖，仅依赖 Polars/NumPy/SciPy（均为 pyproject 依赖）；数据组装在调用方/测试。
2. **类规模门禁**：新文件 ≤400 行，存量文件不可膨胀——因此因子检验拆两模块、中性化/轮动动量/杜邦均新建独立模块而非扩展存量。
3. **Ground Truth First**：每个阶段都做真实数据验证并记录基线（本地 Curated 黄金表），无外部检索依赖、无编造数值。
4. **Fail-closed**：缺失/样本不足/秩亏/零分母均输出 null 或空表，不推断、不填值。
5. **ICIR 双口径**：主口径不年化（`Mean/Std`，与公开研报可比），年化变体 `×√252` 仅辅助，二者只差常数倍，t 统计量不受影响。

---

## 四、后续方向（未纳入本次，见计划文档）

- 行业估值分位 / 行业动量因子（复用 `historical_percentile` / `with_return_columns`）
- 每标的（INDEX/ETF 实体）IV 指标，`underlying_symbol` 粒度
- 标准 VIX 方差积分方法论替代结算价 IV 代理
- 因子正交化接入多因子合成打分流程
