---
name: industry-rotation-strategy
description: 申万 31 行业 5 大中观量化因子特征工厂、四大行业轮动策略池（纯动量/反拥挤逆向/供需剪刀差/宏观相态元路由）、11 年全周期多策略回测对账、跨周期稳定性审计门禁与 14:50 盘尾实盘推演 ETF 报单技能。当用户询问申万行业轮动策略、中观因子计算、多策略资金曲线对比、行业抱团瓦解量化防范、跨周期稳健性审计或盘尾实盘调仓指令时使用此技能。
---

# Industry Rotation Strategy (申万行业中观量化特征工厂与轮动策略体系)

本技能定义了申万 31 行业在中观量化因子工程、轮动策略池、跨周期稳定性对账、CI 门禁与实盘巡检中的**端到端标准操作流 (SOP)** 与**量化金融工程规范**。

---

## 核心量化原则 (Ground Truth First)

1. **真实数据底座与单一信任源**：
   - 策略参数、基准、宏观范式与场内 ETF 映射唯一信任源：[`config/strategy/industry_rotation.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/strategy/industry_rotation.yaml)；
   - 5 大中观量化因子窗口与权重信任源：[`config/analytics/industry_factors.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/analytics/industry_factors.yaml)；
   - 所有点位、估值分位、资金流与回测指标必须来自本地 Curated 黄金表与 Mart，严禁脑补或记忆推测。
2. **严格 T+1 与交易摩擦成本扣除**：
   - 信号于当日收盘（或 14:50 盘尾预判）生成，次日开盘按目标权重执行（T+1）；
   - 严格扣除券商佣金（万一，0.0001）与冲击滑点（万五，0.0005）；
   - 执行 **3% 调仓死区 (Deadband)** 过滤，杜绝无效微量换手磨损。
3. **抱团瓦解与过热拥挤前置防御**：
   - 将成交额占比 5Y 滚动百分位（`ind_crowding`）与产业资本增减持流作为硬约束；
   - 拥挤度突破 85% 极值时启动逆向一票否决；宏观破位时自动切换低估值红利防御。

---

## 常用量化命令清单

```bash
# 1. 因子特征工厂：全量生成 31 行业 5 大中观因子日频面板 (2015-2026 全历史)
make industry-factors
# 或
uv run python -m stock_cli.industry_factors --start-date 2015-01-01

# 2. 多策略全周期横向对账：生成 11 年资金曲线对比图、净值 CSV 与 Markdown 研报
make industry-strategy-report
# 或
uv run python -m stock_cli.industry_strategy_report

# 3. 跨周期稳定性审计：运行 6 大宏观范式、4 大危机压力测试与 CI 门禁断言
make industry-strategy-audit
# 触发断言门禁（用于 Makefile check / CI）
uv run python -m stock_cli.industry_strategy_audit --assert-guardrails

# 4. 14:50 盘尾实盘巡检：生成最新持仓打分、调仓建议与场内流动性最高 ETF 报单卡片
make industry-strategy-live
# 推演指定策略
uv run python -m stock_cli.industry_strategy_live --strategy industry_momentum --dry-run
uv run python -m stock_cli.industry_strategy_live --strategy industry_meta_router --dry-run
```

---

## 5 大中观量化因子与第一性原理

因子面板物化于 `data/analytics/industry_structure/latest/industry_factor_panel.parquet`，所有因子均经横截面百分位计算无量纲化至 $[0, 100]$，确保 100% 零空值。

| 因子标识 | 因子名称 | 计算公式与核心输入 | 金融经济学第一性原理 |
| :--- | :--- | :--- | :--- |
| **`ind_momentum`** | **景气动量因子** | $0.35 \times \text{Ret}_{20d} + 0.35 \times \text{Ret}_{60d} + 0.30 \times \text{MA}_{bias20}$ | Moskowitz & Grinblatt (1999) 行业动量效应：高景气行业呈现 1~3 个月的信息扩散与机构共识推升惯性。 |
| **`ind_scissors`** | **供需剪刀差因子** | $\text{ProfitGrowth}_{\text{TTM}} - \text{RevenueGrowth}_{\text{TTM}}$ | 衡量毛利率逆势扩张与产业链真实定价权。在去库存或通胀期，具备剪刀差的行业抗通胀转嫁能力最强。 |
| **`ind_crowding`** | **拥挤过热因子** | 行业成交额占全市场比重（TCR）的 5 年滚动历史百分位 | 资金博弈极值与防踩踏约束：TCR 突破 85%~90% 表明流动性虹吸过度，潜在增量资金枯竭，进入高危筑顶期。 |
| **`ind_valuation`** | **估值赔率因子** | $100 - \frac{1}{2}(\text{PE}_{\text{Pct5Y}} + \text{PB}_{\text{Pct5Y}})$ | 反转估值分位：数值越高代表处于历史极端低估底，安全边际充足，向下空间有限且向上赔率极大。 |
| **`ind_smart_flow`** | **聪明资金流因子** | $0.60 \times \text{大单净流入} + 0.25 \times \text{北向外资} + 0.15 \times \text{产业资本增减持回购}$ | Kyle (1985) 知情交易学理：融合内资主力机构、外资陆股通与实体上市公司实控人三维资金共振。 |

