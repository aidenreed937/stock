# 韩国存储/半导体双雄（三星电子 DS / SK海力士）IDM 存货周转天数 (DOI) 接入技术规范

> **文档定位**：半导体垂直产业数据管道（`src/stock_data/fetcher/industry/semiconductor/`）扩展技术规范与数据契约
> **涉及标的**：三星电子半导体事业部（`005930.KS_DS`）、SK海力士（`000660.KS`）
> **数据目标**：将全球半导体存储（Memory）存货周转天数（DOI）由单美光（`MU`, P0）样本升级为覆盖全球 90%+ 产能的加权黄金基准（P1），与模拟/汽车龙头（`TXN/ADI/STM/NXPI`）共同构成全球 IDM 综合库存相态矩阵。
> **遵循准则**：Ground Truth First、2-Tier ETL、会计准则双轨汇率折算（IAS 21/ASC 830）、分部严格隔离与防前视偏差。

> **2026-09 回填结果**：三星 DS 与 SK 海力士各 42 期（2016Q1–2026Q2）已统一回溯到 DART 官方定期报告。三星取 `C. Inventory – The inventory status by Division`（韩文标题：`다. 재고자산 현황`）中的半导体小计；2016Q1–2021Q4 为旧组织表，排除 DP/SDC，2022Q1 起取 `DS 부문`。三星库存可以官方披露到半导体业务，但没有 Memory 单独库存，`memory_inventory_status=not_disclosed`。SK 海力士 2016Q1–2026Q2 已连续；Q4 成本按同年度 DART 年度成本减 DART 9M 累计成本，并保留支撑报告血缘。2016Q1–2026Q2 的 42 个季度均恢复为 **7 个标的**；三星 DS 的存货不属于 IFRS `Segment Information - Balance Sheet` 表。

---

## 0. 核心背景与接入价值

### 0.1 现状与痛点（P0 美光的局限性）
在接入韩国双雄之前的半导体 IDM 存货周转天数黄金表（`data/curated/industry/semiconductor_inventory_days.parquet`）中：
1. **存储样本单点依赖**：存储子板块（`subsector="memory"`）仅有美光科技（`MU`），其存货规模约在 80~85 亿美元，仅占全球原厂存储库存的不到 20%。
2. **财年错位带来的噪音**：美光独特的财年周期为 8 月底截止（Q1 为 9~11 月，Q2 为 12~次年 2 月，Q3 为 3~5 月，Q4 为 6~8 月），与其他日历季标的（3/6/9/12 月底）存在整整 1 个月的错位，在计算季频加权 DOI 时易受单公司节奏扰动。
3. **行业代表性失衡**：在未接入韩股前，全球 IDM 加权 DOI（`idm_weighted_doi_days`）总存货约 200 亿美元，其中 60% 权重被模拟/汽车（TI, ADI, STM, NXP）占据，存储周期的剧烈起伏在综合指数中被过度平抑。

### 0.2 接入目标（P1 韩国双雄的战略意义）
| 标的代码 | 机构与业务实体 | 全球存储份额 | 原生币种与财报口径 | 接入定位 |
| :--- | :--- | :--- | :--- | :--- |
| **`000660.KS`** | SK海力士 (SK hynix) | DRAM ~30%, NAND ~20% | 兆/十亿韩元 (KRW), K-IFRS 集团合并 | P1 核心存储标的 |
| **`005930.KS_DS`** | 三星电子 (Samsung Electronics) - 仅限 **Device Solutions (DS)** 半导体事业部 | DRAM ~40%, NAND ~32% | 兆韩元 (KRW), K-IFRS 分部披露 | P1 核心半导体/内存周期代理（非纯 Memory 库存） |
| **`MU`** | 美光科技 (Micron Technology) | DRAM ~23%, NAND ~12% | 百万美元 (USD), US-GAAP SEC 10-Q/10-K | P0 现存美股标的 |

接入后，全球存储周期的三家核心样本（Samsung DS + SK hynix + Micron）全部入库；其中 Samsung DS 是官方半导体业务库存代理，不能解释为纯 Memory 库存。`memory_weighted_doi_days` 应标注为“存储周期样本加权 DOI”，而不是纯存储库存总额。

---

## 1. 三大客观技术壁垒与架构解法

