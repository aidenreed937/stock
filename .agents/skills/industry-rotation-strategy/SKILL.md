---
name: industry-rotation-strategy
description: 申万二级行业中观量化轮动与特征体系技能。彻底废除申万一级 31 行业粗颗粒度无效轮动，全面下沉至申万二级行业（SW L2）核心方向池；以二级动量排名进攻（Top3 优势赛道）+ 滚动拥挤度时序分位与估值防守门排雷（一票否决）为核心，提供策略全周期回测、宏观恐慌/加息周期降仓、细分产业腿供需门控与 14:50 盘尾实盘二级 ETF 报单指令生成。当用户询问申万二级行业轮动、二级动量排名、行业拥挤度防守、二级行业 ETF 调仓与回测对账时使用此技能。
---

# Industry Rotation Strategy (申万二级行业中观量化轮动与特征体系)

本技能定义了**申万二级行业 (SW L2)** 在中观量化因子工程、轮动策略池、拥挤度防守排雷、跨周期回测对账与 14:50 盘尾实盘 ETF 报单的**端到端标准操作流 (SOP)** 与**量化金融工程规范**。

> **架构演进声明 (Ground Truth)**：
> 申万一级 31 行业粗颗粒度轮动因“行业内部成分股严重分化、选对大类却被权重股拖累”，实测样本外 Sharpe 仅在 0.02 ~ 0.13，且宏观二值择时开关已证伪失效。**本项目已全线废除申万一级行业轮动策略**，全面升级下沉为**申万二级行业（SW L2）方向池轮动体系**，实现全周期年化收益 +15.38%、最大回撤压缩至 38.33%、Sharpe 提升至 0.58。

---

## 快速导航与知识地图

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                       【主路由与快速执行入口 (本文件)】                         │
│  • 申万二级核心量化原则 (Ground Truth)   • 常用命令速查 (CLI Cheat Sheet)       │
│  • 5 步标准执行 SOP                      • 核心状态决策矩阵 (Decision Matrix)   │
└───────────────────────────────────────┬────────────────────────────────────────┘
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
┌─────────────────────────┐┌─────────────────────────┐┌─────────────────────────┐
│ 二级因子特征定义        ││ 二级策略池与实盘 ETF    ││ 抱团瓦解与产业切换机制  │
│ [factor_definitions.md] ││ [strategy_pool.md]      ││ [crowding_mechanisms.md]│
│ 二级动量/拥挤度/供需象限││ guarded+hike 策略与 ETF ││ 15年浪潮与第一性原理    │
└─────────────────────────┘└─────────────────────────┘└─────────────────────────┘
                                        │
                                        ▼
                        ┌─────────────────────────┐
                        │ 跨周期审计与退役对账    │
                        │ [audit_guardrails.md]   │
                        │ 一级退役证据与二级门禁  │
                        └─────────────────────────┘
```

---

## 核心量化原则 (Ground Truth First)

1. **申万二级核心方向池单一信任源**：
   - 基本面与日行情黄金面板：[`data/curated/mart/industry_l2_panel_daily.parquet`](file:///Users/mac/workspace/personal/finance/stock/data/curated/mart/industry_l2_panel_daily.parquet)；
   - 策略与参数配置信任源：[`config/strategy/industry_trend_tracking.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/strategy/industry_trend_tracking.yaml)；
   - 核心主战场为 **16 个全球共振申万二级行业方向池**（半导体/通信设备/计算机设备/电池/乘用车/工业金属/贵金属/化学制药/医疗服务/化学原料/化学纤维/农化制品/工程机械/航运港口/电网设备/消费电子），有效消除高相关性冗余并精准映射场内 ETF。
2. **核心策略逻辑：动量排名进攻 + 组合防守门排雷**：
   - **进攻（选强）**：采用季度/双周动量 `return_60d` 降序排列，筛选排名最靠前的 Top 3 细分行业；
   - **拥挤度防守（排雷）**：成交额占比滚动历史分位 `tcr_percentile >= 85%` 启动**一票否决**。实测将样本外最大回撤从 42.11% 压缩至 25.80%，强力规避高位抱团踩踏；
   - **估值防守门**：`pe_ttm_ew_percentile_5y <= 90.0%`，剔除历史极端透支标的；
   - **宏观恐慌与加息防守**：恐慌指数突破阈值或美联储加息周期（FFR 6个月变化 $\ge 0.25\text{pp}$）时，组合自动降仓 50%，压低系统性波动。
3. **严格 T+1 与交易摩擦成本扣除**：
   - 信号于当日收盘（或 14:50 盘尾预判）生成，次日开盘按目标权重执行（T+1）；
   - 严格扣除券商佣金（万一，0.0001）与冲击滑点（万五，0.0005）；
   - 执行 **3% 调仓死区 (Deadband)** 过滤，杜绝无效微量换手磨损。
4. **真实场内 ETF 映射与代理折扣**：
   - 纯二级对标（如半导体、通信、电池、电网、创新药、黄金股、消费电子、工程机械）1:1 映射；
   - 代理替代（如无纯二级 ETF 时采用交通运输、中证医疗等）执行**实测跟踪差降权**，释放仓位转为现金管理。

---

## 常用量化命令速查 (CLI Cheat Sheet)

