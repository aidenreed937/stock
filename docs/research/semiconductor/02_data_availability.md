# 数据可用性与来源声明（Ground Truth First）

> 半导体深研线 · 数据来源声明（2026-09 落盘核验）
> 本文是 [SOP 符合性评估](sop_gap_assessment.md) 行动项 #2（P1：补数据来源披露）的落地产物，
> 仿照光伏 `../photovoltaic/02_data_availability.md` 的"数据源/时效/代理口径/缺口"结构，
> 满足 Ground Truth First 与信息分级（已验证事实 / 机制推断 / 外部背景）。
> 数据现状以 `data/curated/industry/` 与 `data/curated/mart/` 磁盘真实落盘为准，核验日期见文末。

## 0. 分级原则：GT 主表 vs 代理腿 vs 对账源

| 层级 | 定义 | 本线示例 |
| :-- | :-- | :-- |
| **Ground Truth 主表** | 指标定义域的法定全集，其他任何代理不得回写或替代它作为该指标的事实来源 | SIA/WSTS 全球半导体销售额；SEAJ 日本制设备出货（其自身口径内的全集） |
| **代理腿（proxy leg）** | 语义层级低于目标指标、与目标高度相关但非全集的实物流量，仅用于领先/确认，**不替代 GT 主表** | TSMC 月营收（单公司，全球销售额的领先代理）；SEMI WWSEMS（全球设备全集，SEAJ 的对账源）；交期（供需结果，只读方向） |
| **对账/参考源** | 仅在分析/对账层计算，不回写某一来源的黄金事实表 | SEAJ/SEMI 比值；美元换算序列 |

**核心声明（需求腿）**：TSMC 台积电月营收**适合作为 SIA/WSTS 全球半导体销售额的领先代理指标**
（领先约 25 天，见 §1.1），但**不应该替代 WSTS/SIA 作为全球半导体销售额的 Ground Truth**：
TSMC 是单公司（晶圆代工龙头）营收，SIA/WSTS 是全球销售额全集，语义层级不同；两者在
demand 腿中为**并列双源等权合成**，不是代理-被代理关系（§1.3）。

---

## 1. 需求腿（demand = TSMC + SIA/WSTS 均值合成）

### 1.1 TSMC 台积电月营收 —— 领先代理腿（不替代 GT）

| 项 | 内容 |
| :-- | :-- |
| 本地黄金表 | `data/curated/industry/semiconductor_lead.parquet`（151 行，2014-01 ~ 2026-07） |
| 原始来源 | TSMC 官方投资者站 `https://investor.tsmc.com/english/monthly-revenue/{year}`（英文年度页） |
| 字段 | `tsmc_revenue_3mma_usd`（3MMA 美元，USD/3MMA 在 Curated 阶段计算）、`tsmc_revenue_yoy` |
| 时效 | 月频；每月 10 日前后披露上月营收（`release_date` = 下月 10 日，无前视、0 缺失） |
| **定位声明** | **领先代理指标**：比 SIA 全球销售额提前约 25 天，是最高频、最前瞻的需求实物流量腿；**单公司口径，非全球销售额全集，不替代 SIA/WSTS 作为全球销售额 Ground Truth** |
| 覆盖说明 | 2014-01 ~ 2014-12 为平台填充段（2015 起真实），引用该区间读数需标注 |

### 1.2 SIA / WSTS 全球半导体销售额 —— Ground Truth 主表