```
[外部官方信源]
  ├─ Samsung IR / DART Interim & Business Report ─┐
  ├─ DART 分部摘要（收入/营业利润）──────────────┤
  ├─ SK hynix DART 定期报告 ────────┼─> [parsers/korea_memory.py] ──> [collectors/inventory.py (合流)]
  └─ FRED 官方 DEXKOUS (韩元即期) ──┴─> [transforms/fx.py (汇率引擎)]        │
                                                                             ▼
                                                                  [RAW: semiconductor_inventory_days.parquet]
                                                                             │
                                                                             ▼
                                                                  [transforms/inventory.py]
                                                                    - 存货: BS 期末即期折算 USD
                                                                    - 营业成本: IS 季均汇率折算 USD
                                                                    - 三星严格剥离半导体业务（排除 DP/SDC）
                                                                             │
                                                                             ▼
                                                                  [Curated: semiconductor_inventory_days.parquet]
                                                                    - idm_weighted_doi_days (全球综合)
                                                                    - memory_weighted_doi_days (存储周期样本；三星 DS 为半导体代理)
```

### 1.1 壁垒一：数据申报体系非 SEC 标准（DART vs IR Factsheet）

#### 机制矛盾
韩国交易所上市公司的法定披露平台是韩国金融监督院 DART（Open DART API）：
- 需要申请特定开发者 API Key，海外网络与沙箱环境调用稳定性差；
- 原始 XML/JSON 报表遵循韩文 K-IFRS 科目（如 `재고자산`、`매출원가`），科目代码缺乏统一的 US-GAAP XBRL 标签映射；
- DART 季报正式申报（Quarterly Business Report）通常在季度结束后 45 天才披露，严重滞后于业绩发布会（Earnings Call）。

#### 架构解法：官方 IR / DART 公报与 Factsheet 解析器
- **信源选择**：三星的分部存货以法定披露平台 DART 的 Interim/Business Report 为主；IR Earnings Presentation/Factsheet 仅作为英文补充和交叉检查。SK 海力士的库存与合并营业成本统一使用 DART 定期报告，禁止再回退到 SGX、SEC 或 IR Factsheet。
- **采集模式（2-Tier 协同）**：
  1. **历史回填种子（Ground Truth Seed）**：
     - 将 2016Q1 至今已审计的季度数据结构化沉淀在 `data/raw/industry/semiconductor/korea_memory_raw.csv`；
     - 每一条记录包含完整的源端金额、货币单位（KRW）、报告期末、官方发布日、原始材料 URL 及快照 SHA-256；三星 DS 另保留分部收入、营业利润和成本代理来源标记。
  2. **季度增量采集器（`parsers/korea_memory.py`）**：
     - 在财报披露窗口自动化抓取两家公司 IR/DART 发布的最新财务摘要；
     - 原始文件压缩存档至 `data/raw/industry/semiconductor/korea_filings/`，严守血缘不可篡改原则。

---

### 1.2 壁垒二：三星电子业务分部（Segment）剥离风险

#### 机制矛盾
- **SK海力士**：95% 以上收入与成本来自存储芯片，集团合并报表（Consolidated）等价于存储主营，直接取合并报表上的存货与销售成本。
- **三星电子**：综合性科技集团，旗下业务包括：
  - **DS (Device Solutions)**：半导体部门（Memory 存储、System LSI 逻辑设计、Foundry 晶圆代工）；
  - **DX (Device eXperience)**：MX (智能手机)、VD (电视)、DA (家电)；
  - **SDC (Samsung Display)**：显示面板；
  - **Harman**：车载与音响。

若错误使用三星集团合并报表：
- 集团总存货常年高达 50~55 兆韩元（约 380~420 亿美元），但半导体 DS 部门存货仅为 25~30 兆韩元（约 190~230 亿美元）；
- 错用合并报表会导致三星一人吞噬全球 IDM 存货总额的 60% 以上，非芯片类库存（手机、电视、白电）将严重污染半导体库存周转天数，导致加权 DOI 人为虚高 30~50 天，彻底破坏相态判决。

#### 架构解法：下钻提取 DS 分部与异常断言门禁
1. **主键与符号定义**：
   - 明确设立标的代码为 **`005930.KS_DS`**，在数据层物理隔绝“三星电子集团”与“三星半导体事业部”。
