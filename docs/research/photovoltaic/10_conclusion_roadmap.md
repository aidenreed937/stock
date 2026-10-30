> 光伏深度行业研究（2026-09）| 目录：[00 总览](00_study_overview.md) · [01 信号尺度](01_signal_horizon.md) · [02 数据](02_data_availability.md) · [03 供需腿](03_supply_demand_legs.md) · [04 贴顶](04_cap_defense.md) · [05 财报拐头](05_profit_turn.md) · [06 防守门](06_defense_gates.md) · [07 产能周期](07_cycle_position.md) · [08 capex 先导](08_capex_leading.md) · [09 定稿闭环](09_final_closed_loop.md) · [10 待办](10_conclusion_roadmap.md) · [11 三源预警卡](11_warning_card.md) · [12 状态门稳健性](12_cycle_robustness.md)

# 待办 / 未决

- [x] 落地撤销 630500 供给腿接入（B 路径，2026-09）：`industry_direction_map.py` 移除
      硅业开工率供给腿构建/映射分支，docstring 标注证伪；630500 回退通用 demand 通道
      （supply 中性 50），重新生成 `global_resonance_l2_map` 验证 supply_score 全为 50。
- [x] 定稿方案闭环实证（§8.1）：630500 放回方向池为净拖累；动量兜底大幅减亏未转正；
      最佳减亏形态 = 动量选中才持有 + 产能周期状态门（外 -0.89%）。
- [x] 资本开支先导前瞻检验（§7.5）：财报 capex 先导**不成立**（数据截断假象、实际滞后
      于产业层）；高扩张区 fwd4q 显著为负（-22~-26%）作防守滞后确认；前瞻仍以产业层
      状态门 + 动量兜底为准。
- [x] 三源预警卡（季度/拐点层复用贴顶信号）定稿：**不在季度防守层重用需求分位贴顶**——加入贴顶会
      劣化防守；最优 = 产业层产能周期状态 + 财报 TTM 两源门（外 -6.47%/外MaxDD 30.56）。
      详见 `11_warning_card.md`。
- [x] 状态门稳健性审计：**阈值稳健（非参数拟合）但仅含一次产能循环实现、跨相位 IS/OOS 无法
      同截面验证**；结论成立但置信度受限于单次实现。详见 `12_cycle_robustness.md`。
- [ ] **（后续数据确认）** 待 2026+「底部右侧→新一轮上行」形成后，二次确认状态门在第二次循环中
      的区分度，才能把「唯一前瞻信号」从单次实现升级为可重复信号（与 07 §3 右侧样本短同源）。

## 产物与复现

- 腿 IC 回测：`scripts/industry_solar_supply_legs_backtest.py` → `data/analytics/industry_strategy/industry_solar_supply_legs_backtest.md`
- 贴顶防守验证：`scripts/industry_solar_cap_defense.py` → `data/analytics/industry_strategy/industry_solar_cap_defense.md`
- 财报净利拐头右确（L2 短期样本）：`scripts/industry_solar_profit_turn.py` → `data/analytics/industry_strategy/industry_solar_profit_turn.md`
- 财报净利拐头右确（成分股聚合扩展 2014→）：`scripts/industry_solar_profit_turn_ext.py` → `data/analytics/industry_strategy/industry_solar_profit_turn_ext.md`
- 财报滞后决定性指标减仓防守门：`scripts/industry_solar_fin_defense_gate.py` → `data/analytics/industry_strategy/industry_solar_fin_defense_gate.md`
- 财报+贴顶组合防守门：`scripts/industry_solar_combo_defense.py` → `data/analytics/industry_strategy/industry_solar_combo_defense.md`
- 产能周期位置指示器（季度尺度拐点预警）：`scripts/industry_solar_cycle_position.py` → `data/analytics/industry_strategy/industry_solar_cycle_position.md`
- 定稿方案闭环实证（动量 Top3 兜底 + 组合防守门）：`scripts/industry_solar_final_closed_loop.py` → `data/analytics/industry_strategy/industry_solar_final_closed_loop.md`
- 资本开支先导前瞻检验（财报 capex 先导）：`scripts/industry_solar_capex_leading.py` → `data/analytics/industry_strategy/industry_solar_capex_leading.md`
- 三源预警卡（贴顶+产能周期+财报TTM复合、§9 定稿：不复用贴顶）：`scripts/industry_solar_warning_card.py` → `data/analytics/industry_strategy/industry_solar_warning_card.md`
- 状态门稳健性审计（阈值敏感/分年切片/IS-OOS，非参数拟合但仅单次循环实现）：`scripts/industry_solar_cycle_robustness.py` → `data/analytics/industry_strategy/industry_solar_cycle_robustness.md`
- 目录总览与全文索引：`00_study_overview.md`
