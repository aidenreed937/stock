---
name: industry-rotation-strategy
description: 申万 31 行业 5 大中观量化因子特征工厂、四大行业轮动策略池（纯动量/反拥挤逆向/供需剪刀差/宏观相态元路由）、11 年全周期多策略回测对账、跨周期稳定性审计门禁与 14:50 盘尾实盘推演 ETF 报单技能。当用户询问申万行业轮动策略、中观因子计算、多策略资金曲线对比、行业抱团瓦解量化防范、跨周期稳健性审计或盘尾实盘调仓指令时使用此技能。
---

# Industry Rotation Strategy (申万行业中观量化特征工厂与轮动策略体系)

本技能定义了申万 31 行业在中观量化因子工程、轮动策略池、跨周期稳定性对账、CI 门禁与实盘巡检中的**端到端标准操作流 (SOP)** 与**量化金融工程规范**。

---

## 快速导航与渐进式知识地图

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                       【主路由与快速执行入口 (本文件)】                         │
│  • 核心量化原则 (Ground Truth)       • 常用命令速查 (CLI Cheat Sheet)          │
│  • 5 步标准执行 SOP                  • 核心状态决策矩阵 (Decision Matrix)      │
└───────────────────────────────────────┬────────────────────────────────────────┘
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
┌─────────────────────────┐┌─────────────────────────┐┌─────────────────────────┐
│ 因子特征工程专题        ││ 四大策略池与实盘专题    ││ 抱团瓦解与宏观演进专题  │
│ [factor_definitions.md] ││ [strategy_pool.md]      ││ [crowding_mechanisms.md]│
│ 5大中观因子与产业资本流 ││ 策略伪代码与ETF映射字典 ││ 15年6大浪潮与第一性原理 │
└─────────────────────────┘└─────────────────────────┘└─────────────────────────┘
                                        │
                                        ▼
                        ┌─────────────────────────┐
                        │ 跨周期审计与 CI 门禁    │
                        │ [audit_guardrails.md]   │
                        │ 6大范式/4大危机/11项门禁│
                        └─────────────────────────┘
```

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

## 常用量化命令速查 (CLI Cheat Sheet)

```bash
# 1. 因子特征工厂：全量生成 31 行业 5 大中观因子日频面板 (2015-2026 全历史)
make industry-factors

# 2. 多策略全周期横向对账：生成 11 年资金曲线对比图、净值 CSV 与 Markdown 研报
make industry-strategy-report

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

## 核心状态决策矩阵 (Decision Matrix)

| 市场所处状态 / 因子特征 | 核心量化指标特征 | 推荐激活策略 | 推荐配置方向与动作 | 详细参考章节 |
| :--- | :--- | :--- | :--- | :--- |
| **强多头主升浪 / 政策牛** | 基准站稳 MA20 + 宏观雷达正常 | **`industry_momentum`** | 打满景气动量 Top 3 进攻赛道（电子/通信/机械） | [`strategy_pool.md`](references/strategy_pool.md) |
| **板块极度过热 / 抱团筑顶** | `ind_crowding >= 85%` + 估值透支 | **`industry_reversal`** | **一票否决剔除过热行业**，买入低估值安全边际板块 | [`crowding_mechanisms.md`](references/crowding_mechanisms.md) |
| **通胀期 / 供给侧格局重塑** | 行业毛利逆势扩张 (`ind_scissors >= 60`) | **`industry_scissors`** | 重仓真实定价权与抗通胀核心资产 | [`factor_definitions.md`](references/factor_definitions.md) |
| **宏观破位 / 黑天鹅恐慌** | `panic_index > 75` 或破位 MA20 | **`industry_meta_router`** | 100% 切换银行/煤炭/公用事业高股息红利防御 | [`strategy_pool.md`](references/strategy_pool.md) |

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
检验策略在 6 大宏观范式与 4 大危机压力测试下的表现：
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

### Step 5: 抱团瓦解风险与下钻诊断排查
当某个热门板块面临拥挤瓦解争议时：
1. 运行 `uv run python -m stock_cli.industry_diagnose --industry <行业名称>`，检查上下游毛利传导与库存周转天数；
2. 检视 `insider_industry_daily.parquet` 中产业资本 60 交易日净流入是否由正转负；
3. 若满足“TCR分位 > 85% + 估值分位 > 95% + 资金流背离”，提示用户启动反拥挤逆向策略或红利防御。

---

## 渐进式深入阅读清单 (References)

按需查阅专题深度文档：
1. [**5 大中观量化因子与产业资本流计算定义**](references/factor_definitions.md) —— 动量/剪刀差/拥挤度/赔率/聪明资金流公式与自适应降级机制。
2. [**四大行业轮动策略池设计与 ETF 映射**](references/strategy_pool.md) —— 动量/逆向/剪刀差/元路由器策略伪代码、交易摩擦与场内 ETF 字典。
3. [**行业抱团演进规律与产业切换底层机制**](references/crowding_mechanisms.md) —— A 股 15 年 6 大浪潮、3 步切换传导机制、4 阶段生命周期与第一性原理。
4. [**跨周期稳定性审计与 CI 门禁规范**](references/audit_guardrails.md) —— 6 大宏观范式切片、4 大危机情景与 11 项质量门禁标准。