2. **提取口径**：
   - **存货（Inventory）**：提取三星 Interim/Business Report 的 `C. Inventory – The inventory status by Division`（韩文：`다. 재고자산 현황 → (1) 사업부문별 재고자산의 보유 현황`）。2016Q1–2021Q4 取旧表 `반도체` / `반도체 사업` 的 `소계`，排除 `DP`；2022Q1 起取 `DS 부문` 的 `소계`，并排除单列的 `SDC`。这不是 IFRS `Segment Information - Balance Sheet` 数据。
   - **纯存储库存**：DART 库存表没有 Memory / DRAM / NAND / HBM 独立余额，`memory_inventory_status=not_disclosed`；`005930.KS_DS` 只代表三星 DS 半导体整体（Memory + System LSI + Foundry）。
   - **分部收入/营业利润**：提取同一报告的 `사업부문별 요약 재무 현황`（分部摘要）中的 DS 收入和营业利润。半年度、三季度和年度披露通常是累计值，先做相邻累计值差分得到单季值。
   - **营业成本（Cost of Revenue / COGS）**：三星 DS 未直接披露分部 COGS。DOI 暂用 `DS Revenue − DS Operating Profit`，字段 `cost_of_revenue_source=proxy_ds_revenue_minus_ds_operating_profit`；`cost_of_revenue_usd_million` 只能解释为成本代理，禁止标记为官方 COGS。
3. **工程断言防护门（Assertion Gate）**：
   在 Transform 阶段对三星电子数据执行分部合理性硬约束门禁：
$$\text{Ratio} = \frac{\text{Inventory}_{\text{DS}}}{\text{Inventory}_{\text{Group}}} \in [0.35, 0.70]$$
   2021Q1 之前的旧组织表允许历史低位至 20%；若低于对应历史下限或超过 70%，或取到了集团合并值，构建流程立即抛出 `ValueError` 并阻断落盘，防止网页结构改版引发的数据污染。

---

### 1.3 壁垒三：汇率与期末对齐（KRW → USD）双轨折算引擎

#### 机制矛盾与会计学规范
韩股财报计量币种为韩元（通常以 10 亿韩元或兆韩元为单位）。要与美光科技及美股 IDM 合流，必须折算为统一的**百万美元（Million USD）**。

国际会计准则（IAS 21 / ASC 830）对跨币种报表折算有明确要求：
1. **资产负债表（Balance Sheet）科目 —— 存货（Inventory）**：
   - 属于**时点存量（Instant Stock）**；
   - 必须采用**资产负债表日（即季度末最后一天）的即期汇率（Spot Exchange Rate）**折算。
2. **利润表（Income Statement）科目 —— 成本代理（Cost Proxy；非官方 DS COGS）**：
   - 属于**期间发生额流量（Flow over Quarter）**；
   - 必须采用**该报告季度的交易日平均即期汇率（Quarterly Average Rate）**折算。

若混淆两类汇率（例如用期末即期汇率折算营业成本，或用均价折算存货），在韩元汇率剧烈波动季度（如 2022 年底韩元对美元大幅贬值 15%），会导致计算出的当季 DOI 人为失真 10~20 天。

#### 架构解法：依托本地 FRED 底座接入日频 DEXKOUS

1. **权威汇率源选择**：
   - 采用美联储经济数据库（FRED）官方标准日频汇率序列 **`DEXKOUS`**（South Korean Won to U.S. Dollar Spot Exchange Rate，纽约联储正午电汇买入汇率）；
   - 该系列在本仓库已有的 FRED 管道中可直接同步，历史可回溯至 1981 年，具备完全可重复验证性。
2. **折算公式定义**：
   对于季度 $Q$（起始日 $T_{\text{start}}$，期末日 $T_{\text{end}}$）：
   - **期末即期汇率** $S_Q$：
     $$S_Q = \text{DEXKOUS}(t),\quad t = \max \{ \tau \le T_{\text{end}} \mid \tau \in \text{TradingDays} \}$$
   - **季度平均汇率** $A_Q$：
     $$A_Q = \frac{1}{N} \sum_{t = T_{\text{start}}}^{T_{\text{end}}} \text{DEXKOUS}(t)$$
   - **美元标准化**（假设源端单位为兆韩元 $\text{Trillion KRW} = 10^{12}\text{ KRW}$）：
     $$\text{Inventory}_{\text{USD\_Million}} = \frac{\text{Inventory}_{\text{Trillion\_KRW}} \times 1,000,000}{S_Q}$$
     $$\text{CostProxy}_{\text{USD\_Million}} = \frac{\text{CostProxy}_{\text{Trillion\_KRW}} \times 1,000,000}{A_Q}$$