```bash
# 1. 申万二级策略回测：运行最优二级策略 (组合防守门 + 加息防守，年化 +15.38%, Sharpe 0.58)
make industry-trend-strategy STRATEGY=industry_l2_direction_guarded_hike
# 运行基础组合防守门策略 (年化 +14.59%, Sharpe 0.52, MaxDD 38.95%)
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction_guarded
# 查看所有可用申万二级策略列表
uv run python -m stock_cli.industry_trend_strategy --list

# 2. 14:50 盘尾实盘巡检：生成最新二级行业打分、目标持仓与场内 ETF 报单卡片 (含代理折扣)
make industry-trend-live
# 预览指定策略报单指令 (dry-run)
uv run python -m stock_cli.industry_trend_live --strategy industry_l2_direction_guarded --dry-run

# 3. 细分行业动量 × 拥挤度防守框架深度回测 (验证半导体/贵金属/工业金属防守增益)
uv run python scripts/industry_crowd_defense_framework.py

# 4. 现实景气与拥挤度防守复合对账实验
uv run python scripts/industry_prosperity_crowd.py

# 5. 刷新构建二级行业基本面面板 Mart (industry_l2_daily + L2 财务黄金表)
uv run python - <<'PY'
from stock_analytics.marts.builder import DomainMartBuilder
from stock_analytics.features.store import FeatureStore
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext
from pathlib import Path
b = DomainMartBuilder(
    catalog=DataCatalog(data_source="tushare"),
    store=FeatureStore(mart_dir=Path("data/curated/mart")),
    runtime=DataRuntimeContext.from_root("data"),
)
b.build_industry_l2_panel(overwrite=True)
PY
```

---

## 核心状态决策矩阵 (Decision Matrix)

| 细分行业所处状态 / 因子特征 | 核心量化指标特征 | 推荐激活策略/规则 | 推荐配置方向与动作 | 详细参考章节 |
| :--- | :--- | :--- | :--- | :--- |
| **景气动量领跑 / 估值安全** | `return_60d` 排名靠前 + `pe5y <= 80` | **`industry_l2_direction`** | 顶格配置 Top 3 核心二级赛道 | [`strategy_pool.md`](references/strategy_pool.md) |
| **赛道极度拥挤 / 交易过热** | `tcr_percentile >= 85%` | **`crowd_gate` (一票否决)** | **坚决剔除过热行业**，防范抱团瓦解与踩踏风险 | [`crowding_mechanisms.md`](references/crowding_mechanisms.md) |
| **产能过剩 / 供给无序扩张** | Capex 洪峰或剪刀差转负 | **`capex_gate` / `scissors_gate`** | 剔除供给过快扩张、毛利坍塌行业，保护本金 | [`factor_definitions.md`](references/factor_definitions.md) |
| **全球流动性收紧 / 加息周期** | FFR 6个月变化 $\ge 0.25\text{pp}$ | **`hike_gate` (加息防守)** | 组合总仓位主动缩放 50%，压制系统性下行风险 | [`strategy_pool.md`](references/strategy_pool.md) |
| **宏观系统性恐慌破位** | `panic_index >= 65.0` | **`panic_scale` (恐慌防守)** | 组合总仓位缩放 50%，规避极端流动性枯竭 | [`strategy_pool.md`](references/strategy_pool.md) |

---

## 标准执行 SOP (5 步工作流)

### Step 1: 检查与刷新二级行业基本面面板
确保申万二级基本面 Mart 数据为最新状态，检查 16 个核心二级行业覆盖完备：
```bash
uv run python -m stock_cli.industry_trend_strategy --list
```

### Step 2: 运行二级行业策略回测与绩效检验
运行带有组合防守门和加息防守的最优策略，核验全周期与样本外指标：
```bash
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction_guarded_hike
```
- 核验指标门槛：年化收益 $\ge 12\%$，最大回撤 $\le 40\%$，Sharpe $\ge 0.50$。

### Step 3: 14:50 盘尾实盘推演与 ETF 报单卡片生成
在交易日 14:50 盘尾运行巡检，生成最新的配置建议与场内 ETF 报单指令：
```bash
uv run python -m stock_cli.industry_trend_live --strategy industry_l2_direction_guarded --dry-run
```
- 查看报单卡片中的**目标权重**、**建议下单手数**与**代理折扣说明**。

### Step 4: 拥挤度与抱团风险排查
当某热门二级赛道（如半导体、贵金属、电网设备）涨幅巨大时：
1. 检查其 `tcr_percentile` 是否突破 85% 警戒线；
2. 运行 `uv run python scripts/industry_crowd_defense_framework.py`，查看该赛道叠加拥挤度防守后的表现；
3. 一旦触发 `crowd_gate`，自动剔除并顺延换入动量次优且拥挤度正常的二级行业。

### Step 5: 真实交易摩擦与执行监控
- 核验调仓是否满足 **3% 调仓死区 (Deadband)**，避免微量调仓磨损；
- 针对存在负跟踪差的代理 ETF（如交通运输、中证医疗），确认已自动扣除代理折扣转为现金管理。

---

## 专题进阶手册 (References)

专题深入文档：
1. [**申万二级量化因子定义与特征工程规范**](references/factor_definitions.md) —— 二级动量、时序拥挤度分位、估值赔率与产业腿供需剪刀差。
2. [**申万二级轮动策略池与 16 行业场内 ETF 映射**](references/strategy_pool.md) —— guarded 组合防守门、hike 加息防守机制与纯正对标 ETF 字典。
3. [**行业抱团演进规律与产业切换底层机制**](references/crowding_mechanisms.md) —— A 股 15 年 6 大抱团浪潮、拥挤度时序防守与第一性原理。
4. [**跨周期稳定性审计与一级行业退役依据**](references/audit_guardrails.md) —— 一级行业证伪数据证据、二级方向池 11 项质量与防退化门禁。
