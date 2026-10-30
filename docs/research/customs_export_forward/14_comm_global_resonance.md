# 14 通信设备（光模块）全球 AI 资本开支共振专题

> **定位**：通信设备（801102.SI，C 级 0.42）出口量价信号只覆盖光模块+网络设备，
> 全局方向判定必须回到**全球资本开支链**（industry-trend-tracking 拐点规则：
> 拐点正确信号 = 全球资本开支见顶，不来自 A 股内部）。
>
> **数据底座（本地黄金表，Ground Truth First）**：`data/curated/industry/` 下
> `cloud_capex_quarterly` / `semiconductor_equipment` / `semiconductor_lead` /
> `semiconductor_sales` / `semiconductor_equipment_gm` / `semiconductor_channel_inventory`。
>
> **复现**：`uv run python .agents/skills/customs-export-research/scripts/build_comm_global_resonance.py`
> → 产物 `data/analytics/industry/comm_global_resonance_panel.parquet`。
>
> **版本**：2026-09（海关出口口径 2026-07，全球信号 2026-Q2/2026-07）。

---

## 1. 光模块出口现状（海关侧，2026-07）

| 指标 | 值 | 结构解读 |
| :--- | :--- | :--- |
| 金额 yoy（3MMA） | **+33.5%** | 7 月回升（6 月 +25.3% → 7 月 +33.5%） |
| 量 yoy（3MMA） | **+3.5%** | 连续 5 个月个位数，二阶导"量增速回落"持续 4 个月 |
| 价 yoy（ASP，3MMA） | **+28.9%** | 增长切换为高端（800G/1.6T）提价驱动 |

**关键张力**：量能停滞 vs 金额回升——需要全球链判定这是"涨价换量的暂歇"还是"需求见顶的反转"。

---

## 2. 全球 6 信号共振表（最新 vs 上期）

| 信号 | 数据期 | 值 | 上期 | 趋势 | 状态 |
| :--- | :--- | ---: | ---: | :--- | :--- |
| 云 CapEx 合计 yoy | 2026-Q2 | **+87.0%** | +80.5% | 加剧 | 🟢 扩张 |
| SEMI 设备销售 3MMA yoy | 2026-07 | **+35.4%** | +26.9% | 加剧 | 🟢 扩张 |
| SIA 全球销售 yoy | 2026-06 | **+123.6%** | +107.4% | 加剧 | 🟢 扩张 |
| 台积电收入 yoy | 2026-07 | +44.7% | +67.9% | 缓解 | 🟢 扩张（高位） |
| 设备商毛利率 | 2026-Q2 | 54.0% | 53.0% | 加剧 | 🟢 定价权强 |
| 渠道库存 DOI | 2026-07 | 66.3 天 | 66.3 天 | 持平 | 🟢 健康（≤80） |

**拐点预警：无**（云 CapEx 与 SEMI 设备均加速扩张，无一转弱）。

云 CapEx 结构（十亿美元）：MSFT 35.8 / GOOG 44.9 / META 30.1 / AMZN 54.2——**四家全部环比抬升**，
无一家见顶；SEMI 设备 3MMA yoy 连续 5 个月加速（+2.7 → +35.4%），是资本开支"最先下单腿"的
最强先行信号。

---

## 3. 结论：量能回落 = 暂歇（涨价换量），非趋势反转

1. **需求端未破位**：云 CapEx yoy +87% 且加速，四家云厂商无一家见顶——光模块直接最终需求仍在扩张；
2. **先行腿更乐观**：SEMI 设备 3MMA yoy 五连升至 +35.4%，按"设备 → 晶圆产能 → 光模块需求"传导链，
   领先指标比光模块自身更健康；
3. **量能回落的结构解释**：量 +3.5%、价 +28.9% 是**高端单模块 ASP 上升带来的量速换挡**
   （800G/1.6T 替换低端），不是需求萎缩；
