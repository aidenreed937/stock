# 宏观风控因子选取机制与方法论

> 本文记录宏观风控线（双轨制）**当前因子是如何被选取进系统**的机制——三层配置决策、
> 验证方式（回测导向）、聚合规则，并附上 2026-09 时序 Rank IC 佐证与建议的衔接方式。
> 目的：把隐性的"选取规则"变成可追溯、可复核的显式记录。
>
> 相关文件：`config/analytics/macro_risk.yaml`（因子/维度/指数三段）、
> `src/stock_analytics/pipelines/macro_risk/*`（S2 特征）、`src/stock_strategy/macro/ic.py`（IC 验证）。

---

## 1. 因子进入系统的三层决策

每个因子要依次通过三个决策点，分别在 `config/analytics/macro_risk.yaml` 的三段配置中决定：

| 决策点 | 配置段 | 当前状态 | 含义 |
| :-- | :-- | :-- | :-- |
| **① 是否算这个因子** | `factors` | 23 个全算 | 每个因子产出 0-100 滚动历史分位 score 列 |
| **② 是否聚合进维度** | `dimensions` | 21 个进维度 | 决定是否纳入某个 `dim_*`（等权合成） |
| **③ 是否进入双轨指数** | `indices` | 6 个维度进指数 | 决定维度是否参与 `overheat_index` / `panic_index` |

### 1.1 当前因子去向快照（23 → 10 → 2）

```
factors（23 个）
 ├─ 进维度（21 个）→ 10 个 dim_* → 其中 6 个进双轨指数
 │    valuation(erp,pb) / leverage(margin_pen,margin_buy_ratio)
 │    flow(main_ratio,composite_flow,divergence_score) / breadth(adv_dec,newhigh60_ratio)
 │    fear(pcr,iv,vix) / crowding(market_turnover) / euphoria(fund_issue_pct)
 │    corporate(insider_net,insider_sell,unlock_amount)
 │    cross_asset(cb_price,copper_gold) / smart_money(smart_money)
 │
 ├─ 独立观测、不进维度（3 个）
 │    etf_flow_ratio   →  PIT 不稳、常走降级置空，剔出 dim_flow（见 commit 28f21e6）
 │    repurchase       →  语义与产业资本维度不一致，解耦出 dim_corporate（见 commit 28f21e6）
 │    us_yield_curve   →  年度 IC 符号跨周期漂移，剔出 dim_cross_asset（2026-09 核验）
 │
 └─ 维度进指数（6/10）
      overheat = valuation + leverage + fear(rev) + flow(rev) + crowding
      panic    = breadth + fear + flow
      未进指数：euphoria / corporate / cross_asset / smart_money
```

> 注：`etf_flow_ratio`、`repurchase`、`us_yield_curve` 虽不进维度，但仍保留在 `factors` 段、
> 仍产出 score 列，供研报/IC 独立观测（配置中已补设计注释说明）。

---

## 2. 选取依据：不是 IC 门槛，而是"机制 + 回测验证 + 人工定稿"

当前**没有自动化"IC > X 才纳入"的门禁**。因子的进/出依据是：

1. **机制假说优先**：先有"该因子影响市场情绪/估值/资金/杠杆"的因果机制（如"估值贵了会跌"、"恐慌后会反弹"），才把它算进管线。
2. **回测验证裁决**：因子是否真正保留，看它进入策略后是否改善绩效指标（全周期 v5_etf 的 Sharpe / 最大回撤 / guardrails / 样本外 OOS）。历史 commit 佐证：
   - `ed685f3`：拆分 sentiment → fear/euphoria，`fund_issue` 降级为参考维度，"全周期 v5_etf Sharpe 0.47→0.54、回撤收窄 8.8pp"
   - `28f21e6`：`etf_flow_ratio` 被**证伪**剔除出维度、`repurchase` 解耦（机制 + 工程质量裁决）
3. **人工定稿**：最终进/出由人工改配置 + 重跑回测 + 过 guardrails 确认，不是动态规则。

**结论**：因子池、维度归属、指数构成是**配置快照**，验证是**回测导向**，IC 目前是**事后佐证**而非**入场条件**。

---

## 3. 聚合规则：等权，不按 IC 加权

- 维度内：`mean_horizontal` 等权合成（`pipeline.py:191`）
- 指数内：`mean_horizontal` 等权合成（`pipeline.py:205`）

即：只要因子进了维度/指数，就和同层其他成员**等权**，不因单因子 IC 强弱而加权。
这也解释了为何强因子（如 copper_gold）可能被同维弱因子稀释、弱因子也不拖死指数。

---

## 4. IC 佐证（2026-09 时序 Rank IC，路线 A）