---

## 四大行业轮动策略池

| 策略标识 | 策略类名 | 选股逻辑与硬约束 | 适用市场范式与特性 |
| :--- | :--- | :--- | :--- |
| **`industry_momentum`** | `IndustryMomentumRotationStrategy` | 每月调仓，打满景气动量得分最高的 Top 3 行业。 | **强多头主升浪 / 政策牛市**：弹性极高，进攻性最强（11 年全周期 CAGR +5.53%）。 |
| **`industry_reversal`** | `IndustryCrowdingReversalStrategy` | 拥挤度 `ind_crowding > 85` 坚决剔除；在估值处于安全边际（分位 $\le 20\%$）且动量初起中建仓。 | **存量震荡 / 熊市寻底**：防踩踏能力极强，滚动 3 年正收益胜率高达 **64.1%**。 |
| **`industry_scissors`** | `IndustrySupplyDemandScissorsStrategy` | 筛选剪刀差 `ind_scissors >= 60.0`，结合动量与聪明资金流共振打分 Top 3。 | **供给侧改革 / 核心资产重估**：锚定真实定价权与毛利扩张龙头，回撤可控。 |
| **`industry_meta_router`** | `IndustryMetaRouterStrategy` | 监听宏观风险雷达，恐慌破位（`panic > 75`）100% 切换银行/煤炭/公用事业红利防御，多头切换成长。 | **全天候跨周期自适应**：平滑极端黑天鹅，全周期最大回撤仅 49.55%，危机回撤 42.6%。 |

---

## 行业抱团演进规律、切换传导机制与量化方法论

### 1. A 股 15 年 6 大抱团浪潮演进规律

```
2013-2015: 移动互联与TMT (计算机 +101%) ──> 监管降杠杆，配资泡沫破裂
  │
2016-2017: 供给侧改革漂亮50 (白酒 +53%, 家电 +40%) ──> 金融去杠杆与中美贸易战
  │
2019-2021.02: 消费医药茅指数 (社服 +93%, 白酒 +90%) ──> 美债利率飙升，DCF 贴现杀估值
  │
2021-2022: 双碳新能源宁组合 (电设/锂电 +38%) ──> 资本开支无序扩张，产能严重过剩
  │
2022-2024: 存量高股息红利 (煤炭 +9% in 22, 银行 +36% in 24) ──> 924 政策底，转向科技弹性
  │
2024-2026: 全球 AI 算力与自主可控 (通信 +90%, 电子 +53%, 有色 +96%) ──> 当前进行中
```

### 2. 市场抱团产业切换的“三步传导机制”

```
                 【第一步：相对业绩增速差出现剪刀差】
         老抱团行业产能过剩/增速放缓 (如 2021 白酒 / 2023 光伏)
                                  VS
         新产业爆发性景气涌现 (如 2021 新能源 / 2023 AI 光模块)
                                  │
                                  ▼
                 【第二步：增量资金性质与审美偏好切换】
         老资金赎回 (公募基民) <───┼───> 新增量入场 (险资配置 / 海外对冲 / ETF)
                                  │
                                  ▼
                 【第三步：估值赔率均值回归 (高低切)】
         老抱团高位杀估值 (PE 100分位) ──> 新赛道低位放量戴维斯双击
```

- **相对业绩增速差（Growth Differential）**：机构并非追求绝对低估值，而是追求全市场相对业绩增速最快的前 10% 资产。当老赛道增速放缓、新赛道爆发时，机构发生大迁徙。
- **增量资金主导者的审美**：散户杠杆偏好题材弹性（2015），外资与公募偏好高 ROE 白马（2017-2020），赛道公募偏好景气爆发（2021），险资与国家队偏好高股息破净托底（2023-2024）。

### 3. 行业生命周期 4 阶段量化判定矩阵

| 生命周期阶段 | 核心特征表象 | 5 大量化因子状态 | 策略应对操作 |
| :--- | :--- | :--- | :--- |
| **阶段 1：左侧潜伏期** | 市场无人问津，估值处于历史大底，产业资本与主力暗中买入 | `ind_crowding < 30`<br>`ind_valuation > 80`<br>`ind_smart_flow > 65` | **`industry_reversal` 逆向建仓** |
| **阶段 2：景气主升期** | 供需剪刀差扩张，行业订单饱满，机构大单与外资加速共振流入 | `ind_scissors > 60`<br>`ind_momentum > 70`<br>`ind_smart_flow > 70` | **`industry_momentum` / `industry_scissors` 打满 Top 3** |
| **阶段 3：过热筑顶期** | 成交额极度虹吸，散户狂热进场，产业资本加速套现减持，利好滞涨 | `ind_crowding >= 85`<br>`ind_valuation <= 15`<br>`ind_smart_flow` 见顶背离 | **启动 85% 拥挤度硬约束一票否决，分批止盈** |
| **阶段 4：踩踏瓦解期** | 业绩增速不及预期或流动性边际收紧，基民赎回引发被动抛售踩踏 | `ind_crowding` 崩塌<br>`ind_momentum < 30`<br>`ind_smart_flow < 30` | **`industry_meta_router` 切换银行/煤炭/公用事业红利防御** |