4. **反转证据链不成立**：趋势反转应伴随云 CapEx 减速、SEMI 设备转负、台积电回落——三者当前全部向上。

**处置**：维持"量增速连续回落 = 二阶导预警，但全球链未证实见顶"的持有观察定调；不追加、不退出。

---

## 4. 数据源说明（Ground Truth First）

| 信号 | 原始源 | 本地表 | 关键字段 |
| :--- | :--- | :--- | :--- |
| 云 CapEx | 四家云厂商季度财报（10-Q/10-K） | `cloud_capex_quarterly` | `total_capex_billion_usd / yoy_growth` |
| SEMI 设备 | SEMI 月度设备销售报告 | `semiconductor_equipment` | `billings_3mma_jpy / yoy_growth_3mma` |
| 台积电收入 | TSMC 月度营收新闻稿 | `semiconductor_lead` | `tsmc_revenue_usd_million / tsmc_revenue_yoy` |
| SIA 销售 | WSTS/SIA 月度销售蓝皮书 | `semiconductor_sales` | `global_sales_usd / yoy_growth` |
| ASML 毛利率 | ASML 季度财报 | `semiconductor_equipment_gm` | `gross_margin_pct` |
| **渠道 DOI** | **SEC EDGAR XBRL Companyfacts API**（Arrow Electronics ARW / Avnet AVT 两家全球电子元器件分销商季度 10-Q 的 `Inventory` / `CostOfRevenue`） | `semiconductor_channel_inventory` | `channel_weighted_doi_days` |

**渠道 DOI 口径**：`个股 DOI = 期末存货 / 季度营业成本 × 90`；`渠道加权 DOI = Σ两家存货 / Σ两家营业成本 × 90`
（规模加权合成，2026Q2：Avnet 6069M/7430M→73.5 天，Arrow 5940M/8867M→60.3 天，合并 **66.3 天**）。

**两个边界**：
1. **这是分销渠道库存，不是芯片厂库存**——反映下游备货/去化压力，与 IDM 库存数据集
   （`semiconductor_inventory_days`，同为 SEC 源、样本为半导体厂商）是两回事；
2. **80 天"健康"阈值是分位经验标尺，非权威口径**：渠道加权 DOI 全历史（2009 起，134 个观测）
   p25=40.6 / 中位 53.7 / **p90=77.5 / max=85.9**——80 天≈历史上沿，作警觉阈值合理；
   方法论文档的 IDM regime 划分（105/130/150 天，`inventory.py:20`）适用于芯片厂、不适用于分销渠道。

---

## 5. 月度跟踪清单（升级拐点预警的三道闸）

| 顺序 | 指标 | 升级阈值 | 数据期 |
| :--- | :--- | :--- | :--- |
| ① | 云 CapEx 下季 yoy | < +70%（较本期明显失速） | 2026-Q3，10 月底披露 |
| ② | SEMI 设备 3MMA yoy | < +20% 或单期回落 >10pp | 月度 |
| ③ | 光模块量 yoy | 重新转负并持续 2 个月 | 月度 |

三道闸任一触发 → 光模块量能拐点由"暂歇"升级为"反转预警"，通信设备处置转"减仓观察"。

---

## 6. 与海关出口研究视角的衔接

- 通信设备 L2 观察表：金额 +6.0%、量 -11.8%——**"量回落 × 财报加速"最危险组合警示**
  （历史 6m 中位 -7.9%），但本专题证据显示该组合的下跌风险被全球外需扩张对冲；
- 分子结构：光模块（+33.5%，量 +3.5%）与网络设备（+1.0%，量 -13.4%）分化——网络设备量缩更显著，
  对应交换机/路由需求走弱，光模块仍由 AI 集群建设支撑；
- 一致率 C 级（0.42）边界不变：出口信号不代表通信设备行业整体财报方向，光模块仅作全球 AI
  资本开支方向性观测。
