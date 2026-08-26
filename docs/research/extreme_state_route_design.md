# 可靠路线正式化：极端状态驱动原语（Extreme-State Route）设计文档

- 状态: 设计待确认（正式化提案）
- 创建日期: 2026-08-27
- 依据: 61 天回归实证（2026-06-01..08-25），诊断输出 `data/analytics/diagnostics/temperature_odds_matrix.json` 与申万一级指数区间收益
- 目标产物: `data/analytics/quant_brief/`（`brief_report.json` 新增 `extreme_state` 字段 + md 新小节）
- 关联配置: `config/analytics/quant_brief.yaml`
- 关联源码: `src/stock_reporting/interpretation/quant_brief/extreme_state.py`（新增，与 `cross_cycle.py` 同级）
- 不动: 评分层、温度/行业管线、cross_cycle 现有实现（extreme_state 与其并列，不合并）

---

## 1. 背景与问题

61 天实证把市场温度/结构体系的所有信号按可靠度分成了两类：

| 信号类别 | 行为 | 61 天证据 | 可靠度 |
|---|---|---|---|
| 极端状态（高温 >60 / 冰点 / 深度背离 / 拥挤） | 之后回归或惩罚有统计一致性 | 高温后 5 日 0% 正（−4.26%）；冰点背离窗口 fwd5 93% 正；拥挤=高波 | 高 |
| 常态/确认（同步、收敛、温度中位） | 之后涨跌近似抛硬币 | 收敛事件 fwd1 17% 正；standard 组 fwd 温和负 | 低 |

问题：现有 `quant_brief` 把两类信号平铺（五道闸门 + 快慢背离 + cross_cycle 象限），**"极端状态窗口"没有作为一等公民显式输出**——高温/冰点/拥挤三类高可靠信号分散在温度带、背离闸门、拥挤否决多处，不可被机器一次性消费，也不带"窗口状态"语义（如冰点窗口内"左侧分批"、高温窗口内"只减不加"的纪律动作）。

正式化目标：把经验性路线"A 风控裁剪 → B 极端状态定位 → C 档位纪律 → D 方向约束"落成**可审计、可回测、可执行的规则**，其中 B 层（极端状态窗口）是本次新增核心。

---

## 2. 路线定义（正式化后的四层）

```
每日推演链（按顺序，任何一层触发即执行，不进入下一层）：
L1 风控裁剪（确定性）  硬闸门? → 停止进攻；高温>60? → 只减不加；拥挤? → 局部回避
L2 极端状态定位（概率） 冰点窗口 / 高温窗口 / 深度背离窗口 → 标记窗口类型与动作
L3 档位纪律            composite 温度带 → 仓位基准（不突破，也不因"看好"上调）
L4 方向约束（背书非预测）防御底仓方向（银行类低波）+ 条件弹性方向（有色类周期波段）
```

61 天证据背书：L1（高温 0% 正 / 拥挤防尾部 / 空仓跑赢）、L2（冰点/背离 fwd 86-93% 正）、L3（温度带档位映射）、L4（回避可靠、银行全程唯一正收益）。

---

## 3. 核心新增：极端状态窗口原语（L2）

### 3.1 三类窗口定义（输入全部来自已有产物字段）

| 窗口 | 触发条件 | 状态语义 | 纪律动作 | 61 天样本 |
|---|---|---|---|---|
| **高温窗口 hot_window** | 综合温度 composite > `hot_threshold`(60.0) | 热度虚高，回调高发 | 只减不加；达到档位下沿；不新开仓 | 5 天，fwd5 0% 正、−4.26% |
| **冰点窗口 frozen_window** | 综合温度 < `cold_threshold`(45.0)，或（背离 ≤ −15 且快温 ≤ 35） | 冷却回归前兆 | 左侧分批（仓位 ≤ 档位 −7pp 等效），等快温回升确认 | 低温 9 天 fwd5 +0.58%；冰背离 14 天 fwd5 93% 正 |
| **拥挤窗口 crowded_window** | 存在 crowding_temperature ≥90 或 TCR ≥25% 的行业 | 局部高波动，追高即挨打 | 相关行业一票否决；不因强势叙事追高 | 61 天贯穿（电子/通信名单），尾部 −7%~−15% |

窗口叠加规则：可同时命中的窗口并存输出（如"高温 + 拥挤"= 最强降仓组合）；`hot_window` 优先级高于 `frozen_window`（同一时刻理论互斥，以防配置漂移）。

### 3.2 输出规格（`brief_report.json` 新增 `extreme_state`）

```json
{
  "extreme_state": {
    "status": "ready",
    "windows": ["hot_window", "crowded_window"],
    "hot_window": {"triggered": true, "composite": 65.3, "threshold": 60.0},
    "frozen_window": {"triggered": false, "composite": 65.3, "threshold": 45.0},
    "crowded_window": {"triggered": true, "crowded_count": 3,
                        "crowded_industries": ["电子", "通信", "机械设备"]},
    "composite_window_rank": "hot",
    "position_bias_pp": -10,
    "action": "高温+拥挤：只减不加，回避拥挤行业，不新开仓。",
    "rules_version": "extreme-route-v1"
  }
}
```

