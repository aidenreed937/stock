# 跨周期胜率/赔率矩阵（Cross-Cycle Odds Matrix）设计文档

- 状态: 设计待确认（已确认：落地方式=先写设计文档；阈值来源=机制草案 + 回测校准）
- 创建日期: 2026-08-27
- 目标产物: `data/analytics/quant_brief/`（`brief_report.json` 新增 `cross_cycle` 字段 + md 新小节）
- 关联配置: `config/analytics/quant_brief.yaml`
- 关联源码:
  - `src/stock_reporting/interpretation/quant_brief/`（新增 `cross_cycle.py`，与 `risk_gates.py`/`divergence_gate.py` 同级）
  - `src/stock_reporting/interpretation/quant_brief/config.py`（新增字段）
  - `src/stock_analytics/pipelines/quant_brief/` 组装层
- 关联脚本: `scripts/diagnose_temperature_odds_matrix.py`（新增，61 天回归验证）
- 不涉及: `stock_analytics` 评分层、`market_temperature.yaml`、行业结构管线、新数据源

---

## 1. 背景与问题

当前 `quant_brief` 已按四步决策链（宏观定基调 → 量价判性质 → 微观排雷 → 中观选方向）输出风控闸门、仓位档位与方向选择，但存在一个显式缺口：

1. **赔率与胜率没有显式评分**。长/中/短三个周期的事实（慢温度、60 日扩散、快慢背离、短线温度、资金确认、外盘传导）分散在温度快照、行业结构、风险闸门多个字段中，机器可消费的"跨周期决策矩阵"不存在。
2. **决策依据不可复现**。"先赔率后胜率，用仓位统一"是策略语义，当前只能靠人工综合；不同读取者对同一产物会得出不同结论。
3. **历史验证缺失**。没有按象限的历史触发统计，无法回答"某类组合出现后，胜率/赔率到底是高是低"（61 天快照历史索引已具备重建条件，缺的是执行脚本）。

目标（用户明确）：在"风险控制、趋势交易机会、获取收益"三个目标排序下，把跨周期赔率/胜率权衡落成可审计、可回测、可校准的产物字段与报告小节。

---

## 2. 框架定义（本设计依赖的语义）

### 2.1 期望值主线

E = p·W − (1−p)·L（p=胜率，W=平均盈利，L=平均亏损）。盈亏平衡线：赔率 R = W/L 时，胜率需 > 1/(1+R)。

| 赔率 R | 最低胜率 | 典型窗口 |
|---|---:|---|
| 2.0 | 33.3% | 极端冰点/左侧 |
| 1.5 | 40.0% | 趋势回踩 |
| 1.0 | 50.0% | 震荡回归 |
| 0.67 | 60.0% | 右侧追涨（胜率高、赔率被透支） |

### 2.2 跨周期分工

| 周期层 | 本系统事实来源 | 回答的问题 | 提供 |
|---|---|---|---|
| 长（60-120 日/季度） | 慢温度、估值分位、60 日扩散、宏观流动性 | 方向与空间，赚不赚得到 | 赔率 O |
| 中（20 日） | 综合温度、快慢背离、20 日扩散 | 趋势是否成立 | O + S |
| 短（5-10 日） | 短线温度、资金流、外盘传导状态 | 何时介入 | 胜率 S |

决策顺序：**先赔率后胜率**；冲突时由仓位调节（胜率不足→降单笔仓位，不动赔率假设）。

---

## 3. 现状素材盘点

