---
name: industry-trend-tracking
description: 申万二级行业产业趋势跟踪技能。跟踪周期尺度（季度/半年）全球资本开支方向（费半 SOX/光伏装机/半导体销售额/新能源车销量/变压器出口/创新药BD等）在 A 股供应链二级行业（半导体/通信设备/计算机设备/光伏设备/电池/汽车等全球共振方向池）的承接与确认，以三层共振框架（全球方向 × 量价齐升 × 议价权）+ 动量 Top3 + 估值防守确认真景气二级行业，输出趋势跟踪持仓与拐点预警。当用户询问产业趋势、全球景气共振、真景气行业跟踪、资本开支方向、景气拐点预警或产业趋势回测时使用此技能。
---

# Industry Trend Tracking (申万二级行业产业趋势跟踪)

本技能定义申万二级行业在**周期尺度（季度/半年）全球产业趋势确认与跟踪**中的端到端标准操作流 (SOP)
与量化工程规范。主战场为**全球共振方向池 13 个二级行业**（半导体/通信设备/计算机设备/光伏设备/电池/
汽车/工业金属/贵金属/化学制药/生物制品/工程机械/航运港口/电网设备，即 `_THEME_L2_CODE` 覆盖的行业；
电网设备对应 `159326.SZ` 华夏中证电网设备主题ETF）。它与 [`industry-rotation-strategy`](../industry-rotation-strategy/SKILL.md) 是两套独立体系：

| 维度 | 行业轮动 (rotation) | 产业趋势跟踪 (trend tracking) |
| :--- | :--- | :--- |
| 尺度 | 20-60 日截面博弈 | 季度/半年周期 |
| 矛盾 | A 股内部截面矛盾 | 全球资本开支方向 × A 股供应链承接 |
| 主信号 | 动量/剪刀差/拥挤度 | 全球方向 × 量价齐升 × 议价权 + 动量/估值 |
| 目标 | 轮动超额 | 真景气产业的趋势确认与拐点预警 |

---

## 快速导航

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     【主路由与快速执行入口 (本文件)】                      │
│  • 三层共振框架 (Ground Truth)    • 常用命令速查 (CLI Cheat Sheet)       │
│  • 5 步标准执行 SOP               • 拐点预警决策矩阵                      │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
┌──────────────────────┐┌──────────────────────┐┌──────────────────────┐
│ 三层共振框架          ││ 因子计算定义          ││ （预留：全球数据接入）│
│ [framework.md]       ││ [factor_definitions.md]││                       │
│ 方向×供需×议价权     ││ 三层因子 + 动量/估值  ││                       │
└──────────────────────┘└──────────────────────┘└──────────────────────┘
```

---

## 核心量化原则 (Ground Truth First)

1. **三层共振框架是唯一判定标准**（详见 [`framework.md`](references/framework.md)）：
   - **方向层**：资本开支是不是全球性的（全球景气代理向上：费半 SOX / 光伏装机 / 半导体销售额 / 新能源车销量 /
     变压器出口 / 创新药出海 BD / 挖机产销 / 海运运价）；
   - **供需层**：承接的是需求驱动还是产能过剩（量价齐升 = 营收 + 净利双正，取自理杏仁 L2 财务黄金表
     `sw_2021_l2_fs_*` 的 `toi.ttm_y2y` / `np.ttm_y2y`）；
   - **议价权层**：这个制造环节有没有定价权（毛利率扩张 = 净利增速 > 营收增速，微笑曲线偏上非代工）。
   **三层同时成立才是「真全球景气」**；只满足方向（如光伏产能过剩）不是真 alpha。
2. **方向池优先**：主战场是 12 个全球共振二级行业（半导体/通信设备/计算机设备/光伏设备/电池/汽车/
   工业金属/贵金属/化学制药/生物制品/工程机械/航运港口），由 `theme_etf_direction.parquet` 与
   watchlist 精确映射到场内 ETF 执行（无精确主题的行业归并到一级主题 ETF），不在全市场撒网。
3. **动量 Top3 + 估值防守**：季度调仓按动量（`return_60d`）取 Top3，叠加估值防守
   （`pe_ttm_ew_percentile_5y` 高位剔除）。6 行业池全周期（2020-05 起）Sharpe 0.72；
   扩池至 12 行业后集中度下降（Sharpe 0.52），以 12 行业实测为准。
4. **供需层在 12 行业小池不作硬门**：量价齐升硬门/加分均不优于 baseline，
   保留为持仓观察与拐点预警信号；量价齐升作为横截面因子（需求驱动 > 供给收缩）在全行业截面成立。
5. **方向层作防守/预警，不作进攻加分**：全球方向分与未来收益显著负相关（追高反向），
   高位 × 非量价齐升是最差象限；方向防守门（高位剔除）实证弱于 baseline，保留为拐点预警信号。
6. **拥挤度防守**：成交额占比高位一票否决/减仓，样本外风险翻倍，防守可把回撤 42% → 26%。
7. **严格 T+1 与摩擦成本**：信号当日收盘生成，次日开盘执行，扣佣金（万一）+ 滑点（万五）+ 3% 调仓死区。
8. **拐点预警来自全球指标，不来自 A 股内部**：拥挤度滞后、环比噪声大，A 股内部信号做不出拐点
   （已验证全劣于不退出）。拐点的正确信号是「全球资本开支见顶」。

---

## 常用命令速查 (CLI Cheat Sheet)

```bash
# 1. 二级方向池策略回测（读 industry_l2_panel_daily）
make industry-trend-strategy STRATEGY=industry_l2_direction
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction_qlq
uv run python -m stock_cli.industry_trend_strategy --list