| 项 | 内容 |
| :-- | :-- |
| 本地黄金表 | `data/curated/industry/semiconductor_sales.parquet`（486 行，1986-01 ~ 2026-06） |
| 原始来源 | 双源协同：主源 WSTS Historical Billings Report（wsts.org 官方 xlsx，1986 年至今 40 年连续 3MMA 底表）；补充源 SIA 官网新闻（semiconductors.org，补充中国区销售额与官方新闻发布日） |
| 字段 | `global_sales_usd`（官方 3MMA，0 缺失）、`china_sales_usd`（中国区绝对额，全空，见 §4 缺口①） |
| 时效 | 月频；全球 3MMA 按官方口径（非单月原始值） |
| **定位声明** | **全球半导体销售额 Ground Truth 主表**；中国区增速 `china_yoy_growth`(106 非空)/`china_mom_growth`(112 非空) 直接落在主表，中国区绝对销售额因 SIA 不披露而无黄金表承载（见 §4 缺口①） |
| 覆盖说明 | 早期段（1986 ~ SIA 新闻覆盖前的月份）`release_date` 缺失占 59.5%，生效日回退 `trade_date`（见 §4 缺口②） |

### 1.3 合成与替代边界（本节为需求腿的"不替代"硬约束）

- **合成**：两源各自 YoY → 36 月滚动分位后**等权均值**为 `demand_score`
  （`src/stock_analytics/pipelines/semiconductor/legs.py:142-170`，配置 `config/analytics/semiconductor_legs.yaml:28-34`）。
- **不替代**：一腿缺失时另一腿独立生效（不阻塞），**任何情况下不允许用 TSMC 序列回填/回写
  `semiconductor_sales`（GT 主表）**；GT 表的缺失必须按缺口披露，不记忆补造。
- **禁用**：SOX 等价格类序列不进入 demand 腿（只买实物流量，不用价格类；`legs.py:7` 明确"剔 SOX 市价"）。

### 1.4 领先性辨析：数据时效领先 vs 周期同步 vs 制程传导（2026-09-04 实证）

> 回答"产业数据大部分是先进制程，对 A 股成熟制程有前瞻引导吗？传导是否从高端到中低端？"
> —— 三个"领先"必须分清，本地实测结论如下。

**① 数据时效领先（TSMC vs SIA）—— 成立，这是 TSMC 在 demand 腿中的真实角色**
- TSMC 月营收次月 10 日前后披露（本地 `release_date` 相对报告月末中位 +10 天），SIA 全球 3MMA
  滞后约 1 个月发布 → TSMC **早 3-4 周拿到当月读数**，是"最早可得的当月实物流量信号"。
- 实证（150 个月）：TSMC YoY vs SIA YoY 同期相关 0.306、-1 月 0.322（略高但基本同期）——
  领先性来自**发布时效**，不是产业先动。

**② 全球周期同步（全球产业数据 vs A 股）—— 成立，这是剪刀差预测力的真正来源**
- 剪刀差对 270100 fwd60 IC +0.113（显著，本地复算 n=2967）；但 TSMC YoY 对 270100 未来
  1/3/6 个月收益无显著领先（r=0.014~0.085，p 不显著）。
- 机制：A 股对全球产业数据**滞后反应**（`semi_sox_backtest` 已证：同信号在美股 SOX 无效、
  A 股有效，依赖 A 股滞后），剪刀差读的是"全球供需周期位置"，不是"制程传导链"。

**③ 先进→成熟制程传导领先 —— 不成立（本轮证伪）**
- 全球销售 vs 中国区销售：lag 0 相关最强（0.540），±1 月对称（0.503/0.514）→ **同期共振，
  非全球领先**。
- ASML（先进 EUV）vs SEAJ（日本设备=成熟为主）：未来 1 季 0.424 与反向未来 1 季 0.424
  → **双向同期**，无单向高端领先。
- **2024-2026 AI 周期先进/成熟显著脱钩**：TSMC YoY vs 中国区 YoY 同期相关 **r=-0.099
  （p=0.60，n=30）**——2024-2025 TSMC 高增（+25~+60%）而中国区反复负增长，2026 中国区才补涨
  （+47%~+113%）。先进与成熟受不同驱动（AI 算力 vs 传统消费/工业），不是线性传导。

**数据腿制程构成（修正"大部分是先进制程"的认知）**：

