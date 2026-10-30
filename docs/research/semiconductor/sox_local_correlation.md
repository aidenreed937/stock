# SOX 与本地半导体垂直产业黄金表相关性研究

> 研究问题：费城半导体指数（SOX，`^SOX`）和本地什么半导体产业数据相关？
> 数据底座：本地 Curated 黄金表（`data/curated/industry/semiconductor/`）与 SOX 日频 Mart
> （`data/curated/mart/global_macro_daily.parquet`）。
> SOX 覆盖 2014-08 ~ 2026-09（146 月 / 48 季）；黄金表覆盖见 §2。
> 复核日期：2026-09（本报告数字均来自本地落盘，未使用外部未核验数值）。
> 时代驱动配置：`config/industry/semiconductor/demand_drivers.yaml`（2023 起 = AI/HPC 时代）。

## 一、核心结论（摘要）

1. **与 SOX 最相关的是"价格弹性类 + 同步销售额 + 设备商毛利"三条路径**，库存 DOI 呈弱逆周期：
   - SOX **12 个月动量**与内存价格 YoY（NAND 0.813 / DDR4 0.557 / DDR5 0.481）、
     中国区销售额 YoY（0.654）、台湾存储营收 YoY（0.60~0.66）、亚太区 YoY（0.619）、
     全球销售额 YoY（0.555）高度正相关——这是"周期共振"维度，SOX 与全球产业增速同向。
   - SOX **月收益**的同期相关普遍较弱，最强的是 DDR4/DDR5 代际比价（Spearman 0.371，p=0.013）、
     DDR5 现货 YoY（0.204）、ASML 季度毛利率（0.178）、全球销售额 MoM（0.157）、
     台积电先进制程晶圆占比（0.154）、内存现货 YoY（0.138~0.152）。
2. **领先-滞后结构分化（本研究所获最重要结构事实）**：
   - **SOX 领先**：SEMI 全球/中国区设备出货 YoY（领先约 3 季，rho 0.44~0.46，p<0.01）、
     SEMI 全球出货 QoQ（0.38~0.45）、全球销售额 MoM（-4 月，0.26~0.30）、
     DDR5/NAND 现货价 YoY（-5 月，0.26~0.39）——符合"美股提前定价、资本开支/销售额滞后确认"。
   - **指标领先 SOX**：DDR4/NAND 现货价 MoM（+4 月，0.28~0.39）、DDR4/DDR5 代际比价（+1 月，0.39）、
     台湾存储营收 MoM（+2~6 月）、IDM 等权/模拟 DOI（+3 季，0.25~0.26）——价格弹性与库存边际
     是少数对 SOX 有领先倾向的本地序列。
3. **AI 时代（2023+）明显换挡**：云 CapEx QoQ、SEMI 设备 YoY、ASML 净销售额 YoY 与 SOX
   收益的关系由"SOX 领先"变为弱/负相关（n 仅 13~14，需谨慎）；中国区与台湾存储 YoY 与
   SOX 12M 动量的共振进一步增强（0.65~0.78）；渠道 DOI 同期转强负相关（-0.464，p=0.094）。
4. **不构成交易信号**：同期相关性绝对值普遍 <0.4，且与既有 `semi_sox_backtest` 结论一致
   （产业实物流量腿对 SOX 未来 60 日收益无稳定预测力，全周期 IC -0.10 左右）——
   本报告的领先项（内存价格 MoM、比价）是描述性关联，需独立因子验证后才可考虑使用。

## 二、数据与方法（口径披露）

### 2.1 SOX 口径

- 来源：`data/curated/mart/global_macro_daily.parquet`（`sox_close`，yfinance `^SOX`）。
- 月频：取每月最后一个交易日收盘 → `sox_mom`（月收益）、`sox_yoy12`（12 个月动量）。
- 季频：取 3/6/9/12 月末收盘 → `sox_qret`（季度收益）。

### 2.2 黄金表口径与参与情况

16 张黄金表中 **14 张参与相关计算（49 条指标序列）**，2 张因样本不足仅披露：

