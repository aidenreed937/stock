# 每日全景量化复盘研报 (基准日：{as_of_date})

## 一、宏观风控大盘全景 (Macro Regime & Risk Gate)

- **中证全指点位**：收盘点位 `{close}` 点 | **20日均线 (MA20)**：`{ma20}` 点（当前偏离 `{diff_ma20_pct}%`）
- **双轨制雷达指标**：
  - **狂热指数 (Overheat Index)**：`{overheat_index}`（危险阈值 >= 65.0）
  - **恐慌指数 (Panic Index)**：`{panic_index}`（冰点阈值 >= 65.0）
- **宏观相态定位**：**【{regime_name}】**
- **定性研判与风控提示**：
  - **状态定性**：{regime_status_summary}
  - **后续推演**：{regime_forward_deduction}
  - **操作原则**：{regime_action_principle}

---

## 二、全天候大类资产配置与 14:50 调仓指令 (Portfolio Allocation)

| 资产大类 | 目标标的 ETF | 建议目标权重 | 核心配置逻辑与功能 |
| :--- | :--- | :---: | :--- |
| **权益防守** | `510880.SH (红利ETF)` | **{weight_defensive}%** | 高股息锁润，抗跌与现金流收益 |
| **权益核心** | `510300.SH (300ETF)` | **{weight_core}%** | 宽基核心资产底仓托底 |
| **权益成长** | `159915.SZ (创业板ETF)` | **{weight_growth}%** | 高贝塔成长弹性进攻 |
| **固收避险** | `511010.SH (国债ETF)` | **{weight_bond}%** | 无风险流动性底座，平抑组合波动 |
| **商品避险** | `518880.SH (黄金ETF)` | **{weight_gold}%** | 对冲全球地缘冲突与货币信用风险 |

---

## 三、申万 31 行业中观特征与主线格局 (Industry Allocation)

### 1. 动量领涨主线 Top 5
| 申万行业 | 行业代码 | 动量分位 | 供需剪刀差分位 | 拥挤度分位 | 场内对应 ETF 映射 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **{ind_name_1}** | `{ind_code_1}` | {momentum_1} | {scissors_1} | {crowding_1} | `{etf_1}` |
| **{ind_name_2}** | `{ind_code_2}` | {momentum_2} | {scissors_2} | {crowding_2} | `{etf_2}` |
| **{ind_name_3}** | `{ind_code_3}` | {momentum_3} | {scissors_3} | {crowding_3} | `{etf_3}` |
| **{ind_name_4}** | `{ind_code_4}` | {momentum_4} | {scissors_4} | {crowding_4} | `{etf_4}` |
| **{ind_name_5}** | `{ind_code_5}` | {momentum_5} | {scissors_5} | {crowding_5} | `{etf_5}` |

### 2. 供需剪刀差 / 基本面改善 Top 5
| 申万行业 | 行业代码 | 剪刀差分位 | 估值分位 | 拥挤度分位 | 场内对应 ETF 映射 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **{ind_name_1}** | `{ind_code_1}` | {scissors_1} | {val_1} | {crowding_1} | `{etf_1}` |
| **{ind_name_2}** | `{ind_code_2}` | {scissors_2} | {val_2} | {crowding_2} | `{etf_2}` |
| **{ind_name_3}** | `{ind_code_3}` | {scissors_3} | {val_3} | {crowding_3} | `{etf_3}` |
| **{ind_name_4}** | `{ind_code_4}` | {scissors_4} | {val_4} | {crowding_4} | `{etf_4}` |
| **{ind_name_5}** | `{ind_code_5}` | {scissors_5} | {val_5} | {crowding_5} | `{etf_5}` |

### 3. 高拥挤度一票否决警报名单 (防范抱团瓦解)
| 申万行业 | 行业代码 | 拥挤度分位 | 动量分位 | 风控警示与操作建议 |
| :--- | :---: | :---: | :---: | :--- |
| **{veto_name_1}** | `{veto_code_1}` | **{veto_crowd_1}** | {veto_mom_1} | **【严禁追高 / 一票否决】** 成交额占比达历史极值，防短线踩踏 |
| **{veto_name_2}** | `{veto_code_2}` | **{veto_crowd_2}** | {veto_mom_2} | **【严禁追高 / 一票否决】** 成交额占比达历史极值，防短线踩踏 |

---

## 四、次日关键临界防线与操作纪律 (Action Rules)

1. **生命线刚性防守**：中证全指 20 日生命线位于 **`{ma20}`** 点（当前相距 `{diff_ma20_pct}%`）；
2. **多头守线纪律**：若收盘价维持在 `{ma20}` 点上方，严格维持 **【{regime_name}】** 仓位结构；
3. **破位拉闸熔断**：一旦盘尾放量跌破 `{ma20}` 点，无条件触发 **【相态 4：0% 权益 + 60% 国债 ETF + 40% 黄金 ETF】** 单日拉闸避险。