| 矩阵输入 | 现成字段 | 来源产物 | 可用性 |
|---|---|---|---|
| 长周期位置 | `slow_temperature`、`valuation` 温度、`macro_liquidity` | `market_temperature/snapshot.json` | ✅ |
| 中期确认 | `composite`、`fast_slow.divergence`/`divergence_level` | `market_temperature/snapshot.json` | ✅ |
| 60 日扩散 | `breadth_60d_share`（12.90%） | `industry_structure/report.json` | ✅ |
| 短线节奏 | `short_term_temperature_5d/10d` | `market_temperature/facts`（指标事实） | ✅ |
| 资金确认 | `fund_flow` 维度、主力的 20 日累计、资金确认行业数 | 温度快照 + 行业结构 | ✅ |
| 宽度/尾部 | `above_ma60_share`、拥挤行业占比、两融渗透率分位 | 温度快照 + quant_brief risk_gates | ✅ |
| 外盘状态 | `external_risk.shock_status`/`transmission_status` | `market_temperature/snapshot.json` | ✅ |
| **显式 S/O 评分** | 无 | — | ❌ 需新增 |
| **四象限档位与仓位微调** | 无 | — | ❌ 需新增 |
| **历史象限触发统计** | 无（历史索引已就绪） | 61 天 snapshot/quant_brief runs | ❌ 需诊断脚本 |

结论：不需要新数据源和新 Mart；所需事实全部已在本地产物，落地内容 = 规则组合 + 输出 + 回测校准。

---

## 4. 评分口径草案（初始阈值，待 61 天回测校准）

> v1 校准说明（2026-08-27，61 天回归后）：方向性分项已弱化（背离同步 +20→+10、冰极 −30→−15、热极 −20→−10；收敛 +10→+5、恶化 −20→−5；avoid 仓位 −10pp→−5pp）；档位阈值改按 61 天分值分布分位设定（S 高 ≥5 / S 低 ≤−25 / O 高 ≥5）。校准依据与样本限制见第 9 节。

两个评分均为 0-100 连续值 + 三档定性，由加分项累加后映射。初始分值与阈值是**机制草案**，校准流程见第 7 节。

### 4.1 胜率环境 S（当下介入的确定性）

| 输入 | 条件 | 分值 |
|---|---|---|
| 快慢背离等级 | synchronized | +20 |
| | divergent（8≤\|d\|<15） | 0 |
| | extreme（\|d\|≥15）且 fast≤35（冰背离） | −30 |
| | extreme 且 fast≥60（热背离） | −20 |
| 短线温度 5d | <35（冰点） | +10 |
| | 35-65 | 0 |
| | >65（高位） | −10 |
| 技术宽度 above_ma60_share | ≥60% | +10 |
| | 40%-60% | 0 |
| | <40% | −10 |
| 主力资金 20 日累计占比 | ≥0 | +10 |
| | <0 | −10 |
| 外盘传导状态 | pending / shock（未确认） | −10 |
| | 无冲击 / 已消化 | 0 |

映射：≥+30 → 高；−10 ~ +30 → 中；<−10 → 低。
（上限 +50 / 下限 −60，等比例归一至 0-100 的展示值另算，字段同时保留原始分与档位。）

### 4.2 赔率环境 O（上行空间与下行保护）

| 输入 | 条件 | 分值 |
|---|---|---|
| 慢温度 | <50（低位，空间大） | +20 |
| | 50-65 | 0 |
| | >65（高位） | −10 |
| 估值温度 | <40 | +10 |
| | 40-70 | 0 |
| | >70 | −10 |
| 60 日扩散 share | ≥60%（高位） | −10 |
| | 30%-60% | 0 |
| | <30%（低位基数） | +10 |
| 拥挤行业占比 | 0 | +10 |
| | >10% | −10 |
| 宏观流动性温度 | ≥65（偏紧） | −10 |
| | 40-65 | 0 |
| | <40（宽松） | +10 |
| 外盘背景压力 | >75（高压力） | −10 |

映射：≥+20 → 高；−10 ~ +20 → 中；<−10 → 低。
（上限 +60 / 下限 −50，同上归一化。）

### 4.3 轨迹修正项（S/O 的连续性输入，避免当日截面孤立化）