---

## 2. 数据契约与 Schema 规范

### 2.1 RAW 层 Schema（源端原始事实）
落盘路径：`data/raw/industry/semiconductor/semiconductor_inventory_days.parquet`

| 字段 | 类型 | 说明与样例 |
| :--- | :--- | :--- |
| `symbol` | String | `000660.KS` / `005930.KS_DS` / `MU` / `TXN` |
| `report_quarter` | String | 标准日历季，如 `2024Q1` |
| `trade_date` | Date | 季度标准对齐日（季度末日，如 `2024-03-31`） |
| `subsector` | String | `memory`（存储周期样本；三星 DS 为半导体代理）或 `analog_auto`（模拟/汽车） |
| `source_period_end` | Date | 原始披露期末日（如 `2024-03-31`） |
| `fiscal_period_raw` | String | 原文会计期（如 `1Q24`） |
| `inventory_usd_raw` | String | 换算前源端存货字符（如 `"29.54"`） |
| `cost_of_revenue_usd_raw` | String | 换算前源端营业成本字符（如 `"15.20"`） |
| `cost_of_revenue_annual_raw` | String | 可选，年报披露累计值 |
| `cost_of_revenue_derivation` | String | 衍生标记（如 `krw_avg_fx_converted;ds_segment_extracted`） |
| `ds_revenue_krw_raw` | String | 三星 DS 分部收入源值（兆韩元；半年度/年度先做单季差分） |
| `ds_operating_profit_krw_raw` | String | 三星 DS 分部营业利润源值（兆韩元；半年度/年度先做单季差分） |
| `cost_of_revenue_source` | String | `proxy_ds_revenue_minus_ds_operating_profit` 或官方合并成本来源 |
| `inventory_scope` | String | 三星库存口径：`legacy_semiconductor_business`（2016Q1–2021Q4，旧表半导体小计）或 `ds_division`（2022Q1 起） |
| `memory_inventory_status` | String | 三星纯存储库存披露状态：`not_disclosed` |
| `release_date` | Date | **官方业绩公报发布日**（严格防前视偏差） |
| `source` | String | `SAMSUNG_DART_BUSINESS_REPORT_C_INVENTORY_BY_DIVISION` / `SK_HYNIX_DART_PERIODIC_REPORT` |
| `source_url` | String | 官方下载链接或公报 URL |
| `unit` | String | `trillion_krw` 或 `billion_krw` |
| `data_status` | String | `actual` |
| `collected_at` | String | UTC ISO-8601 时间戳 |
| `raw_content_sha256` | String | 原始文件快照哈希 |
| `raw_snapshot_path` | String | 原始文件存放相对路径 |

### 2.2 Curated 层 Schema（标准化黄金事实）
落盘路径：`data/curated/industry/semiconductor_inventory_days.parquet`

| 字段 | 类型 | 说明与计算逻辑 |
| :--- | :--- | :--- |
| `symbol` | String | 标的代码（`000660.KS`, `005930.KS_DS`, `MU`, `TXN`, `ADI`, `STM`, `NXPI`） |
| `report_quarter` | String | 报告季度（`YYYYQn`） |
| `trade_date` | Date | 对应季度期末日 |
| `inventory_usd_million` | Float64 | 统一折算后的期末存货（百万美元） |
| `cost_of_revenue_usd_million` | Float64 | 统一折算后的季度营业成本（百万美元） |
| `cost_of_revenue_source` | String | 成本来源标记；三星 DS 必须为 `proxy_ds_revenue_minus_ds_operating_profit` |
| `inventory_scope` | String | 半导体库存口径；用于识别旧 `반도체` 小计与新 `DS 부문` 的组织变更 |
| `memory_inventory_status` | String | 纯存储库存披露状态；三星 DS 为 `not_disclosed` |
| `release_date` | Date | 财报披露日（下游无前视生效锚点） |
| `source` | String | 来源标识 |
| `unit` | String | 固定为 `days` |
| `data_status` | String | `actual` |
| `collected_at` | String | 收集时间戳 |
| `doi_days` | Float64 | **个股 DOI** $= (\text{inventory} / \text{cogs}) \times 90$ |
| `total_inventory_usd_million` | Float64 | 当季入库所有 IDM 总存货合计（百万美元） |
| `total_cost_of_revenue_usd_million` | Float64 | 当季入库所有 IDM 总营业成本合计（百万美元） |
| `idm_equal_doi_days` | Float64 | 简单等权平均 DOI |
| `idm_weighted_doi_days` | Float64 | **全球综合加权 DOI** $= (\sum \text{inv} / \sum \text{cogs}) \times 90$ |
| `inventory_regime` | String | 综合相态（`tight_restocking` / `normal_balanced` / `elevated_destocking` / `high_overstocked`） |
| `subsector` | String | 子行业分类（`memory` 或 `analog_auto`） |
| `analog_weighted_doi_days` | Float64 | 模拟/汽车龙头加权 DOI |
| `memory_weighted_doi_days` | Float64 | **存储周期样本（Samsung DS 半导体代理 + SK hynix + Micron）加权 DOI；不代表三星纯存储库存** |