| 腿 | 制程构成 | 判定 |
| :-- | :-- | :-- |
| demand = TSMC + SIA | TSMC 先进为主（3/5/7nm 约 65-70%）+ SIA 全制程混合 | 先进 + 全口径 |
| supply = SEAJ | 日本设备（TEL/DNS 涂胶显影/清洗/刻蚀）偏成熟制程 | 偏成熟 |
| DOI 库存腿（TXN/ADI/STM/NXPI） | 模拟/混合信号 = 成熟制程代表 | 成熟 |
| GM 前瞻腿（AMAT/LRCX/KLAC/ASML） | 先进制程设备商 | 先进 |
| ai_capex 结构性腿 | 云算力需求 | 先进 |

**对框架的含义**：TSMC 在 demand 腿的角色是"时效领先"（更早确认周期位置）而非"制程领先"；
先进/成熟脱钩正是 `ai_capex_score` 结构性腿存在的理由（AI 轮特异驱动，换驱动轮需换腿）；
A 股 270100（成熟代工+成熟设计+设备材料国产替代）不直接吃先进制程景气的基本面，
先进制程对 A 股更多是主题/预期传导——剪刀差信号天然带滞后与折损，框架定位
"防守门躲回撤"而非"先进制程指引买入"正是该约束的体现。

---

## 2. 供给腿（supply = SEAJ 日本制设备出货）

| 项 | 内容 |
| :-- | :-- |
| 本地黄金表 | `data/curated/industry/semiconductor_equipment.parquet`（139 行，2015-01 ~ 2026-07） |
| 原始来源 | SEAJ 官网 `https://www.seaj.or.jp/statistics/`：历史 XLS 底表 + 最新速报 PDF；`ReleaseDates.pdf` 提供官方发布日 |
| 字段 | `billings_3mma_jpy`（**十亿日元原始序列**，3MMA）、`yoy_growth_3mma`、`mom_growth_3mma`（0 缺失） |
| 时效 | 月频，`release_date` 0 缺失，按发布日生效无前视（2026-09 修复 release_date 口径） |
| **定位声明** | **代理口径，非全球全口径**：SEAJ 为日本制造商出货（TEL/Disco/Kokusai 等，约全球 1/3+），领先 1-2 年产能释放；剪刀差供给腿只用日元原币 YoY 与滚动分位 |
| 对账 | SEMI WWSEMS（`semiconductor_equipment_semi.parquet`，2018-Q1 ~ 2026-Q2，34 季）是全球设备真实全集（**全球主序列，附中国区域分项**），仅用于量级对账与自主可控研判；`seaj_global_share_pct` 与美元换算**不进入供给腿或剪刀差**。中国区列已补齐：`china_billings_billion_usd` / `china_share_pct` **覆盖 34/34 季、止于 2026-Q2**（15 期取自公报文本区域表 + 11 期取自官方区域图片人工核对 + 8 期由年度值残差推导）；图片 URL、SHA-256 与区域合计门禁见 `regional_billings_image_ledger.csv`。仍不得用 `semiconductor_sales.china_yoy_growth`（SIA 中国区月销售额增速，另一口径）顶替 |
| 覆盖说明 | 2015-01 起；2015 前无 SEAJ 月频序列（剪刀差历史起点受供给腿起点约束） |

---

## 3. 确认腿（leg_type 独立分组，不入剪刀差）