S/O 原始分为当日截面，叠加以下轨迹修正后得到最终分（原始分与修正分同时保留，便于审计）。输入源：快照历史索引（`fast_temperature`/`slow_temperature`/`divergence`/`divergence_level`）与 `market_cycle_review` 的 `signal_days`/`phase_summary`——全部为已落盘本地产物，零新数据源。

| 输入 | 条件 | 修正 |
|---|---|---|
| 背离状态迁移 | extreme → synchronized（收敛确认） | +10 |
| | synchronized → extreme（恶化） | −20 |
| | 其他迁移 | 0 |
| 近 5 日综合温度方向 | 连续上行 | +5 |
| | 连续下行 | −5 |
| 60 日扩散 5 日斜率 | 上升 | +10 |
| | 下降 | −5 |
| 阶段归属 | 仅展示（stage id/名称/天数），不改分 | — |

预演（2026-08-25）：08-24 背离 −17.69（extreme、快温 40.13）→ 08-25 +1.91（synchronized、快温 59.19）命中「extreme → synchronized 收敛确认」+10，同时自动命中升级触发线②（冰点背离后确认回升）——该事件当前单日产物无法呈现，轨迹项可机器判定。

### 4.4 四象限与仓位微调（叠加在 quant_brief 现有仓位档之上）

| 象限 | 语义 | 仓位微调 | 执行备注 |
|---|---|---|---|
| O 高 + S 高 | 底部确认共振 | 0（核心仓上限） | 正常配置，可到档位上限 |
| O 高 + S 低 | 左侧/冰点窗口 | −5 ~ −10pp | 试错仓/分批，等确认再加 |
| O 低 + S 高 | 短线强、中期未确认 | −5pp | 只做确认后波段，不按趋势反转配置 |
| O 低 + S 低 | 高位 + 方向未确认 | −10pp 或回避 | 现金等待 |

硬约束：微调不突破 `position_policy` 的硬性总闸门；若任一风控闸门为硬性 `stop`，cross_cycle 不产生任何上调。追涨/拥挤行业的"一票否决"语义不受本矩阵影响。

---

## 5. 报告呈现（quant_brief 新增小节）

- `brief_report.json` 新增 `cross_cycle` 字段：

```json
{
  "cross_cycle": {
    "status": "ready",
    "table": {
      "long": {"temperature": 57.28, "diffusion_60d_share": 12.9, "role": "赔率"},
      "medium": {"composite": 58.23, "divergence": 1.91, "level": "synchronized"},
      "short": {"short_term_5d": 40.84, "short_term_10d": 47.05, "external": "pending_next_ashare_session"}
    },
    "win_score": 20, "win_level": "中",
    "odds_score": 10, "odds_level": "中",
    "quadrature": "o_mid_s_mid",
    "position_adjustment_pp": 0,
    "trajectory": {
      "divergence_transition": "extreme->synchronized 收敛确认 (+10)",
      "d5_composite_direction": "up",
      "diffusion_60d_slope_5d": "+3.2pp",
      "stage": {"stage_id": 5, "name": "7月下旬低温修复阶段", "days_in_stage": 5}
    },
    "upgrade_triggers": ["60日扩散回升至 30% 以上（赔率打开）", "冰点背离后确认回升（高赔率窗口）"],
    "rules_version": "odds-matrix-v1"
  }
}
```

- `brief_report.md` 新小节「跨周期胜率赔率矩阵」：三周期表 + 象限 + 仓位含义 + 升级触发线。
- 仅在 `status=ready`（S/O 输入完整）时输出；任一关键输入缺失（如外盘状态缺失）时降级为 `degraded` 并披露缺失项，不静默出结论。

---

## 6. 实施步骤与文件清单（方案 A：解读层最小改动）