| 表 | 分类 | 频次 | 参与指标数 | 覆盖（本地落盘） | 状态 |
| :-- | :-- | :-- | --: | :-- | :-- |
| semiconductor_sales | sales | 月 | 7（全球/分区域 YoY、MoM） | 1986-02 ~ 2026-06 | ✅ |
| semiconductor_lead | sales | 月 | 3（TSMC 营收 YoY/MoM/3MMA YoY） | 2014-01 ~ 2026-08 | ✅ |
| cloud_capex_quarterly | sales | 季 | 2（北美四大云厂 CapEx YoY/QoQ） | 2018-06 ~ 2026-06 | ✅ |
| semiconductor_equipment | equipment | 月 | 2（SEAJ 设备出货 YoY/MoM） | 2015-01 ~ 2026-07 | ✅ |
| semiconductor_equipment_semi | equipment | 季 | 4（全球/中国区出货、QoQ、占比） | 2016-03 ~ 2026-06 | ✅ |
| semiconductor_equipment_gm | equipment | 季 | 2（ASML GM/净销售额 YoY） | 2015-12 ~ 2026-06 | ✅ |
| semiconductor_equipment_gm_multi | equipment | 季 | 4（LRCX/KLAC/AMAT/TEL GM） | 2012-03 ~ 2026-12 | ✅ |
| foundry_capacity_utilization | capacity | 季 | 2（加权/台积电利用率） | 2016-03 ~ 2026-03 | ✅ |
| chip_lead_time | capacity | 月 | 3（交期水平/MoM、MCU 交期） | 2018-01 ~ 2026-08 | ✅ |
| tsmc_advanced_packaging_revenue | capacity | 季 | 3（封测 YoY、HPC/先进制程占比） | 2018-03 ~ 2026-06 | ✅ |
| semiconductor_inventory_days | inventory | 季 | 4（IDM 加权/等权/存储/模拟 DOI） | 2016-03 ~ 2026-06 | ✅ |
| semiconductor_channel_inventory | inventory | 季 | 1（渠道加权 DOI） | 2009-06 ~ 2026-06 | ✅ |
| semiconductor_memory_benchmark | price | 月 | 7（DDR5/DDR4/NAND 现货 YoY、MoM、代际比价） | 2021-09 ~ 2026-08 | ✅ |
| semiconductor_memory_taiwan_lead | price | 月 | 5（南亚科/威刚 YoY、MoM、均值） | 2016-02 ~ 2026-08 | ✅ |
| semiconductor_memory_price | price | 日 | — | 仅 2 个 trade_date | ⛔ 排除 |
| tsmc_cowos_capacity_estimates | capacity | 季 | — | 仅 7 期（forecast） | ⛔ 排除 |

> 说明：`semiconductor_memory_price` 为覆盖式快照；`tsmc_cowos_capacity_estimates` 仅 7 期智库
> 预测，均无法做时间序列相关，按 Ground Truth First 要求只披露不参与。

### 2.3 指标变换与统计

- 变换：优先使用黄金表官方增速列（`yoy_growth`/`price_yoy`/`revenue_yoy` 等）；无现成增速时
  由水平序列自算 `pct_change(12)` 或 `pct_change(4)`（标注"自算"）；DOI/利用率/毛利率/占比
  直接使用无量纲水平。
- 相关：Spearman（主）+ Pearson（辅）；同期 + 领先滞后。
- 领先滞后定义：`lag=k` 表示 `corr(SOX_t, metric_{t-k})`；**k>0 = 指标领先 SOX k 期**，
  **k<0 = SOX 领先指标 |k| 期**。月频 ±6 月，季频 ±3 季。
- 区间：全样本（SOX 2014-08 起重叠段）、`since2018`、`since2023`（AI 时代）。
- 样本门槛：月频 n≥24、季频 n≥12；序列恒定或过短不输出相关系数。

### 2.4 产物

| 产物 | 路径 |
| :-- | :-- |
| 汇总（每指标 × 区间：同期/领先滞后最佳） | `data/analytics/semiconductor/sox_local_correlation/sox_local_corr_summary.csv` |
| 领先-滞后矩阵（每指标 × 每个 lag） | `data/analytics/semiconductor/sox_local_correlation/sox_local_corr_lag_matrix.csv` |
| 表级覆盖清单 | `data/analytics/semiconductor/sox_local_correlation/coverage.csv` |
| 复现脚本 | `scripts/sox_local_correlation.py` |

## 三、同期相关：SOX 月收益 vs 各环节（全样本 Spearman）

