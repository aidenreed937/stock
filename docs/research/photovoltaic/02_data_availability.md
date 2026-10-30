> 光伏深度行业研究（2026-09）| 目录：[00 总览](00_study_overview.md) · [01 信号尺度](01_signal_horizon.md) · [02 数据](02_data_availability.md) · [03 供需腿](03_supply_demand_legs.md) · [04 贴顶](04_cap_defense.md) · [05 财报拐头](05_profit_turn.md) · [06 防守门](06_defense_gates.md) · [07 产能周期](07_cycle_position.md) · [08 capex 先导](08_capex_leading.md) · [09 定稿闭环](09_final_closed_loop.md) · [10 待办](10_conclusion_roadmap.md) · [11 三源预警卡](11_warning_card.md) · [12 状态门稳健性](12_cycle_robustness.md)

# 数据可用性筛选（Ground Truth First）

逐表核对磁盘真实版本（`data/curated/industry/`），覆盖 + 缺失 + data_status 三维判定。
本版记录截至 2026-09-07 的最新状态：NBS 占位行状态标注（`missing_unverified`）、库存专表
接入 SMM/百川校准补丁（扩充至 58 行，2022 起连续 55 个月无缺失）、完成无量纲周数与状态机核验、
`solar_supply_demand` 剪刀差量纲修复（demand 小数 ×100 与 supply 百分数统一，75 行与上游重算 0 误差）。
本轮同时完成海关历史税号桥接、进口/出口方向解析和 `polysilicon_balance` 的净进口接线；平衡表现已合并读取
Comtrade 与 GACC Curated，以下覆盖率仍以当前磁盘真实落盘数据为准。

### ✅ 入选（可用、准确、完整）

| 表 | 覆盖 | 完整性 | 准确性 | 说明 |
| :-- | :-- | :-- | :-- | :-- |
| `solar_capacity`（装机，需求端） | 2018-01~2026-07 | `monthly_new_capacity_gw` 0 缺失 | `actual`/NEA | 需求腿最干净 |
| `solar_cell_production`（电池产量） | 2016-09~2026-08 | `output_current` 11 缺失（历年 1 月占位 + 2026-08 未披露，均标 `missing_unverified`） | `actual`/NBS | 中游实物量最长 |
| `solar_price_chain`（价格链） | 2020-01~2026-09（348 行） | 四档价格 0 缺失 | `actual`/InfoLink | 仅价格，无现金成本字段；yoy/mom 为小数口径 |
| `pv_wafer_monthly`（硅片排产） | 2018-01~2026-08 | 核心量仅 1 缺失 | verified 主导 | `derived_wafer_utilization_rate` 完整 |
| `solar_supply_demand`（中游剪刀差） | 2018-01~2026-07 | supply/demand 0 缺失；剪刀差 75/103 月可用 | `derived`/NBS+NEA | **量纲已修复（2026-09）**，与上游重算 0 误差；需求增速−供给增速（百分数口径，与 `polysilicon_balance` 同式） |

### ⚠️ 有条件入选（核心可用，但需知晓准确度/边界）

| 表 | 风险与边界 |
| :-- | :-- |
| `polysilicon_supply_monthly`（硅料供给） | `production`/`derived_utilization_rate` 完整，但 **24/104 为 `reconstructed`（CPIA 推算）**，官方 actual 仅 20 行（2024-12 起）；**口径收敛（2026-09 阶段 1）：`derived_utilization_rate` 为唯一标准特征，`operating_rate` 降级为参考辅助列**（84/104 缺失，不再作为模型输入） |
| `silicon_wafer_monthly`（硅料硅片主表） | 同上状态构成；`polysilicon_operating_rate`/`wafer_operating_rate` 84/104 缺失，仅参考列 |
| `polysilicon_balance`（硅料平衡） | 已接入 `customs_trade` 与 `customs_trade_gacc` 的进口−出口净进口腿；当前 2018-01~2026-07 有值，2026-08 因海关月份尚未提供而为空。`inventory_weeks` 与 `cycle_score` 有效行数已随库存补丁提升至 58/104 行；**勾稽残差不闭合**（主要由社会库存统计范围扩大导致） |
| `polysilicon_inventory_monthly`（库存） | 已扩充至 58 行（接入 SMM/百川校准补丁，覆盖 2021-06 至今，其中 **2022-01 至 2026-07 连续 55 个月 100% 无缺失**）；每条均标注具体研报与 SMM 来源 URL；`inventory_weeks`/`inventory_status` 58/58 完整有效 |
| `customs_trade` 组件 HS 854140/854143 | 目录已桥接 HS 2017 的 `85414020`/`854140` 与 HS 2022 的 `85414300`，回填后可按统一 `solar_cell` 口径形成跨版本连续序列；当前磁盘仍仅有 2022-01 起连续 55 个月，2021 及以前待回填 |

