# 宏观风控多策略池与实战纪律手册

> **文档定位**：本手册维护宏观策略池清单（键名/类名/定位）与"如何使用、实战纪律、盲区诊断"
> 等指导性内容；各策略的**状态机转移规则**、**标的/权重/阈值/摩擦成本**、**回测执行语义**
> （T+1、首日归一、现金兜底）与**绩效指标计算**（CAGR / Sharpe / Calmar 等）均为工程实现，
> 一律以工程为准：
> - 状态机逻辑：`src/stock_strategy/pool/` 下对应策略类的 `on_bar` 实现；
> - 标的、权重、阈值、摩擦：`config/strategy/macro_risk.yaml`（唯一真实源）；
> - 回测语义与绩效公式：`src/stock_strategy/macro/runner.py`、`report.py`；
> - 回测绩效对账：`data/analytics/macro_strategy/multi_strategy_comparison.md` 最新产物；
> - 策略池清单（下表）为本手册唯一维护点，新增/变更策略时同步本表。

> **利率口径迁移（2026-10）**：`macro_rotation_v5_hike_gate_etf` 及下文涉及其利率门的历史绩效数字基于月频 `FEDFUNDS`；生产因子现改用日频 `DFF`，本次已刷新宏观因子、策略报告和审计。旧研究数字仅作历史记录，不能视为 DFF 口径的独立验证。

---

## 〇、 宏观风控多策略池清单

策略体系由 `config/strategy/macro_risk.yaml` 统一驱动，标的、权重、基准、阈值与摩擦均以该文件为准；下表仅记录"键名 → 类名 → 定位哲学"，便于路由与速查。

| 策略键名 | 核心类名 | 定位说明（哲学） |
| :--- | :--- | :--- |
| **`macro_risk_v3` / `_etf`** ~~已停用~~ | `MacroRiskV3Strategy` | 单宽基趋势防守压舱石（已停用：无 alpha、回撤与沪深300 持平） |
| **`macro_rotation_v4` / `_etf`** | `MacroRotationV4Strategy` | 双核哑铃风格轮动：牛市主升打满创业板弹性，存量熊市切换高股息红利托底避险 |
| **`macro_rotation_v5` / `_etf`** 🌟 | `MacroRotationV5Strategy` | 资金博弈智能增强轮动：在 V4 基础上用 `smart_money_pct` 做恐慌左侧确认过滤，未逆势接货判定假黄金坑不建仓 |
| **`macro_rotation_v5_rebalance_etf`** 🌟 | `MacroRotationV5RebalanceStrategy` | 权益封顶 + 固收再平衡：V5 权益腿 × 70% 封顶 + 511010 国债 ETF 固收腿，OOS Sharpe 0.81、回撤 -21.3%，收益略低于 v5_etf，适合回撤敏感配置（OOS 风险调整冠军已由 hike_gate 取代，见下行） |
| **`macro_rotation_v5_hike_gate_etf`** 🌟 | `MacroRotationV5HikeGateStrategy` | 加息周期防守门变体：`ffr_chg_6m_score`≥60 时权益腿总权重封顶 0.35（常态 0.7 减半）转固收腿，非对称防守（降息期零干扰）；OOS Sharpe 全池最高（0.95）、回撤最浅（-18.76%），2026-09-04 转正，评估详见 `ffr_cycle_factor_research.md` §8 |
| **`macro_rotation_v5_rebalance_dd` / `_dd20`** ~~已停用~~ | `MacroRotationV5RebalanceDDStrategy` | 回撤深度确认抄底变体：Panic>75 满仓需距前120日高点回撤 ≥15%/20%，否则降级分批（已停用：全周期 CAGR 8.21%/7.50% vs 原版 10.92%、OOS Sharpe 0.62/0.57 vs 0.79，回撤无改善且牺牲浅回撤 V 反收益） |
| **`macro_rotation_v5_fear` / `_etf`** ~~已停用~~ | `MacroRotationFearStrategy` | 恐惧前置抄底变体：以 `dim_fear` (pcr/iv/vix) 替代 `panic_index` 触发抄底（已停用：全周期 CAGR 7.76% vs v5 11.56%、OOS Sharpe 0.31 vs 0.62，情绪脉冲致频繁过早接飞刀） |
| **`macro_rotation_v6` / `_etf`** ~~已停用~~ | `MacroRotationV6Strategy` | 三核资产与风格动量自适应轮动（已停用：不如 v4/v5） |
| **`macro_meta_router` / `_etf`** ~~已停用~~ | `MacroMetaRouterStrategy` | 宏观元策略动态路由器（已停用：不如 v4/v5） |
| **`macro_all_weather_etf`** ~~已停用~~ | `MacroAllWeatherStrategy` | 大类资产全天候自适应相态轮动（已停用：收益平庸 + walk-forward 样本外亏损） |

> 各策略的全周期回测绩效（CAGR / 最大回撤 / 夏普 / 卡玛）以 `data/analytics/macro_strategy/multi_strategy_comparison.md` 最新产物为准；本表不维护绩效数字。