| 排名 | 指标 | 环节 | rho | n | 备注 |
| --: | :-- | :-- | --: | --: | :-- |
| 1 | DDR4/DDR5 代际比价（61050/6105） | price | **0.371** | 44 | p=0.013，结构错配哨兵 |
| 2 | DDR5 16G 现货价 YoY | price | 0.204 | 32 | 2023-12 起，样本短 |
| 3 | ASML 季度毛利率 | equipment | 0.178 | 41 | |
| 4 | 全球半导体销售额 MoM | sales | 0.157 | 142 | Pearson 0.231 (p=0.006) |
| 5 | 台积电先进制程晶圆占比 | capacity | 0.154 | 34 | |
| 6 | DDR4 16Gb 现货价 YoY | price | 0.152 | 49 | |
| 7 | LRCX 季度毛利率 | equipment | 0.145 | 34 | |
| 8 | NAND 512Gb 现货价 YoY | price | 0.138 | 48 | |
| 9 | 台湾存储营收 YoY（威刚 3260） | price | 0.135 | 116 | |
| 10 | KLAC 季度毛利率 | equipment | 0.130 | 37 | |
| — | 台积电先进封测营收 YoY | capacity | **-0.404** | 30 | p=0.027，显著负相关（见 §六） |
| — | 台积电月度营收 YoY / MoM | sales | -0.097 / -0.112 | 144 | 同期为弱负 |

其余季度指标（IDM/渠道 DOI、产能利用率、云 CapEx YoY、SEMI 出货 YoY 同期）均在
-0.05 ~ +0.13 之间，同期相关性不显著。

## 四、周期共振：SOX 12 个月动量 vs 产业 YoY（全样本 Spearman）

| 指标 | rho | n |
| :-- | --: | --: |
| NAND 512Gb 现货价 YoY | **0.813** | 48 |
| 中国区销售额 YoY | **0.654** | 106 |
| 台湾存储营收 YoY 均值（2408/3260） | **0.649** | 116 |
| 台湾存储营收 YoY（威刚 3260） | 0.664 | 116 |
| 台湾存储营收 YoY（南亚科 2408） | 0.601 | 116 |
| 亚太区销售额 YoY | 0.619 | 142 |
| DDR4 16Gb 现货价 YoY | 0.557 | 49 |
| 全球半导体销售额 YoY | 0.555 | 142 |
| DDR5 16G 现货价 YoY | 0.481 | 32 |
| 全球半导体销售额 MoM | 0.452 | 142 |
| SEAJ 设备出货 YoY | 0.240 | 139 |
| 台积电月度营收 3MMA YoY | 0.109 | 140 |
| 台积电月度营收 YoY | 0.043 | 144 |

> 解读：SOX 的 12 个月动量与"价格弹性 + 中国/亚太需求 + 全球销售额"增速强共振，是典型
> 全球半导体景气周期的同向映射；TSMC 单公司月营收与 SOX 动量共振弱，说明 SOX 定价的是
> 全行业景气而非单一代工厂流水。

## 五、领先-滞后结构（全样本最佳 |rho|）

| 方向 | 指标 | 最佳 lag | rho | n | p |
| :-- | :-- | --: | --: | --: | --: |
| SOX 领先（k<0） | SEMI 中国区设备出货 YoY | -3 季 | 0.462 | 38 | 0.005 |
| SOX 领先 | SEMI 全球设备出货 YoY | -3 季 | 0.440 | 38 | 0.008 |
| SOX 领先 | SEMI 全球设备出货 QoQ | -3 季 | 0.377 | 41 | 0.020 |
| SOX 领先 | DDR5 16G 现货价 YoY | -5 月 | 0.390 | 32 | 0.044 |
| SOX 领先 | 全球销售额 MoM | -4 月 | 0.255 | 138 | 0.003 |
| SOX 领先 | NAND 现货价 YoY | -5 月 | 0.260 | 48 | 0.092 |
| SOX 领先 | 存储三巨头加权 DOI | -3 季 | -0.206 | 42 | 0.209 |
| 指标领先（k>0） | DDR4/DDR5 代际比价 | +1 月 | 0.391 | 43 | 0.010 |
| 指标领先 | NAND 现货价 MoM | +4 月 | 0.303 | 59 | 0.025 |
| 指标领先 | DDR4 16Gb 现货价 MoM | +4 月 | 0.282 | 60 | 0.035 |
| 指标领先 | 模拟四巨头加权 DOI | +3 季 | 0.260 | 42 | 0.111 |
| 指标领先 | IDM 等权库存天数 DOI | +3 季 | 0.252 | 42 | 0.122 |
| 指标领先 | 渠道（ARW/AVT）加权 DOI | +3 季 | 0.219 | 47 | 0.154 |
| 指标领先 | 台湾存储营收 MoM（南亚科） | +2 月 | 0.211 | 127 | 0.018 |