### 4. 抱团瓦解的 3 大底层根本原因

1. **资本回报率第一性原理（Capex 时滞与均值回归）**：超额利润必然引来过度投资。投产时滞过后，行业供给呈指数级爆发，不可避免地演变为“产能过剩 $\to$ 降价去库存 $\to$ 毛利坍塌”；股票市场在产能见顶前 6-12 个月提前定价这种均值回归。
2. **定价模型第一性原理（DCF 超长久期资产对利率极其敏感）**：抱团后期估值达 80x~100x PE，绝大部分价值来自远期现金流贴现。一旦无风险利率或折现率上行 50 bps，分母端轻微抬升就会导致远期现值缩水 20%~40%。
3. **资管博弈第一性原理（相对收益考核下的流动性负反馈螺旋）**：公募与机构相对排名考核导致上涨期“不敢不下注”（追高抱团），瓦解期“抢跑砸盘”；一旦边际资金枯竭引发基民赎回，基金经理被迫按比例抛售流动性最好的核心抱团股，形成通杀负反馈。

---

## 标准执行 SOP (5 步工作流)

### Step 1: 刷新因子面板与截面诊断
运行因子工厂生成最新因子矩阵，提取当日各行业综合得分与异常警报：
```bash
uv run python -m stock_cli.industry_factors
```
检查是否存在：
- `ind_crowding >= 85.0` 且 `ind_valuation <= 15.0`（**抱团极度过热瓦解高危区**）；
- `ind_smart_flow >= 75.0` 且 `ind_valuation >= 80.0`（**主力与产业资本暗中筑底区**）。

### Step 2: 运行全周期横向对账研报
执行多策略横向对账，生成最新的绩效对比表与资金曲线图：
```bash
uv run python -m stock_cli.industry_strategy_report
```
- 查看产物：[`data/analytics/industry_strategy/multi_strategy_comparison.md`](file:///Users/mac/workspace/personal/finance/stock/data/analytics/industry_strategy/multi_strategy_comparison.md)；
- 资金曲线与动态回撤置于首屏，核验 CAGR、夏普比率与卡玛比率。

### Step 3: 运行跨周期稳定性审计与门禁断言
检验策略在 6 大宏观范式（杠杆牛熊、供给侧蓝筹、去杠杆慢熊、公募抱团、红利防守、政策新质牛）与 4 大危机压力测试下的表现：
```bash
uv run python -m stock_cli.industry_strategy_audit --assert-guardrails
```
- 查看审计报告：[`data/analytics/industry_strategy/audit/strategy_stability_report.md`](file:///Users/mac/workspace/personal/finance/stock/data/analytics/industry_strategy/audit/strategy_stability_report.md)；
- 确保 11 项跨周期门禁（滚动 3Y 年化、胜率与危机回撤）全部绿灯通过。

### Step 4: 14:50 盘尾实盘推演与 ETF 报单生成
在交易日 14:50 盘尾执行实盘巡检，获取最新持仓行业与场内 ETF 报单建议：
```bash
uv run python -m stock_cli.industry_strategy_live --strategy industry_momentum
```
输出卡片样例：
```
================================================================================
【申万行业轮动 14:50 盘尾实盘巡检与调仓指令卡片】
================================================================================
策略名称: industry_momentum (纯高景气动量轮动)
基准指数: 000985.CSI (中证全指)
最新交易日: 2026-08-28

【最新目标持仓行业与得分】
  1. 801080.SI 电子     : 综合分 52.0 (动量=95.1, 拥挤=84.5, 资金=80.8) -> 目标权重 33.33%
  2. 801890.SI 机械设备 : 综合分 50.3 (动量=89.2, 拥挤=65.1, 资金=78.3) -> 目标权重 33.33%
  3. 801030.SI 基础化工 : 综合分 61.8 (动量=85.4, 拥挤=62.0, 资金=77.3) -> 目标权重 33.33%

【场内可交易 ETF 推荐与报单指令】
  • 801080.SI 电子     -> 买入 512480.SH (半导体芯片ETF)  目标权重: 33.33%
  • 801890.SI 机械设备 -> 买入 516960.SH (机械装备ETF)    目标权重: 33.33%
  • 801030.SI 基础化工 -> 买入 516020.SH (化工ETF)        目标权重: 33.33%
================================================================================
```

### Step 5: 抱团瓦解风险与下钻诊断排查
当某个热门板块面临拥挤瓦解争议时：
1. 运行 `uv run python -m stock_cli.industry_diagnose --industry <行业名称>`，检查上下游毛利传导与库存周转天数；
2. 检视 `insider_industry_daily.parquet` 中产业资本 60 交易日净流入是否由正转负；
3. 若满足“TCR分位 > 85% + 估值分位 > 95% + 资金流背离”，提示用户启动反拥挤逆向策略或红利防御。