# 2. 盘尾实盘巡检：生成 ETF 报单卡片（二级行业 → 场内 ETF 映射）
make industry-trend-live
uv run python -m stock_cli.industry_trend_live --strategy industry_l2_direction --dry-run

# 3. 二级方向池量价齐升判定与组合回测（供需层/方向层接入验证）
uv run python scripts/industry_l2_direction_qlq.py

# 4. 生成二级方向分映射（阶段 3：_THEME_L2_CODE × _THEME_SIGNAL）
uv run python scripts/industry_direction_map.py

# 5. 构建二级行业基本面面板 Mart（industry_l2_daily + L2 财务黄金表）
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

## 拐点预警决策矩阵

| 全球景气状态 | 核心信号特征 | 产业趋势动作 |
| :--- | :--- | :--- |
| 全球资本开支向上 + 量价齐升 + 毛利率扩张 | 三层共振全成立 | 持有真景气二级行业，季度再平衡 |
| 全球资本开支见顶（SOX/装机/出货转弱） | 方向层转负 | **拐点预警**：减仓/退出，不赌 A 股内部反弹 |
| 量价齐升破坏（营收或净利转负） | 供需层转负 | 剔除供给收缩/双负行业 |
| 拥挤度极端（tcr ≥ 85%） | 防守信号 | 一票否决过热行业 |

---

## 标准执行 SOP (5 步工作流)

### Step 0: 核对二级方向池数据（L2 财务黄金表）
```bash
uv run python - <<'PY'
from datetime import date
from stock_data.catalog import DataCatalog
cat = DataCatalog(data_source="lixinger")
for ds in ["sw_2021_l2_fs_non_financial", "sw_2021_l2_fs_bank",
           "sw_2021_l2_fs_security", "sw_2021_l2_fs_insurance"]:
    df = cat.load_dataset(ds, start_date=date(2020, 1, 1), end_date=date(2026, 8, 14))
    print(ds, len(df), df["trade_date"].min(), "~", df["trade_date"].max())
PY
```
检查 12 个方向行业（半导体 270100 / 通信设备 730200 / 计算机设备 710100 / 光伏设备 630500 / 电池 630700 /
汽车=乘用车 280500 / 工业金属 240300 / 贵金属 240400 / 化学制药 370100 / 生物制品 370300 /
工程机械 640600 / 航运港口 421100）在 `sw_2021_l2_fs_non_financial` 中的报告期覆盖（19-25 期，2020Q1 ~ 2026Q1）。

### Step 1: 构建/核对二级行业基本面面板（阶段 1 产物）
```bash
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
产物：`data/curated/mart/industry_l2_panel_daily.parquet`（18 字段，2014-01 ~ 2026-08），
含 `return_60d` / `pe_ttm_ew_percentile_5y` / `revenue_growth_ttm` / `profit_growth_ttm` /
`supply_demand_score` / `bargaining_score` / `crowding_score` / `direction_score`。

### Step 2: 生成二级方向分映射（阶段 3）
```bash
uv run python scripts/industry_direction_map.py
```
生成 `data/curated/mart/global_resonance_l2_map.parquet`（理杏仁码二级行业方向分，
`_THEME_L2_CODE × _THEME_SIGNAL` 映射，信号腿缺失自动跳过）与 `theme_etf_direction.parquet`。

### Step 3: 回测二级方向池策略
```bash
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction
uv run python -m stock_cli.industry_trend_strategy --list
```
- 基线（`industry_l2_direction`）：动量 Top3 + 估值防守（return_60d + pe5y<=90），
  全周期（2020-05 起）Sharpe 0.72；
- 变体（`industry_l2_direction_qlq` / `industry_l2_direction_gate`）：量价齐升硬门 / 方向防守门
  （实证弱于 baseline，参考对比）。

### Step 4: 验证样本外稳定性
所有改进必须用 2022-01-01 之后样本外检验（对齐国泰海通拆分），不拿全样本刷参数。
样本内 0.47 / 样本外 0.15 的「分析师预期」就是反例。

### Step 5: 三层共振确认真景气 + 拐点预警
对候选行业按 [`framework.md`](references/framework.md) 做三层判定：
方向（全球 capex 向上）× 供需（量价齐升）× 议价权（毛利率扩张），三者缺一不可。
全球指标（SOX/装机/出货/销量）见顶 → 方向层转负 → 触发拐点预警减仓/退出。

---

## 渐进式深入阅读清单 (References)

1. [**三层共振框架**](references/framework.md) —— 方向 × 供需 × 议价权的判定标准、全球景气代理与申万二级行业映射、光伏反例。
2. [**因子计算定义**](references/factor_definitions.md) —— 三层因子 + 动量/估值 + 拥挤度的公式与数据来源。

---

## 实证锚点（本地可复现）

| 结论 | 证据 |
| :--- | :--- |
| 二级方向池动量 Top3 + 估值防守 | 6 方向行业池（return_60d + pe5y<=90），全周期（2020-05 起）Sharpe 0.72（见 `industry_l2_direction_qlq.md`） |
| 量价齐升在 6 行业小池不作硬门 | 硬门 0.72→0.45、加分 0.69，均弱于 baseline；保留为持仓预警信号（实测） |
| 方向防守门不作策略门 | 高位×非量价齐升剔除 0.46，弱于 baseline；保留为拐点预警（实测） |
| 需求驱动 > 供给收缩 | 未来 20 日 +0.74% vs +0.29%（供给收缩最差象限，全行业截面成立） |
| 拥挤度样本外风险翻倍 | tcr IC -2.24% → -5.88% |
| A 股内部信号做不出拐点 | 拥挤度滞后、环比噪声大，退出全劣于不退出 |