> 结构解读：SOX（美股定价）先行的对象是"资本开支物化（设备出货）与同步销售额"——设备出货
> 是滞后确认；而对 SOX 有领先倾向的是"价格弹性/库存边际"（内存现货 MoM、代际比价、DOI），
> 符合周期框架中价格高敏、库存边际先行的机制。注意：3MMA、YoY 序列自相关较强，相关峰
> 存在平台效应（如比价 lag -1~+2 均 >0.33），方向判断可比峰值，精确期数不做过度解读。

## 六、显著负相关与换挡信号（需谨慎）

1. **台积电先进封测营收 YoY vs SOX 季度收益：-0.404（p=0.027，n=30，2019Q1~2026Q2）**。
   机制揣测：封测/先进制造营收是"事后流水确认"，而 SOX 是"预期定价"——营收高增见顶时段
   往往对应 SOX 已回撤（如 2021-2022）；2023+ 子样本相关系数收窄至 -0.26。样本量小，
   勿作因果或反向交易依据。
2. **AI 时代（2023+）换挡**：

| 指标 | 全样本最佳 | 2023+ 最佳 | 说明 |
| :-- | :-- | :-- | :-- |
| SEMI 全球设备出货 YoY | -3 季 +0.440 | -1 季 **-0.610** (p=0.027, n=14) | 符号反转，AI 扩产节奏与美股定价错位 |
| 云 CapEx QoQ | +3 季 -0.368 (全样本) | -1 季 -0.495 (n=14) | 云资本开支与 SOX 季度收益负相关 |
| ASML 净销售额 YoY | -1 季 -0.335 | -1 季 -0.566 (p=0.044, n=14) | 同上 |
| 渠道 DOI（同期） | +0.057 | **-0.464** (p=0.094, n=14) | 2023+ 渠道累库与 SOX 收益反向 |
| 中国区销售额 YoY（12M 共振） | 0.654 | **0.778** | 国产/AI 结构性需求与 SOX 动量共振增强 |

> 2023+ 各子窗口 n=13~15，属探索性证据；结论以全样本结构为主，AI 时代观测作为
> "换挡风险提示"，不单独作为决策依据。

## 七、与既有研究结论的交叉验证

- 与 `data/analytics/industry_strategy/semi_sox_backtest.md` 一致：产业实物流量腿
  （demand=TSMC+SIA、supply=SEAJ）对 SOX 未来 60 日收益无稳定预测力（全周期 IC -0.10 左右、
  分年符号翻转），本文同期/领先滞后同样显示 SOX 与销售额/设备**以 SOX 领先为主**——
  本地产业数据不是 SOX 的稳定领先因子。
- 与 `docs/research/semiconductor/02_data_availability.md` 一致：TSMC 月营收的领先性是
  "发布时效领先（较 SIA 早 3-4 周）"，不是对 SOX 的预测领先；SOX 等价格类序列被明确
  排除在 demand 腿外（`src/stock_analytics/pipelines/semiconductor/legs.py:7`）。
- 补充新事实：内存现货 MoM / 代际比价是本地数据中对 SOX 少数有"指标领先"倾向的序列，
  与"价格是最敏锐信号"的周期框架一致；但需独立 IC/回测验证后才可进入任何信号体系。

## 八、局限与风险提示

1. **统计局限**：描述性相关 ≠ 因果；同期序列普遍自相关，领先滞后峰有平台效应；多指标 ×
   多 lag × 3 区间存在多重检验问题，p<0.05 的个别项可能为偶然。最佳 lag 的点估计保守解读。
2. **样本量**：内存基准（DDR5 44 月、DDR4/NAND ~60 月）、台积电封测（30 季）、云 CapEx
   （30-33 季）及 2023+ 子窗口（13-15 期）样本偏短；5Y 门槛内可作探索，不可过度外推。
3. **口径边界**：SEAJ 为日本制设备（代理口径，非全球全集）；TSMC 月营收为单公司；
   cloud_capex `release_date` 缺失（生效回退 `trade_date`）；`semiconductor_memory_price`
   与 CoWoS 测算因样本不足未纳入；TEL 的 FY quarter 按 3 月末财年映射（FY2027-Q1 = 2026-06）。
4. **与前视的关系**：本报告为描述性相关，不生成交易信号、不做回测，故未使用
   `release_date` 做截面对齐；任何后续因子化必须回到"生效日"口径（见 golden_tables_guide §3）。
5. **不构成投资建议**：本报告仅回答"SOX 与本地哪些产业数据相关"，不推荐基于相关性的买卖。