- `position_bias_pp`：窗口纪律的仓位偏置建议（hot −10、frozen −7（对应跨周期矩阵左侧试错偏置）、crowded 不改总仓仅行业回避；叠加取最负，不突破硬闸门档位）。
- 输入缺失（composite / 拥挤名单任一不可用）→ `status=degraded` + `missing` 披露。

### 3.3 与现有机制的关系（边界）

| 现有机制 | 关系 |
|---|---|
| 五道闸门（L1） | 保留为 L1；extreme_state 是 L2，读闸门结果不重算 |
| cross_cycle 象限（F 层，方向弱） | 并列不合并；extreme_state 只做"窗口状态 + 仓位偏置"，不做方向修正（避免重复 F 层被证伪的预测） |
| 温度带（L3） | 偏置叠加在温度带档位上，`hot_window` 触发时强制"只减不加"注记 |

---

## 4. 其余三层正式化（复用 + 标准化注记）

### 4.1 L1 风控裁剪（已有，标准化动作注记）
- 五道闸门、温度带"只减不加"(<composite_red_flag)、拥挤一票否决——保持现状，不新增规则。
- 正式化点：quant_brief md 增加一行"风控执行链状态"（L1 通过/阻断），把分散闸门收敛为一句执行结论。

### 4.2 L3 档位纪律（已有，标准化）
- 温度带 → `position_policy.effective_band` 已是唯一信任源；正式化：文档确认"不因方向性看好上调档位，只允许偏置下调"。

### 4.3 L4 方向约束（把"优先方向"降级为约束）
- 不再宣称"优先方向=买点"；改为两类角色：
  - **防御底仓**：全程资金确认 + 不拥挤 + 低波（61 天银行唯一正收益方向）——供底仓配置
  - **条件弹性**：修复段周期弹性（61 天有色 +13.65%）——仅在 L2 非 hot 且结构确认时波段参与
- 输出：quant_brief `sector` 补 `role: defense_core | conditional_beta` 标注（映射到既有 priority 列表，不新造行业逻辑）。

---

## 5. 实施清单（方案：解读层新增，不改上游）

| 步骤 | 文件 | 内容 |
|---|---|---|
| 1 | `config/analytics/quant_brief.yaml` | 新增 `extreme_state:` 段：hot_threshold 60 / cold_threshold 45 / bias_hot −10 / bias_frozen −7 / crowding 复用现有常量 |
| 2 | `src/stock_reporting/interpretation/quant_brief/extreme_state.py` | `evaluate_extreme_state(config, market_scores, industry_panel/veto)` 纯函数：三类窗口 + 偏置 + action |
| 3 | `src/stock_reporting/templates/quant_brief.py` + md.j2 | `extreme_state` 字段 + 「风控执行链（L1-L4）」小节（含窗口状态行） |
| 4 | `tests/unit/stock_reporting/test_quant_brief.py` | 三类窗口触发/未触发/叠加/降级 + rules_version 断言 |
| 5 | `scripts/diagnose_temperature_odds_matrix.py` 扩展 | 61 天重建 extreme_state：窗口出现率、fwd1/3/5 一致性、与闸门冲突检查（hot 日不得出现上调） |

约束：不动 `cross_cycle.py`、不动评分层；`schema_version` 不变，增量字段。

---

## 6. 验证与校准

1. **61 天重建**：热/冰/拥挤窗口出现率（预期：hot 5 天、frozen 9-14 天、拥挤贯穿），fwd 统计对比（hot fwd5 0% 正、frozen fwd 正占 ≥60% 为接受线）。
2. **冲突检查**：`hot_window` 日 cross_cycle 不得输出上调（core/left 上调冲突 = 0）。
3. **校准规则**：frozen 窗口 fwd 正占比 <50% → 下调 bias 或收紧条件；hot 窗口出现率 >40% → 阈值上调防过度触发。
4. **一致性**：quant_brief 重跑后 `report_consistency` 通过；`rules_version=extreme-route-v1`。
5. **验收**：窗口分布不过度集中；三类窗口 action 文本与闸门/温度带无矛盾。

---

## 7. 边界与限制

1. 窗口信号实证来自单窗口 61 天；hot 样本 5 天、frozen 9-14 天——方向一致但 n 小，窗口扩大后重放诊断复核。
2. 牛市无样本：高温必回调在牛市中可能产生机会成本——`hot_window` 设计为"只减不加"（允许持有）而非清仓，正是为此留缓冲。
3. `bias_frozen` 偏置是纪律提示不是买入指令；"左侧分批"仍需等待快温回升确认，避免 6 月末假反攻类陷阱。
4. 极端状态度量温度/热度回归，非价格收益承诺；L4 方向标注是约束背书，不构成个股建议。
5. 本设计不构成个性化投资建议。

---

## 8. 决策记录

| 决策点 | 结论 |
|---|---|
| 正式化范围 | L1/L3/L4 复用现有机制并加标准化注记；L2 新增 `extreme_state` 原语 |
| 输出位置 | `quant_brief` 新增 `extreme_state` 字段 + 「风控执行链」小节 |
| 与 cross_cycle 关系 | 并列不合并：extreme_state 管窗口纪律偏置，cross_cycle 管胜率/赔率描述 |
| 验证 | 扩展 `diagnose_temperature_odds_matrix.py` 做 61 天重建与一致性 |
