---
name: industry-trend-tracking
description: 申万二级行业产业趋势跟踪技能。跟踪周期尺度（季度/半年）全球资本开支方向（费半 SOX/光伏装机/半导体销售额/新能源车销量/变压器出口/创新药BD等）在 A 股供应链二级行业（半导体/通信设备/计算机设备/光伏设备/电池/汽车等全球共振方向池）的承接与确认，选景气行业=深研线簇（有产业供需腿行业用剪刀差 LONG + DOI 激活选行业并自带择时，当前半导体完整实证、化工/计算机有腿待推广）+ 无腿行业动量 Top3 兜底（`return_60d` + 估值/组合防守门，滞后不宣称前瞻），产业供需数据（供需剪刀差/产业数据腿）作前瞻确认，财报层（量价齐升/毛利率扩张）仅作滞后事后验证不作前瞻选股，现实景气仅面板列/事后确认，输出趋势跟踪持仓与拐点预警（全球方向仅作可选加权）。当用户询问产业趋势、全球景气共振、真景气行业跟踪、资本开支方向、景气拐点预警或产业趋势回测时使用此技能。
---

# Industry Trend Tracking (申万二级行业产业趋势跟踪)

本技能定义申万二级行业在**周期尺度（季度/半年）全球产业趋势确认与跟踪**中的端到端标准操作流 (SOP)
与量化工程规范。主战场为**全球共振方向池 16 个二级行业**（半导体/通信设备/计算机设备/电池/
汽车/工业金属/贵金属/化学制药/医疗服务/化学原料/化学纤维/农化制品/
工程机械/航运港口/电网设备/消费电子，即 `_THEME_L2_CODE` 覆盖行业中去重后的成员；
电网设备对应 `159326.SZ` 华夏中证电网设备主题ETF，医疗服务对应 `512170.SH` 华宝中证医疗ETF 主题代理，
消费电子对应 `159732.SZ` 国泰中证消费电子主题ETF，纯二级对标 gap -0.65%）。
它与 [`industry-rotation-strategy`](../industry-rotation-strategy/SKILL.md) 是两套独立体系：

| 维度 | 行业轮动 (rotation) | 产业趋势跟踪 (trend tracking) |
| :--- | :--- | :--- |
| 尺度 | 20-60 日截面博弈 | 季度/半年周期 |
| 矛盾 | A 股内部截面矛盾 | 全球资本开支方向 × A 股供应链承接 |
| 主信号 | 动量/剪刀差/拥挤度 | 深研线簇：有腿行业产业腿激活（剪刀差 LONG + DOI）+ 无腿行业动量 Top3 兜底（`return_60d` + 估值/组合防守门）+ 财报滞后验证（供需/议价权，事后确认）+ 估值防守（全球方向仅可选加权）|
| 目标 | 轮动超额 | 真景气产业的趋势确认与拐点预警 |

---