| 步骤 | 文件 | 内容 |
|---|---|---|
| 1 | `config/analytics/quant_brief.yaml` | 新增 `cross_cycle:` 阈值段（4.1/4.2/4.3/4.4 全部初始值） |
| 2 | `src/stock_reporting/interpretation/quant_brief/cross_cycle.py` | `evaluate_win_odds_matrix(...)`：纯函数，输入温度快照+行业结构+外盘状态，输出 S/O/象限/微调/触发线 |
| 3 | `src/stock_reporting/interpretation/quant_brief/config.py` | 新增 `CrossCycleConfig` 字段（与 `risk_gates` 同级） |
| 4 | quant_brief 组装与模板 | `brief_report.json` 写入 `cross_cycle`；md 新增小节（模板与 risk_gates 同风格） |
| 5 | `tests/unit/stock_reporting/test_quant_brief.py` | 增补：S/O 边界、象限判定、仓位微调、缺失输入降级、rules_version 断言 |
| 6 | `scripts/diagnose_temperature_odds_matrix.py` | 61 天回归：重建 S/O/象限时序 → 触发分布 + fwd1/3/5 前瞻统计（仿 `diagnose_temperature_divergence_gates.py`） |

约束：不触碰 `scoring.py`/`scoring_risk.py`（评分层）；不动 `market_temperature.yaml`；`schema_version` 不变，新字段为增量。

---

## 7. 验证与校准流程

1. **单元验证**：新测试覆盖象限边界与降级路径；`make lint` 通过（class-size / boundaries）。
2. **61 天回归**：以 2026-06-01..08-25 快照历史索引 + quant_brief runs 重建 S/O/象限时间序列；
   - 输出象限出现频率（任一象限占比 ≥70% 视为区分度不足，需调阈值）；
   - 每个象限的 fwd1/3/5 综合温度变化均值与正比例（同 Phase 4 模式，注意：度量温度惯性，非价格收益）；
   - 与现有闸门冲突检查（hard_stop 日不得出现上调）。
3. **轨迹项验证**：单独统计背离迁移事件（extreme→synchronized 收敛 / synchronized→extreme 恶化）在 61 天内的出现次数与 fwd 统计；收敛事件 fwd 均值<0 或正比例<50% 时下调轨迹修正分值或反转方向。
4. **校准规则**：某象限 fwd 均值≈0 或正方向比例 <50% → 下调该象限仓位加成或反转对应输入方向；极端背离等方向性输入与 fwd 统计相反时修正分值符号。
5. **一致性**：quant_brief 增加字段后 61 天全量重跑，`report_consistency` 通过；规则版本 `odds-matrix-v1` 记录于每次运行。
6. **验收标准**：象限分布有效区分；无闸门冲突；报告一致性通过；S/O 评分在 61 天内的档位不会长期锁死（高/中/低均有出现）。

---

## 8. 边界与限制

1. 【机制推断】S/O 的"胜率/赔率"是**环境级别**评分，不是个股 R:R；具体标的的入场价/止损/目标由 watchlist/stock_screen 层负责，本矩阵不越界。
2. 【已验证事实】61 天前瞻统计度量的是**温度惯性**而非价格收益，不能直接当择时收益承诺。
3. 单一时段样本（2026-06-01..08-25，冰区+反弹段），外推需谨慎；校准结果随数据窗口增长应定期重跑诊断脚本。
4. 热背离红旗 61 天零触发，热背离相关分值（S −20）属未验证上端，首次触发需人工复核。
5. cross_cycle 只做仓位微调，不改变现有五道风控闸门的触发与一票否决语义。

---

## 9. 已确认决策记录

| 决策点 | 结论 |
|---|---|
| 落地方式 | 先写设计文档；确认后按方案 A（解读层最小改动）实施 |
| 阈值来源 | 机制草案起步，61 天回测校准（第 7 节流程） |
| 输出位置 | `quant_brief` 新增 `cross_cycle` 字段与 md 小节，不新增独立管线 |
| 数据依赖 | 零新数据源、零新 Mart，复用温度/行业/外盘已有字段 |
| 连续周期维度 | 补充确认：S/O 不采用当日孤立截面，叠加 4.3 轨迹修正项（背离迁移/5 日方向/慢温 5 日变化），输入复用快照历史索引与 cycle_review |
| 轨迹输入源 | 快照历史索引（fast/slow/divergence 序列）+ `market_cycle_review` 的 `signal_days`/`phase_summary`，均为已落盘本地产物 |