### ❌ 剔除（不可用）

| 表 | 剔除原因 |
| :-- | :-- |
| `customs_trade` 多晶硅 HS 280461 | Comtrade Curated 当前 **0 条**，但 GACC Curated 已提供 2025-01~2026-07 的 `28046190` 进口/出口记录；两者按来源独立保留，平衡表统一消费 |

## 供需两端是否足够

- **需求端足够且干净**（装机 NEA 官方 103 月 0 缺失）。但数据完整 ≠ 信号有效，需求腿样本外见第四节。
- **中游供需矛盾可量化**：电池产量 vs 装机需求剪刀差（`solar_supply_demand`，修复后 75 月可用）+ 硅料层理论过剩（`polysilicon_balance`）+ 库存周数（`polysilicon_inventory_monthly`）+ 价格周期阶段（`solar_price_chain`），四表组合可构成供需矛盾主指标。
- **供给端仍有缺口**：硅料官方开工率仅 20 月、24 月产量为推算；库存历史已通过 SMM/百川补丁扩充至 58 月（2022 起连续无缺失），但前段 2021 前仍无公开统一统计；净进口代码链路已闭合，但 2025-01 起采用 GACC 人工导入，不能与 Comtrade 的历史口径完全等同。
  缺的是"反周期、可领先"的干净供给腿，本仓库当前没有。

## 供需分析可靠性分级（2026-09-05 实证）

| 层级 | 表 | 结论置信度 |
| :-- | :-- | :-- |
| 第一梯队（高可靠） | `solar_capacity` 需求端 · `solar_price_chain` 价格 · `solar_cell_production` 中游供给 · `solar_supply_demand` 中游剪刀差 | 供需分析主力，0 缺失/状态干净/勾稽自洽 |
| 第二梯队（有条件） | `silicon_wafer_monthly` · `polysilicon_supply_monthly` · `pv_wafer_monthly`（注意 reconstructed）· `polysilicon_balance`（含 Comtrade/GACC 净进口腿）· `polysilicon_inventory_monthly`（58 月，需注意 2026-07 厂内库到全社会库的跳变）· `customs_trade` 组件（2022+） | 量可用，口径边界需知晓 |
| 第三梯队（不可用） | `polysilicon_balance` 勾稽残差对账 · 开工率长历史对比 | 不支撑结论 |

不建议：用勾稽残差做产需对账；用开工率做长期对比；用依赖进口腿的字段。

## 价格链领先结构（2026-09-05 实证）

周度同比（52 周）交叉相关，2020-01 ~ 2026-08：

| 配对 | 峰值相关 | 领先关系 |
| :-- | :--: | :-- |
| 硅料(元/kg) vs 电池(元/W) | 0.923 | 电池领先硅料 9 周 |
| 硅料 vs 硅片(元/片) | 0.981 | 硅片领先硅料 7 周 |
| 硅料 vs 组件(元/W) | 0.902 | 组件领先硅料 4 周 |
| 硅片 vs 电池 | 0.951 | 同步 |
| 电池 vs 组件 | 0.980 | 电池领先组件 2 周 |

解读与边界：
- 传导方向与教科书"成本推动"（硅料→组件）相反：本轮 2020-2026 周期是**需求预期先行、成本滞后确认**
  （上行期组件/电池先涨、硅料随后暴涨；下行期组件先跌、硅料最后崩），价格链相对领先的产业信号是
  **下游单瓦价格（尤其电池片）**，而非硅料。
- 边界：单周期样本、主要由上行期主导，底部横盘期（2024 后）领先结构不稳定；该结构仅作价格解读备注，
  **不作资金领先交易器**——03 研究已证伪价格/供给类信号对 630500 的择时预测力。