> ⚠️ **有效性评估结论（2026-08 复审，2026-09-04 增补 hike_gate 转正；基于全周期 + 滚动 + walk-forward 审计）**：
> - **启用（有效）**：`macro_rotation_v5` / `v4` / `v5_rebalance_etf` / `v5_hike_gate_etf` —— 有真实正超额（CAGR 8~10%、Sharpe 0.37~0.47），且样本内 alpha 稳定（walk-forward 有效切片占比 67%~100%）；`v5_hike_gate_etf` 为当前风险调整最优（OOS Sharpe 0.95、回撤 -18.76%，全场最高），`v5_rebalance_etf`（OOS Sharpe 0.81）次之。
> - **已停用**：`macro_risk_v3`（无 alpha）；`macro_rotation_v6` / `macro_meta_router`（不如 v4/v5）；`macro_all_weather_etf`（收益平庸 + 样本外亏损）；`macro_rotation_v5_fear`（恐惧前置抄底：全周期 + OOS 均劣于 v5，情绪脉冲致频繁过早接飞刀）；`macro_rotation_v5_rebalance_dd` / `_dd20`（回撤深度确认抄底：全周期 + OOS 均劣于原版 rebalance，回撤无改善且牺牲浅回撤 V 反收益）。策略类代码保留在 `src/stock_strategy/pool/` 作研究留档，仅从 `config/strategy/macro_risk.yaml` 停用。
> - `v5_hike_gate_etf`（2026-09-04 转正）：加息防守门防守有效但非免费——全周期 Sharpe 0.72→0.87、MaxDD -21.4%→-18.8%，2018/2022-2023 两段加息期兑现，代价集中 2019Q1 春季行情误伤（58 天，范式四 -13.45pp）；降息期零干扰（范式六与基线逐位相同）；局限为平台期 diff→0 门提前解除与 2015H1 提前激活属口径巧合，仍保留为后续迭代 backlog。详见 `ffr_cycle_factor_research.md` §8。
> - 详见 `data/analytics/macro_strategy/audit/`（分段收益/压力/滚动/熊市）与 `multi_strategy_comparison.md`。

> **实验留档（2026-09-08，未升级为策略）**：加速度 × 双轨指数择时门控
> （`scripts/accel_regime_gate_experiment.py` + `scripts/accel_gate_walkforward.py`，基准=000985.CSI 全周期）：
> - **G1 恐慌加速门**（恐慌≥60/70 且 a20<0 空仓，假设「避免加速下跌时抄底」）：G1-70 净值 1.005 跑平基准、回撤 -59.8% 反而更差，高换手 224~414 次，**否定**；
> - **G2 狂热加速门**（狂热≥60/65 且 a20>0 空仓，镜像假设「加速段减仓」）：G2-60 净值 0.888 全周期亏损、MDD -61.0% 全场最差，**否定**；
> - **G3 狂热放缓门**（狂热≥T 且 a20≤0 空仓，原始假设「放缓段减仓」）：全周期 MDD 显著改善（-57.9%→-39.3%），但 Walk-Forward 阈值网格 55~70 全部不满足稳健门槛（正超额最多 5/12 年；最优 57.5 年均 +0.81pp，2015/2025 单年分别 -11.4/-21.2pp），**跨期不稳定，停用留档不升级**。产物见 `data/analytics/macro_strategy/robustness/accel_regime_gate_experiment.md` 与 `accel_gate_walkforward.md`。

---

## 一、 场内 ETF 实操 5 大铁律纪律

实盘操作必须严格遵循以下铁律，防止主观情绪破坏量化纪律：

1. **禁止主观预测，不抢跑、不滞后**：严格以系统每日 14:50 运算出的量化信号为唯一执行依据，严禁主观猜顶抄底；
2. **清仓信号发出时坚决下车**：触发 `Overheat > 65 且跌破 MA20` 时，哪怕浮亏也必须坚决卖出股票 ETF 并转入 `511880`（银华日利）避险；
3. **严格限定在 14:50~14:57 尾盘挂单**：严禁早盘 9:30 开盘第一分钟冲动报单，规避早盘集合竞价假突破与流动性冲击滑点；
4. **场内 ETF 溢价率超标禁止追高**：报单前检查实时估值 IOPV；若溢价率 $> +1.0\%$，严禁市价追高买入；
5. **必须使用 3 年以上中长线闲钱**：严禁使用借贷杠杆或短期刚需资金，确保能从容承受 -15%~-25% 的正常周期深蹲。

> 注：铁律 2 中的 Overheat/MA20 触发条件仅为纪律示意，具体阈值以 `config/strategy/macro_risk.yaml` 为准。

---

## 二、 策略 4 大潜在盲区与风险死穴诊断

1. **突发黑天鹅跳空低开风险**：策略基于日线收盘价运算（T 日收盘出信号、T+1 生效）。若突发重大利空发生在周末（如地缘事件），周一开盘跳空低开无法盘前规避，只能收盘后止损；
2. **窄幅箱体震荡市的"均线反复打脸"**：当大盘陷入长期横盘（如在 3000~3100 点窄幅震荡），指数可能在 MA20 附近频繁上下穿梭，导致多次假突破微幅磨损；
3. **宏观因子的"范式漂移"**：宏观雷达依赖 5Y/10Y 历史分位数。若我国无风险利率永久性下移，估值分位中枢需动态自适应调整（见 `quant-metric-standards` skill 的 Regime Shift 自检）；
4. **极端小微盘结构牛市的踏空风险**：若市场出现类似 2023 年仅炒作微盘股而大盘/创业板全趴下的行情，宽基 ETF 组合可能出现阶段性跑输。