---

## 3. 核心计算与加权逻辑

### 3.1 标的子行业划分
```python
MEMORY_SYMBOLS = frozenset({"MU", "000660.KS", "005930.KS_DS"})
ANALOG_AUTO_SYMBOLS = frozenset({"TXN", "ADI", "STM", "NXPI"})
```

### 2.3 三星 DS 2025Q1–2026Q2 官方回填索引

下表的库存和集团总库存来自 DART 报告中的 `C. Inventory / 다. 재고자산 현황`；收入和营业利润来自同一报告的分部摘要。DART 主报告链接可在线复核，原始 HTML 片段和 SHA-256 保存在 `data/raw/industry/semiconductor/korea_filings/`。

| 季度 | DART 报告 | DS 存货（KRW million） | 集团存货（KRW million） | DS 收入（KRW trillion） | DS 营业利润（KRW trillion） |
| :--- | :--- | ---: | ---: | ---: | ---: |
| 2025Q1 | [2025Q1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250515001922) | 30,414,507 | 53,220,267 | 25.1310 | 1.1055 |
| 2025Q2 | [2025H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814003156) | 27,842,495 | 51,037,413 | 27.8751 | 0.3502 |
| 2025Q3 | [2025Q3 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114002447) | 27,039,915 | 50,332,392 | 33.1168 | 6.9913 |
| 2025Q4 | [2025 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260310002820) | 28,805,919 | 52,636,828 | 44.0053 | 16.4111 |
| 2026Q1 | [2026Q1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260515002181) | 30,248,252 | 58,278,373 | 81.7156 | 53.6633 |
| 2026Q2 | [2026H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003699) | 38,056,737 | 71,389,118 | 127.5161 | 89.1960 |

其中 2025Q2–Q4 和 2026Q2 的收入/营业利润是报告累计值做相邻期间差分后的单季值；因此 `cost_of_revenue_krw` 不是报告直接列示的 DS COGS。

### 2.4 三星 DS 2016Q1–2024Q4 DART 回溯核验

2016Q1–2021Q4 的 DART 表仍使用旧组织结构：`CE`、`IM`、`DS`，其中 `DS` 下分别列出 `반도체` 和 `DP`，并另列 `DS 계`。本表改取 `반도체` / `반도체 사업` 的 `소계`，以统一为半导体业务并排除显示面板；2022Q1 起取新组织下的 `DS 부문`。集团总库存取同一张表的 `총계/소계`。金额单位均为 KRW million。2016–2017 年 DS/集团占比最低约 21.9%，仍是 DART 明确列示的半导体小计，因此历史门禁下限设为 20%。DART 2022Q1 报告同时说明 2021、2020 比较数据已按 2021 年 12 月组织变更重述，因此历史原始披露值仍保留 `inventory_scope` 标记。

2016Q1–2017Q4 新增回填如下：

| 季度 | DART 报告 | DS 分部库存 | 集团库存 | DS/集团 |
| :--- | :--- | ---: | ---: | ---: |
| 2016Q1 | [2016Q1 Quarterly Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20160516003174) | 7,402,406 | 18,749,882 | 39.48% |
| 2016Q2 | [2016H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20160816001779) | 7,057,845 | 17,858,721 | 39.52% |
| 2016Q3 | [2016Q3 Quarterly Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20161114001491) | 5,916,571 | 18,378,245 | 32.19% |
| 2016Q4 | [2016 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170331004518) | 5,271,825 | 18,353,503 | 28.72% |
| 2017Q1 | [2017Q1 Quarterly Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170515003806) | 5,346,323 | 21,857,598 | 24.46% |
| 2017Q2 | [2017H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170814001832) | 5,449,786 | 23,020,912 | 23.67% |
| 2017Q3 | [2017Q3 Quarterly Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20171114001694) | 5,925,096 | 27,032,501 | 21.92% |
| 2017Q4 | [2017 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20180402005019) | 6,972,814 | 24,983,355 | 27.91% |