| 腿 | 本地黄金表 | 原始来源 | 口径与时效 | 定位 |
| :-- | :-- | :-- | :-- | :-- |
| 产能利用率/出货代理 | `foundry_capacity_utilization.parquet`（现有 42 行为旧宽表，待双源 RAW 重放更新） | TSMC 官方 IR 季度管理报告 + SMIC 官方业绩公报（HKEX/SSE） | SMIC 利用率、月产能、销售晶圆为官方值；TSMC 稳定提供 12 英寸等效晶圆出货，季度利用率/产能可能 `unavailable`；仅两家公司利用率同时存在时生成带 `proxy_method` 的代表性代理，不能称全球真实加权值 | `utilization_score`：供给端确认；代理缺一时不输出合成值 |
| IDM 存货 DOI | `semiconductor/inventory/semiconductor_inventory_days.parquet`（295 行，2016-Q1 ~ 2026-Q3；2016Q1–2026Q2 每季 7 个标的） | SEC EDGAR 官方 companyfacts、10-Q/10-K、20-F、6-K：TXN / ADI / STM / NXPI / MU（P0）；韩国存储双雄（三星电子 DS / SK海力士，P1）。三星 DS 与 SK 海力士各 42 期，均来自 DART 官方定期报告；三星 `C. Inventory / 다. 재고자산 현황` 的半导体小计已回溯至 2016Q1，2016Q1–2021Q4 记录 `inventory_scope=legacy_semiconductor_business`，2022Q1 起为 `ds_division`；三星纯存储库存 `memory_inventory_status=not_disclosed`。SK 海力士 2016Q1–2026Q2 连续，Q4 成本按 DART 年度与 9M 累计值差分，详见 [06_korea_memory_doi_integration_spec.md](06_korea_memory_doi_integration_spec.md) | DOI =（期末存货 / 季度营业成本或明确标注的成本代理）× 90；季度，`release_date` 完整；Q4 累计营业成本差分保留 `derived_q4` 状态；区分 `analog_auto` 与 `memory` 周期样本加权；2026Q2 已补齐三星 DS 与 SK 海力士当期记录，2016Q1 起韩国双雄历史缺口已通过 DART 增量回填 | `inventory_score`：供给堆积/需求透支确认，**只在贴顶区（≥80）有效**（fwd60 -0.198 / 贴顶 +0.309） |
| 渠道存货 DOI | `semiconductor_channel_inventory.parquet`（134 行，2009-Q2 ~ 2026-Q2，2026-09 修复 10-K 差分后填完整） | SEC companyfacts：ARW（Arrow）/ AVT（Avnet）分销商 10-Q/10-K | 渠道 DOI = (两家合计存货 / 合计季度营业成本) × 90；10-K 财年 Q4 单季 COGS 用差分法（全年 − 前三季）；`release_date` 完整（首次披露日） | 渠道库存压力 proxy（成熟制程流通侧）：去库先行/滞后对照 IDM 厂商侧；面板内自 2014 起日频、分位按全历史（2009Q2 起）计算；2009-2013 保留季度粒度黄金表 |
| GM 前瞻 | `semiconductor_equipment_gm_multi.parquet`（173 行，2016-Q1 ~ FY2027-Q1）+ ASML 表 | SEC EDGAR 8-K 新闻稿（GM 实际/下季指引/服务占比）+ 10-Q XBRL 交叉验证（AMAT/LRCX/KLAC） | 非 GAAP GM `gross_margin_pct`（缺 4.0%）、`gm_guidance_next_pct` / `services_share_pct`（缺 72.3%，各公司指引覆盖期不同）；`release_date` 完整 | `gm_cross`：剪刀差 LONG 挂靠确认腿（基准 0.8 / 高分 ×1.2），不作独立择时；TEL（`tel_gm_quarterly`，日本 IR，仅 GM 实际值、偏 IC -0.091）**未接入前瞻复合** |
| 结构性确认 | `cloud_capex_quarterly.parquet`（34 行，2018-Q1 ~ 2026-Q2） | SEC EDGAR 官方 10-Q：MSFT / GOOGL / META / AMZN | 单季 CapEx 差分，`total_capex_billion_usd` 0 缺失；`release_date` 全空 → 生效回退 `trade_date`（见 §4 缺口③） | `ai_capex_score`：当期驱动源确认（说明层，非交易信号），只 270100/710100 有值 |
| 供需结果 | `chip_lead_time.parquet`（104 行，2018-01 ~ 2026-08，actual） | Susquehanna / Mouser 交期统计 | 月频 `weeks`；2022-09、2026-08 两处口径断裂（Susquehanna→Bloomberg/Mouser） | 只读方向（normal/tight/overheated），不读精确周数，不进剪刀差 |