## 快速导航

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     【主路由与快速执行入口 (本文件)】                      │
│  • 深研线簇+动量兜底(选行业)   • 常用命令速查 (CLI Cheat Sheet)    │
│  • 5 步标准执行 SOP               • 拐点预警决策矩阵                      │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
┌──────────────────────┐┌──────────────────────┐┌──────────────────────┐
│ 深研线簇+动量兜底     ││ 因子计算定义          ││ （预留：全球数据接入）│
│ [framework.md]       ││ [factor_definitions.md]││                       │
│ 半导体实盘·化工待推广 ││ 量化因子 + 动量/估值  ││                       │
└──────────────────────┘└──────────────────────┘└──────────────────────┘
```

---

## 核心量化原则 (Ground Truth First)

1. **选景气 = 深研线簇（产业腿激活）+ 无腿动量兜底**（详见 [`framework.md`](references/framework.md) §0 断层收缩标注）：
   - **选景气行业**：有产业供需腿行业用**剪刀差 LONG + DOI 激活**入选并自带择时（当前半导体完整实证、化工/计算机有腿待推广）；无腿行业用 `return_60d` 动量 Top3 + 估值/组合防守门兜底（滞后，不宣称前瞻），季度调仓；**注意：现实景气=业绩预告/快报，仅作面板列与事后确认，不参与实盘选股；统一 16 行业横截面前瞻不可行（各行业驱动机制不同、产业腿覆盖仅 5/17）**（详见 framework.md §0 断层标注）；
   - **财报滞后验证（量价齐升）**：公司经营与财报是滞后数据，仅事后验证供需逻辑是否兑现（量价齐升 = 营收 + 净利双正，取自理杏仁 L2 财务黄金表
     `sw_2021_l2_fs_*` 的 `toi.ttm_y2y` / `np.ttm_y2y`），不作前瞻选股；
   - **财报滞后验证（毛利率扩张）**：同样为滞后数据，仅事后验证定价权/盈利质量（毛利率扩张 = 净利增速 > 营收增速，微笑曲线偏上非代工）；
   - **前瞻确认依靠产业数据，不靠财报**：真景气的前瞻指导来自产业供需剪刀差（demand − supply，如半导体 TSMC+SIA−SEAJ）与产业数据腿（见 §1），财报仅作滞后确认；
   - **「全球方向」仅作可选关注加权，不作判定层**（数据现状见 framework.md §1，实证方向分 IC 弱、防守变体均不优于 baseline）。
2. **方向池优先**：主战场是 16 个全球共振二级行业（半导体/通信设备/计算机设备/电池/乘用车/
   工业金属/贵金属/化学制药/医疗服务/化学原料/化学纤维/农化制品/
   工程机械/航运港口/电网设备/消费电子），由 `theme_etf_direction.parquet` 与
   watchlist 精确映射到场内 ETF 执行（纯二级对标优先，无纯二级 ETF 时采用一级 ETF 或主题 ETF 代理并透明披露偏差）。
   去重依据：19 行业实测收益相关性聚类（化工 5 兄弟 0.74-0.91 / 医药 3 姐妹 0.77-0.87 / TMT 0.72-0.82 /
   新能源 0.77），剔除高相关成员 光伏/生物制品/化学制品/塑料，池内平均相关从 0.607 降至 0.52 左右；
   2026-09 纳入 消费电子 270500（159732.SZ 实测纯正对标 gap -0.65%）。
3. **动量 Top3 + 估值防守**：季度调仓按动量（`return_60d`）取 Top3，叠加估值防守
   （`pe_ttm_ew_percentile_5y` 高位剔除）。16 行业方向池全周期年化收益 +5.42%
   （扩池与去重历程：13 行业 +12.50% → 14 行业 +7.91% → 19 行业 +4.36% → 15 去重 +5.43% → 16 含消费电子 +5.42%；
   guarded 防守门样本外 Sharpe 0.18→0.42 且全周期 +15.10%（供需象限加成后，16 行业口径 +12.71%），见 `industry_supply_demand_quadrant.md`），以 16 行业实测为准。
4. **财报滞后验证（量价齐升）在 16 行业方向池不作硬门**：量价齐升硬门/加分均不优于 baseline（16 行业实测：硬门全周期 12.83% vs 基线 6.49%，单独生效于 qlq 口径），
   保留为持仓观察与拐点预警信号；量价齐升作为横截面因子（需求驱动 > 供给收缩）在全行业截面成立（财报滞后数据，事后验证）。
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

# 3. 二级方向池量价齐升判定与组合回测（财报滞后验证/方向层接入验证）
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
| 产业腿激活（剪刀差 LONG + DOI）或动量兜底 Top3 通过 + 财报滞后验证通过（量价齐升/毛利率扩张） | 有腿产业剪刀差看多 / 无腿动量靠前 + 财报事后验证供需兑现 | 持有真景气二级行业，季度再平衡 |
| 全球资本开支见顶（SOX/装机/出货转弱） | 方向层转负 | **拐点预警**：减仓/退出，不赌 A 股内部反弹 |
| 财报滞后验证破坏（营收或净利转负） | 财报滞后验证转负 | 剔除供给收缩/双负行业（事后确认，不作前瞻扳机） |
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
检查 16 个方向行业（半导体 270100 / 通信设备 730200 / 计算机设备 710100 / 电池 630700 /
汽车=乘用车 280500 / 工业金属 240300 / 贵金属 240400 / 化学制药 370100 / 医疗服务 370600 /
化学原料 220200 / 化学纤维 220400 / 农化制品 220800 /
工程机械 640600 / 航运港口 421100 / 电网设备 630800 / 消费电子 270500）在 `sw_2021_l2_fs_non_financial` 中的报告期覆盖（19-25 期，2020Q1 ~ 2026Q1）。

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
新增产业数据腿前先读 `references/framework.md`「产业数据腿构建原则」：只用实物流量类不用价格类、
按领先链条排权重、与需求端配对成剪刀差、新腿按 leg_type 独立分组（demand 与 price 不合成）。

### Step 3: 回测二级方向池策略
```bash
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction
uv run python -m stock_cli.industry_trend_strategy --list
```
- 基线（`industry_l2_direction`）：动量 Top3 + 估值防守（return_60d + pe5y<=90），
  全周期年化收益 +5.43%（13 行业时代 +12.50%，扩池稀释后去重回升）；
- 变体（`industry_l2_direction_qlq`）：量价齐升硬门——16 行业全周期 +12.83%，样本外（2022 后）
  Sharpe 0.41 vs 基线 0.19（CAGR 归一化口径），财报滞后验证（量价齐升）唯一正例，保留参考；
- 主推（`industry_l2_direction_guarded`）：capex 洪峰 + 拥挤度一票否决 + **供需象限动量加成** +
  恐慌降仓组合防守门，16 行业全周期 +12.71% / 样本外 Sharpe 0.18→0.42 / MaxDD 36%（见
  `industry_supply_demand_quadrant.md` 与 `industry_capex_combo.md`）；
- 改进方向（未落地）：价格驱动板块（贵金属/工业金属/航运）波动率意识——vol targeting 降权 +
  分板块拥挤度阈值收紧至 80，见 `references/framework.md`「价格驱动板块的波动率意识」；
- 已停用（`industry_l2_direction_gate`）：方向防守门全周期/样本外双弱（IC 无预测力），
  方向分定位为拐点预警信号不作策略门。

> **基线定位（重要）**：`industry_l2_direction` 是**零假设对照组（回测参照系），不是推荐/生产策略**。
> 它是假设最少的锚（只信动量 + 估值防守），让 qlq（样本外 0.36）、guarded（0.41）的增量可被归因
> （防守门 +0.23、量价齐升 +0.18）。基线弱是它的职责：全周期 +5.42% / 样本外 0.18 正是"当前 16 行业
> 池下裸动量的自然水平"，任何叠加层的有效性都以超越它为判据。yaml 保留基线仅用于①回测对账完整对比表、
> ②数据/代码回归检查（基线漂移 = 数据或代码问题，与策略好坏无关）。**生产执行一律走 guarded**
> （live 巡检命令 `--strategy industry_l2_direction_guarded`），基线只在分析层存在，勿当推荐策略使用。

### Step 4: 验证样本外稳定性
所有改进必须用 2022-01-01 之后样本外检验（对齐国泰海通拆分），不拿全样本刷参数。
样本内 0.47 / 样本外 0.15 的「分析师预期」就是反例。

### Step 5: 深研线簇选行业 + 财报滞后验证 + 拐点预警
对候选行业按 [`framework.md`](references/framework.md) 做**深研线簇**：有产业供需腿行业用剪刀差 LONG + DOI 激活入选并择时（半导体完整实证，化工/计算机有腿待推广，见 `framework_semiconductor.md`）；无腿行业用 `return_60d` 动量 Top3 + 估值/组合防守门兜底（滞后，不宣称前瞻）
并叠加财报滞后验证（量价齐升 / 毛利率扩张，事后确认，不作前瞻选股）；「全球方向」仅作可选加权与拐点预警参考。
全球指标（SOX/装机/出货/销量）见顶 → 方向分转负 → 触发拐点预警减仓/退出（不作买入判定）。

---

## 渐进式深入阅读清单 (References)

1. [**半导体方法论总览（先读）**](references/semiconductor/semiconductor_trading_methodology.md) —— 剪刀差双轨定位稳定 vs 证伪的统一交易方法论总览。
2. [**半导体剪刀差方法论（证据明细）**](references/semiconductor/archive/methodology_overview.md) —— 双轨定位、一句话定稿（已归档）。
3. [**研究路线图（下一步做什么）**](references/semiconductor/archive/research_roadmap.md) —— 保留研究的优先级：跨行业推广 > 机制深挖 > 数据补漏，及四条否决线（已归档）。
4. [**机制深挖：剪刀差失效与供给腿真实机制**](references/semiconductor/archive/mechanism_factor_saturation.md) —— IC 失效/翻转机制的修正实证（剪刀差失效=高 std；inventory 只在贴顶区有效）（已归档）。
5. [**产业趋势量化框架**](references/framework.md) —— 深研线簇（产业腿激活选行业）+ 无腿动量兜底、财报滞后验证（供需/议价权）、全球方向（可选加权/数据现状）、产业数据腿构建原则。
6. [**因子计算定义**](references/factor_definitions.md) —— 量化因子 + 动量/估值 + 拥挤度的公式与数据来源。
7. [**半导体剪刀差方法论（已归档，证据明细）**](references/semiconductor/archive/framework_semiconductor.md) —— 完整回测表、财报传导链、供给端确认腿原始实证。
8. [**光伏产业规律与核心命题**](references/photovoltaic/core_proposition.md) —— 结构化配合（防守门 × 生命周期定位）而非单一信号。
9. [**光伏价格链机制与环节传导**](references/photovoltaic/price_chain_mechanism.md) —— InfoLink 价格链量纲折算、电池片领先硅料 9 周传导实证、买入因子证伪与三源防守门定位。
10. [**光伏周期一阶导与二阶导信号框架**](references/photovoltaic/cycle_derivative_framework.md) —— 零阶导（水平）、一阶导（速度）与二阶导（加速度/拐点）投研矩阵、四维观测指标（价格/剪刀差/库存/需求）与四象限状态机。
11. [**光伏产业季节性规律与大周期从属机制**](references/photovoltaic/seasonality_patterns.md) —— 供给端丰枯期电价成本律动、国内气候与央国企“1231”考核节律、全球外需夏休/财年差异，以及“季节性永远服从于产能大周期”实操铁律。
12. [**光伏制造能耗强度与电力经济学**](references/photovoltaic/energy_intensity_and_power_economics.md) —— 运行端绿电与制造端超级能耗双重属性、单瓦 0.4 度耗电模型、能量回收期（EPBT/EROI）科学测算、电价敏感度（0.1元=5500元成本）与产业地理三代迁徙史。

---

## 实证锚点（本地可复现）

| 结论 | 证据 |
| :--- | :--- |
| **基线定位：对照非产品** | `industry_l2_direction` 是零假设对照组（回测参照/回归检查用），**生产执行只走 guarded**；基线弱是职责（见 Step 3 基线定位说明） |
| 二级方向池动量 Top3 + 估值防守 | 16 行业方向池（return_60d + pe5y<=90），全周期（2020-05 起）年化 +5.42%（去重历程：13 行业 +12.50% → 19 行业 +4.36% → 15 去重 +5.43% → 16 含消费电子 +5.42%；guarded 全周期 +12.71% / 样本外 0.42（含供需象限加成），见 `industry_supply_demand_quadrant.md`） |
| 量价齐升在方向池小池不作硬门 | 硬门与加分均弱于 baseline；保留为持仓预警信号（实测） |
| 方向防守门不作策略门 | 高位×非量价齐升剔除弱于 baseline；保留为拐点预警（实测） |
| 需求驱动 > 供给收缩 | 未来 20 日 +0.74% vs +0.29%（供给收缩最差象限，全行业截面成立） |
| 拥挤度样本外风险翻倍 | tcr IC -2.24% → -5.88% |
| A 股内部信号做不出拐点 | 拥挤度滞后、环比噪声大，退出全劣于不退出 |