IC 为对基准指数（000985 中证全指）前瞻收益的 Spearman 秩相关，0-100 分位分，窗口 5/20/60 交易日。
**注意**：score 列已按 `direction` 做过方向处理（`rev` = 已做 `100-score` 反转），解读符号需结合方向。

### 4.1 12 个聚合信号（双轨指数 + 维度分）

| 信号 | IC(5D) | IC(20D) | IC(60D) | 备注 |
| :-- | :-- | :-- | :-- | :-- |
| `overheat_index` | +0.007 | +0.022 | **-0.118** | 60D 才显著（过热→见顶），5D/20D 无信号 |
| `panic_index` | +0.049 | +0.046 | **+0.171** | 60D 显著（恐慌→反弹） |
| `dim_cross_asset` | -0.113 | -0.172 | **-0.276** | **全场最强，但未进双轨指数**（降级后仅 cb_price+copper_gold，IC 仍显著） |
| `dim_valuation` | -0.069 | -0.097 | **-0.200** | 已进 overheat，强 |
| `dim_fear` | +0.078 | +0.102 | **+0.208** | 已进双轨，强 |
| `dim_breadth` | +0.019 | +0.012 | +0.089 | 已进 panic，中等偏弱 |
| `dim_leverage` | +0.050 | +0.085 | +0.024 | 已进 overheat，弱-中 |
| `dim_crowding` | +0.074 | +0.078 | -0.045 | 已进 overheat；pooled 短正长负，但年度核验 60D 连续 12 年全负、方向稳定（见 §5.5） |
| `dim_flow` | +0.018 | -0.036 | +0.008 | 已进双轨，**整体弱** |
| `dim_euphoria` | +0.025 | +0.008 | +0.034 | 未进指数，弱 |
| `dim_corporate` | +0.056 | +0.057 | -0.002 | 未进指数，弱 |
| `dim_smart_money` | +0.021 | +0.047 | -0.003 | 未进指数，弱 |

### 4.2 23 个单因子（独立成分层观测，60D 强弱排序）

| 因子 | direction | IC(5D) | IC(20D) | IC(60D) | 解读 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `copper_gold_score` | raw | -0.101 | -0.197 | **-0.330** | 铜金比高→跌（过热见顶），全场最强 |
| `vix_score` | raw | +0.020 | +0.070 | **+0.214** | VIX 高→涨（恐慌反弹） |
| `pb_score` | raw | -0.083 | -0.120 | **-0.210** | 估值贵→跌 |
| `cb_price_score` | raw | -0.032 | -0.086 | **-0.208** | 转债中位高→跌 |
| `erp_score` | rev | -0.060 | -0.085 | **-0.193** | 估值便宜→涨 |
| `us_yield_curve_score` | rev | -0.038 | -0.096 | -0.155 | 利差倒挂深→跌；**已降级为独立观测**（年度符号漂移） |
| `iv_score` | raw | +0.016 | +0.073 | **+0.140** | IV 高→涨 |
| `newhigh60_ratio_score` | rev | +0.015 | +0.069 | **+0.131** | 新高占比高→涨 |
| `etf_flow_ratio_score` | raw | -0.032 | -0.058 | -0.087 | 独立观测，负向稳定 |
| `adv_dec_score` | rev | -0.032 | -0.056 | -0.094 | 广度逆向 |
| `margin_buy_ratio_score` | raw | +0.048 | +0.093 | +0.017 | 20D 动量峰值 |
| `pcr/insider_*/unlock/repurchase/fund_issue/market_turnover/main_ratio/composite_flow/divergence/smart_money` | 混合 | ≈0 | ≈0 | ≈0 | 弱，接近噪音 |

### 4.3 窗口结论

- 三窗口对比：5D mean\|IC\|=0.045、20D=0.064、**60D=0.085**（单因子）/ 12 信号 60D=0.103 —— **窗口越长平均 IC 越强**。
- **60D 是较优主窗口**：双轨指数在 60D 才显著（overheat -0.118 / panic +0.171）；强因子集中在 60D。
- **注意**：单因子 60D 中位 \|IC\|=0.034 最低，说明 60D 强信号集中在**头部少数因子**（copper_gold/vix/pb/cb_price 等），多数因子在 60D 仍弱。
- **建议**：60D 主用（择时决策窗口）+ 20D 确认（折中最稳）+ 5D 参考（短期动量因子专用），与 `macro-risk-research` skill 的 20D/60D 胜率推演结构一致。

---

## 5. 关键发现与建议的衔接方式

### 5.1 发现（供决策参考）