---

## 4. 已知缺口（必须披露，不得补造）

| # | 缺口 | 影响 | 处置 |
| :-- | :-- | :-- | :-- |
| ① | `semiconductor_sales.china_sales_usd` 主表列全空（100% null） | 中国区**绝对销售额**不在 GT 主表（SIA 只披露区域增速，不披露中国区绝对额） | 中国区增速由主表 `china_yoy_growth`(106 非空)/`china_mom_growth`(112 非空) 承载；原独立表 `semiconductor_china_series.parquet` 与主表同名列在 106 个共同月份上逐值一致、无独立消费方，**已于 2026-09-10 退役**（其 `anchor_flag`/`calc_flag`/`check_status` 三列 112/112 全为常量、校验从未生效，不存在 mismatch/corrected 对账状态）。重启 ETL 回填主表前不得以代理数据补齐 |
| ② | `semiconductor_sales.release_date` 缺失 59.5%（早期 WSTS 底表段） | 历史段生效日用 `trade_date`（月末）替代，存在发布滞后窗口 | 近月段已由 SIA 新闻发布日补齐（0 前视）；早期段仅作回测分母，引用需标注；可追溯目标：WSTS 官方发布日历补全 |
| ③ | `cloud_capex_quarterly.release_date` 100% 缺失 | 结构性腿生效回退 `trade_date`（季度末），比 SEC 实际 filingDate 提前约 3-6 周，**存在前视隐患** | 结构性腿定位说明层、不作交易信号，风险可控；修复项：从 SEC submissions（filingDate）回填 `release_date` |
| ④ | SEMI 表中国区图片值曾缺失 | 已修复：`china_billings_billion_usd` 与 `china_share_pct` 当前 34/34 季非空；8 个 Q4 为年度残差推导 | 11 个官方区域图片值由 ledger 管理并经区域合计差额 ≤0.05 B$ 门禁；禁止外推 |
| ⑤ | TSMC demand 腿 2014-01 ~ 2014-12 平台填充 | 该段分位无区分度 | 按 methodology 定稿：可选不优先补齐（2018-2026 已覆盖近两轮完整周期） |
| ⑥ | 结构性腿起点 2019-04（ai_capex） | 2017-2018 存储轮无数据腿 | 已定标可选/不优先；换轮时按 `structural_leg_build_sop.md` 重建 |

---

## 5. 生效语义（无前视）

- 建腿生效列优先级：`release_date`（官方发布日）→ 回退 `trade_date`（`legs.py:52-54`），
  前向填充至日频交易日历；月频/季频腿按发布日生效，日频信号腿逐日更新。
- 月频腿是"月度滞后确认"阶梯：月末数据在官方实际发布后才可用（TSMC 下月 10 日、SIA 滞后约 1 个月）。
- **Ground Truth First**：本节所有覆盖/缺失/状态均以本地 Curated 落盘为准（核验日期 2026-09-03）；
  本地缺失必须披露（§4），不得用记忆或跨源代理补造黄金事实表。

---

## 6. 引用格式要求（引用具体读数时）

引用任一产业腿读数，必须同时写明：本地数据集、字段、报告期（`report_month`/`report_quarter`）、
`release_date`、`source_url` 或源链接，并声明代理口径（TSMC=单公司领先代理 / SEAJ=日本制代理口径）。
不允许只给一个数值或只引用跨源对账表（口径限制详见
`industry-trend-tracking` skill `semiconductor_trading_methodology.md` §2.1「SEAJ 高频供给代理的使用边界」）。