## 10. v1 校准记录（61 天回归，2026-06-01..08-25）

诊断输出: `data/analytics/diagnostics/temperature_odds_matrix.json`（61 天逐日行 + 聚合统计）。

### 10.1 校准动作

| 参数 | 草案初始值 | v1 校准值 | 依据 |
|---|---:|---:|---|
| win_sync_bonus | +20 | +10 | 背离同步日多为反弹后，61 天内 S 高分日（原阈值 ≥30）0 天 |
| win_ice_extreme_penalty | −30 | −15 | 极端低温后温度回升（与 Phase 3 冰点窗口一致），罚分过重 |
| win_hot_extreme_penalty | −20 | −10 | 热背离 61 天 0 触发，上端未验证，弱化处理 |
| trajectory_convergence_bonus | +10 | +5 | 收敛事件 fwd1 −4.05（正比例 17%），方向与样本相反，弱化为轻修正 |
| trajectory_deterioration_penalty | −20 | −5 | 恶化事件 fwd1 +8.59（100% 正），方向与样本相反，弱化 |
| adj_avoid_pp | −10 | −5 | avoid 组 fwd3 +5.55（70% 正）；属温度均值回归非收益证据，仅下调不反转 |
| win_level_high | 30 | 5 | 61 天 S 上限 +5，原阈值不可达 |
| win_level_low | −10 | −25 | 原阈值下 S 低占 74%，分位校准至约 1/3 |
| odds_level_high | 20 | 5 | 61 天 O 上限 +5，原阈值不可达 |

### 10.2 校准后分布与方向证据（61 天）

| 指标 | 结果 | 解读 |
|---|---|---|
| 象限分布 | 标准 48/61（79%）、左侧 7（11%）、回避 6（10%）、核心/波段 0 | 本窗口无"高环境共振"样本（core/band 0 天为样本事实）；标准档 79% 接近区分度告警线，待窗口扩大复评 |
| S 档位 | 高 2 / 中 38 / 低 21 | 不再锁死 |
| O 档位 | 高 27 / 中 24 / 低 10 | 分布合理 |
| left 窗口 fwd | fwd1 +5.71（86% 正）、fwd3 +1.96、fwd5 +2.65 | 与"左侧/低位"语义一致，adj_left −7pp 保留 |
| avoid 窗口 fwd | fwd1 +0.27（50%）、fwd3 +7.83（83%）、fwd5 +5.33（83%） | 温度回归主导；更验证"低温窗口"而非高位回避场景，避免档位下调已处理 |
| 收敛事件 | 7 天；fwd1 −4.05（17% 正） | 与草案"收敛=胜率改善"相反，已弱化为 +5 |
| 恶化事件 | 5 天；fwd1 +8.59（100% 正） | 与草案"恶化=胜率恶化"相反（极端后回归），已弱化为 −5 |
| 退化天数 | 0 / 61 | 输入完整 |

### 10.3 校准限制与后续

- 全部 fwd 统计度量**温度惯性**而非价格收益；单窗口（6-7 月冰区+7-8 月反弹）、单一样本 61 天，子样本 5-7 天，方向证据不可外推。
- 方向性分项（同步/极端/收敛/恶化）与样本温度惯性相反或未验证：**保留为弱修正，未做反转**，避免对单窗口过拟合；待数据窗口扩大（如 120+ 天）后重跑诊断再定性。
- step 建议：每次 quant_brief 产物重跑满 60 个新交易日后重放本诊断，比较分布与前向统计。
- rules_version 保持 `odds-matrix-v1`（calibration 常量），配置体现校准后值。