| 季度 | DART 报告 | DS 分部库存 | 集团库存 | DS/集团 |
| :--- | :--- | ---: | ---: | ---: |
| 2018Q4 | [2018 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20190401004781) | 12,762,964 | 28,984,704 | 44.03% |
| 2019Q4 | [2019 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20200330003851) | 11,912,031 | 26,766,464 | 44.50% |
| 2020Q4 | [2020 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210309000744) | 13,906,811 | 32,043,145 | 43.40% |
| 2021Q1 | [2021Q1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210517001185) | 13,057,544 | 30,619,976 | 42.64% |
| 2021Q2 | [2021H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210817001416) | 12,617,490 | 33,592,385 | 37.56% |
| 2021Q3 | [2021Q3 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20211115001965) | 13,689,710 | 37,801,695 | 36.21% |
| 2021Q4 | [2021 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220308000798) | 16,274,418 | 41,384,404 | 39.33% |
| 2022Q1 | [2022Q1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220516001751) | 18,795,283 | 47,590,731 | 39.49% |
| 2022Q2 | [2022H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220816001711) | 21,507,990 | 52,092,241 | 41.29% |
| 2022Q3 | [2022Q3 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20221114001832) | 26,365,177 | 57,319,848 | 46.00% |
| 2022Q4 | [2022 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230307000542) | 29,057,604 | 52,187,866 | 55.68% |
| 2023Q1 | [2023Q1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230515002335) | 31,948,136 | 54,419,586 | 58.71% |
| 2023Q2 | [2023H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230814002534) | 33,689,632 | 55,504,798 | 60.70% |
| 2023Q3 | [2023Q3 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20231114002109) | 33,730,696 | 55,255,957 | 61.05% |
| 2023Q4 | [2023 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240312000736) | 30,998,770 | 51,625,874 | 60.05% |
| 2024Q1 | [2024Q1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240516001421) | 32,031,858 | 53,347,700 | 60.04% |
| 2024Q2 | [2024H1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240814003284) | 32,330,843 | 55,566,613 | 58.19% |
| 2024Q3 | [2024Q3 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20241114002642) | 31,596,306 | 53,356,759 | 59.23% |
| 2024Q4 | [2024 Business Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250311001085) | 29,688,574 | 51,754,865 | 57.37% |

这次回溯显示：原 RAW 中 2016Q1–2021Q4 的三星 DS 存货值已由包含 DP 的 `DS 계` 改为 DART 表中的纯 `반도체` / `반도체 사업` 小计；2022Q1–2024Q4 已使用 `DS 부문`。2016Q1–2026Q2 的分部摘要均已解析，成本统一记录为 `proxy_ds_revenue_minus_ds_operating_profit`；它不能解释为官方 DS COGS；三星纯存储库存继续标记为 `not_disclosed`。

### 2.5 SK 海力士 DART 来源统一与 Q4 成本推导

SK 海力士使用集团合并口径。现有 42 个观测季度（2016Q1–2026Q2）已全部切换到 DART 定期报告，原始“连接财务报表”快照和报告清单保存在 `data/raw/industry/semiconductor/korea_filings/`。`source` 固定为 `SK_HYNIX_DART_PERIODIC_REPORT`，`source_url` 固定为 DART 报告页。

本次增量回填补齐了 `2016Q1–Q3`、`2017Q1–Q3` 以及此前的 `2018Q1–Q3`、`2019Q1`、`2019Q3`、`2020Q1–Q2`、`2021Q1–Q2` 等历史缺口；这些季度均直接取对应 DART 报告的期末 `재고자산` 与当季合并 `매출원가`，未使用估算或跨源替代。

Q1–Q3 直接取同一 DART 报告的合并 `재고자산` 和当季 `매출원가`。Q4 年度报告的 `매출원가` 为全年累计值，因此使用同年度 Q3 DART 报告的 9 个月累计成本差分，`cost_of_revenue_source=official_consolidated_cost_of_revenue_derived_q4`，并在 `cost_of_revenue_annual_raw` 与 `cost_of_revenue_derivation` 中保留年度值、9M 报告 RCP 编号和 9M 原始值。