1. **最强的信号集中在三类、且偏 60D**：跨资产类（copper_gold/cb_price）、恐慌类（vix/iv）、估值类（erp/pb）。
2. **`dim_cross_asset` 是 IC 最强维度（-0.276@60D）但刻意不进双轨指数**：2026-09 曾评估将其纳入 `overheat_index`，回测绩效全面劣化（见 §5.3），故维持不纳入——**"单因子/维度 IC 强 ≠ 组合进指数更好"**，印证"必须回测验证、不能只凭 IC 定稿"。
3. **`dim_flow` 整体弱但维持保留**（已进双轨）：单因子 IC 接近 0、年度符号漂移，但 2026-09 剔除回测验证显示 v4 显著变差、v5/rebalance 回撤大幅恶化（见 §5.4），**"IC 弱 ≠ 剔除更好"**，维持现状。
4. **`etf_flow_ratio` 独立观测方向稳定为负**（-0.087@60D）：印证其保留为独立因子的合理性。
5. **`us_yield_curve` 已降级为独立观测**（2026-09）：年度 IC 符号跨周期漂移（60D 符号 `+++-+--++---`），与 cb_price/copper_gold 稳定负向不一致，剔出 `dim_cross_asset`；降级后维度 IC 5D -0.113 / 20D -0.172 / 60D -0.276 仍显著，验证剔除稳定了维度信号。

### 5.2 建议的衔接（不改变当前行为，仅规划）

- **A. IC 作为"准入证据"**：在 `factors`/`dimensions` 配置为强/弱因子加 IC 佐证注释（如"60D \|IC\|<0.05 需复核"），作为人工裁决的输入而非自动门禁。
- **B. IC 作为"权重依据"**：把等权改为按 IC/贡献度加权（改动大，过拟合风险高，需谨慎，当前不推荐）。
- **C. 产物归档**：每次重跑 `build_ic_report` 后，将 4.1/4.2 的 IC 表与方向口径随 `data/analytics/macro_strategy/ic/` 一并留存，作为选取决策的可回溯证据。

### 5.3 评估记录：`dim_cross_asset` 纳入 `overheat_index` 的回测验证（2026-09，结论：不纳入）

> 记录一次完整的"尝试 → 验证 → 回滚"决策链，作为"IC 强≠纳入更好"的实证存档。

**尝试**：将 `dim_cross_asset`（cb_price+copper_gold，direction raw）加入 `overheat_index`，overheat 由 5 维度变 6 维度。

**回测对比**（全周期，v4/v5/v5_rebalance 各变体，含 ETF 变体）：

| 策略 | 基线 CAGR | 纳入后 CAGR | 基线 MaxDD | 纳入后 MaxDD | 基线 Sharpe | 纳入后 Sharpe |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| macro_rotation_v4 | 11.76% | 9.56% | -35.14% | -34.88% | 0.511 | 0.379 |
| macro_rotation_v4_etf | 12.96% | 10.02% | -33.92% | -37.42% | 0.533 | 0.366 |
| macro_rotation_v5 | 12.99% | 11.23% | -36.41% | -33.42% | 0.564 | 0.442 |
| macro_rotation_v5_etf | 14.84% | 12.84% | -33.84% | -33.11% | 0.630 | 0.478 |
| macro_rotation_v5_rebalance_etf | 12.25% | 10.93% | -21.42% | -24.22% | 0.729 | 0.571 |

**结论**：纳入后全策略 CAGR 降 1~2.6pp、Sharpe 降 0.13~0.17、部分回撤扩大——**全面劣化，维持不纳入**。

**归因（机制推断，非定论）**：`dim_cross_asset` 是"越高越预示 60D 后跌"的**慢变量**（单因子 IC 集中在 60D），而 `overheat_index` 的 valuation/leverage/crowding 等主要刻画**当期过热状态**、服务短期防守触发。将慢变量等权混入，稀释了 overheat 对"当下过热→防守触发"的敏感度，使 v5_etf 防守信号延迟/失真，回测变差。

**决策记录**：回滚至基线（overheat 保持 valuation/leverage/fear/flow/crowding 5 维度），`dim_cross_asset` 继续作为 IC/研报独立观测层保留。

### 5.4 评估记录：`dim_flow` 从双轨指数剔除的回测验证（2026-09，结论：维持保留）

> "IC 弱 ≠ 剔除更好"的实证存档，与 §5.3（IC 强 ≠ 纳入更好）构成对称教训。

**背景**：`dim_flow`（main_ratio/composite_flow/divergence_score）单因子与维度 IC 均接近 0（维度 5D +0.018 / 20D -0.036 / 60D +0.008），年度符号大幅漂移，是双轨指数中最弱维度，故评估是否剔除。

**回测对比**（全周期，从 overheat 与 panic 同时剔除 `dim_flow`）：

