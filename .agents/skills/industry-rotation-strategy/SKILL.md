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