此前两期缺口的核验记录：

| 季度 | DART 报告 | 存货（bn KRW） | 营业成本（bn KRW） | DART 发布日 |
| :--- | :--- | ---: | ---: | :--- |
| 2025Q1 | [2025Q1 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250515002103) | 14,551.350 | 7,537.150 | 2025-05-15 |
| 2025Q3 | [2025Q3 Interim Report](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114001805) | 13,156.389 | 10,419.829 | 2025-11-14 |

两期已写入 `korea_memory_raw.csv`，并与其余 SK 海力士记录统一标记为 `SK_HYNIX_DART_PERIODIC_REPORT`，成本来源为 `official_consolidated_cost_of_revenue`。全量报告映射见 `sk_hynix_dart_source_manifest.csv`。

### 3.2 聚合算法（Transforms）
在每个报告季度 `report_quarter` 截面内：
1. **单标的 DOI**：
   $$\text{doi\_days}_i = \frac{\text{inventory\_usd\_million}_i}{\text{cost\_of\_revenue\_usd\_million}_i} \times 90.0$$
2. **全球综合加权 DOI**：
   $$\text{idm\_weighted\_doi\_days} = \frac{\sum_{i \in \text{All}} \text{inventory\_usd\_million}_i}{\sum_{i \in \text{All}} \text{cost\_of\_revenue\_usd\_million}_i} \times 90.0$$
3. **存储周期样本加权 DOI（非纯存储库存总额）**：
   $$\text{memory\_weighted\_doi\_days} = \frac{\sum_{i \in \text{Memory cohort}} \text{inventory\_usd\_million}_i}{\sum_{i \in \text{Memory cohort}} \text{cost\_of\_revenue\_usd\_million}_i} \times 90.0$$
4. **模拟/汽车专属加权 DOI**：
   $$\text{analog\_weighted\_doi\_days} = \frac{\sum_{i \in \text{Analog}} \text{inventory\_usd\_million}_i}{\sum_{i \in \text{Analog}} \text{cost\_of\_revenue\_usd\_million}_i} \times 90.0$$

---

## 4. 下游消费与影响面评估

### 4.1 供给端确认腿（`semiconductor_supply_legs`）
依据 `scripts/industry_direction_map.py` 中的 `build_semi_inventory_direction()`：
- 供给端库存腿 `inventory_score` 取的是 `idm_weighted_doi_days` 的 **12 季滚动同比增速分位**；
- 接入韩股后，存储周期（波动幅度大）与模拟周期（波动平缓、慢周期）形成有机平衡，彻底解决了原先由于模拟公司占比过大导致的“全行业去库已发生，但综合 DOI 迟钝下不来”的滞后偏差；
- 此外，可正式开放独立的 `memory_inventory_score`，精准指导申万二级半导体内部“存储芯片”细分方向的仓位进攻与防守。

### 4.2 信号状态机防守门（`defense_trigger`）
依据 `src/stock_analytics/marts/semiconductor_research.py`：
$$\text{defense\_trigger} = (\text{scissors\_score} < 20) \lor (\text{inventory\_score} \ge 80)$$
当全球原厂库存增速达到历史高位（贴顶区 $\ge 80$ 分位）时，触发半导体防御平仓或减仓。加权总存货体量扩增后，该防守信号的假阳性（False Positive）概率大幅降低。

---

## 5. 工程实施计划与任务分解

| 阶段 | 任务内容 | 产出物与代码位置 |
| :--- | :--- | :--- |
| **Phase 1** | **汇率引擎配置** | 1. 在 FRED 数据源中注册并拉取 `DEXKOUS` 日频序列<br>2. 新增 `transforms/fx.py` 实现双轨汇率折算函数 |
| **Phase 2** | **历史种子回填** | 1. 结构化两家 IR 历史数据并完成 DS 分部校验<br>2. 生成 `data/raw/industry/semiconductor/korea_memory_raw.csv` |
| **Phase 3** | **解析与转换升级** | 1. 编写 `parsers/korea_memory.py`<br>2. 改造 `transforms/inventory.py`（支持 KRW 汇率折算、多标的 `memory` 加权） |
| **Phase 4** | **回归与单测门禁** | 1. 汇率双轨折算单测<br>2. 三星 DS 分部合理性断言单测<br>3. 全球存储加权 DOI 验证单测（覆盖 2016-2026 全周期） |