| 策略 | 基线 CAGR | 剔除后 CAGR | 基线 MaxDD | 剔除后 MaxDD | 基线 Sharpe | 剔除后 Sharpe |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| macro_rotation_v4 | 11.76% | 8.95% | -35.14% | -37.12% | 0.511 | 0.382 |
| macro_rotation_v4_etf | 12.96% | 9.52% | -33.92% | -36.59% | 0.533 | 0.395 |
| macro_rotation_v5 | 12.99% | 13.71% | -36.41% | -43.07% | 0.564 | 0.574 |
| macro_rotation_v5_etf | 14.84% | 15.01% | -33.84% | -41.48% | 0.630 | 0.612 |
| macro_rotation_v5_rebalance_etf | 12.25% | 12.30% | -21.42% | -28.88% | 0.729 | 0.702 |

**结论**：**不建议剔除，维持保留**。v4 系显著变差（Sharpe 0.511→0.382 / 0.533→0.395）；v5 系 CAGR 微升但最大回撤大幅恶化（-34%→-41%~-43%）、Sharpe 持平或略降；rebalance 系 CAGR 持平但回撤恶化（-21.4%→-28.9%）。

**归因（机制推断，非定论）**：`dim_flow` 平均 IC 弱，但在**极端风险时点**（资金流极端、恐慌防守触发）有闸门式边际贡献——不提升平均胜率，但改善关键时点的防守行为；剔除后 v5 系回撤扩大正是该损失的体现。

**决策记录**：维持基线（overheat/panic 均保留 `dim_flow`）。

**方法论沉淀**：单因子/维度 IC 衡量**平均预测力**，策略内贡献还包含**关键时点闸门作用**。IC 强弱不能单独决定纳入/剔除，必须回测验证。

### 5.5 评估记录：`dim_crowding` 从 `overheat_index` 剔除的回测验证（2026-09，结论：维持保留 + 修正方向误判）

**背景**：`dim_crowding`（market_turnover）pooled IC 短正长负（5D +0.074 / 20D +0.078 / 60D -0.045），曾疑为"方向不稳定"；评估是否从 overheat 剔除。

**年度符号核验（关键修正）**：
- 60D 年度 IC **连续 12 年全负**（2015~2026，-0.02 ~ -0.74），方向**稳定**；
- 20D 年度仅 2015(+0.077)/2024(+0.081) 两年为正，其余全负；
- 即 pooled 的"短正长负"是**尺度效应**（换手短期动量正、中期拥挤反转负），**不是跨周期漂移**——此前"方向不稳定"的表述有误，修正为"短长尺度相反、60D 稳定负"。

**回测对比**（全周期，从 overheat 剔除 `dim_crowding`）：

| 策略 | 基线 CAGR | 剔除后 CAGR | 基线 MaxDD | 剔除后 MaxDD | 基线 Sharpe | 剔除后 Sharpe |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| macro_rotation_v4 | 11.76% | 10.00% | -35.14% | -35.13% | 0.511 | 0.407 |
| macro_rotation_v4_etf | 12.96% | 10.24% | -33.92% | -43.66% | 0.533 | 0.388 |
| macro_rotation_v5 | 12.99% | 10.59% | -36.41% | -36.41% | 0.564 | 0.419 |
| macro_rotation_v5_etf | 14.84% | 11.39% | -33.84% | -43.66% | 0.630 | 0.436 |
| macro_rotation_v5_rebalance_etf | 12.25% | 9.94% | -21.42% | -31.64% | 0.729 | 0.535 |

**结论**：**不建议剔除，维持保留**。剔除后全策略全面劣化（CAGR 降 ~2pp、Sharpe 降 0.10~0.19、多处回撤大幅扩大：v4_etf/v5_etf -34%→-43.7%、rebalance -21.4%→-31.6%）。`dim_crowding` 是 overheat 中**贡献明确的防守闸门**——60D 稳定负向（换手天量→见顶）正是"过热→防守"的核心证据。

**方法论沉淀**：**pooled IC 符号翻转 ≠ 方向不稳定**——需年度核验区分"尺度效应"与"跨周期漂移"；`dim_crowding` 是"短长尺度相反"（5/20D 短期动量正、60D 中期拥挤反转负），其 60D 稳定负向与 overheat 逻辑完全一致，是有效成员。

---

## 6. 与通用 SOP 的关系

- 本文是 `通用 SOP × 宏观风控专题规则` 中 **S0 立题（机制/口径）与 S3 验证（IC/回测）** 在"因子选取"这一决策点的落地记录。
- 通用六阶段与 Checklist 见 `../quantitative_research_workflow.md`；宏观线整体符合性审计见 `./sop_gap_assessment.md`。
- 本文不改变任何代码/配置行为，仅记录现状与建议衔接方式。
