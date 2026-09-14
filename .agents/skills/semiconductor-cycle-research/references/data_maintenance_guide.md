# 半导体垂直产业数据采集、注册与运维手册 (Data Collection & Maintenance Guide)

> 适用角色：数据工程师、ETL 维护人员、增量采集与数据治理智能体。
> 核心目标：完整对齐 [`src/stock_data/fetcher/industry/semiconductor/registry.py`](../../../../src/stock_data/fetcher/industry/semiconductor/registry.py) 的**13 个核心半导体端点及设备商 GM 增量源任务**，规范采集器注册契约、RAW 目录布局、三类采集机制与标准化更新 SOP。
> 投研消费端与黄金表读取请参考：[`golden_tables_guide.md`](golden_tables_guide.md)。

---

## 1. 采集器注册全景与契约矩阵 (对齐 registry.py)

半导体产业采集器统一在 `registry.py` 中通过 `record_endpoint` 与 `frame_endpoint` 注册。`semiconductor_bundle` 保持以下 13 个核心端点；设备商 GM 的四个公司级任务另见第 3.4 节，不混入核心半导体包：

| 序号 | 端点名称 (`endpoint`) | 产研 RAW 子目录 (`raw_subdir`) | Curated 目标文件名 (`target_file`) | 采集器类 / 方法 (`collector`) | 主键约束 (`primary_keys`) | 采集机制分类 |
| :---: | :--- | :--- | :--- | :--- | :--- | :---: |
| 1 | `semiconductor_sales` | `semiconductor/sales` | `semiconductor_sales.parquet` | `SemiconductorCollector` | `[report_month]` | **类别 A** (智能嗅探) |
| 2 | `semiconductor_lead` | `semiconductor/sales` | `semiconductor_lead.parquet` | `TsmcLeadCollector` | `[report_month]` | **类别 B** (全量轮询) |
| 3 | `semiconductor_inventory_days` | `semiconductor/inventory` | `semiconductor_inventory_days.parquet` | `SemiconductorInventoryCollector.collect_raw` | `[report_quarter, symbol]` | **类别 A** (智能增量) |
| 4 | `semiconductor_channel_inventory` | `semiconductor/inventory` | `semiconductor_channel_inventory.parquet` | `ChannelInventoryCollector.collect_raw` | `[report_quarter, symbol]` | **类别 C** (RAW 存证) |
| 5 | `semiconductor_equipment` | `semiconductor/equipment` | `semiconductor_equipment.parquet` | `SeajEquipmentCollector` | `[report_month]` | **类别 B** (全量轮询) |
| 6 | `semiconductor_equipment_semi` | `semiconductor/equipment` | `semiconductor_equipment_semi.parquet` | `SemiEquipmentCollector.collect_raw` | `[report_quarter]` | **类别 C** (RAW 存证) |
| 7 | `foundry_capacity_utilization` | `semiconductor/capacity` | `foundry_capacity_utilization.parquet` | `FoundryUtilizationCollector.collect_raw` | `[report_quarter]` | **类别 A** (窗口抓取) |
| 8 | `chip_lead_time` | `semiconductor/capacity` | `chip_lead_time.parquet` | `SusquehannaLeadTimeCollector` | `[report_month]` | **类别 A** (智能增量) |
| 9 | `tsmc_advanced_packaging_revenue` | `semiconductor/capacity` | `tsmc_advanced_packaging_revenue.parquet` | `TsmcAdvancedPackagingRevenueCollector` | `[symbol, report_quarter]` | **类别 A** (智能在线增量) |
| 10 | `tsmc_cowos_capacity_estimates` | `semiconductor/capacity` | `tsmc_cowos_capacity_estimates.parquet` | `CowosCapacityEstimatesCollector` | `[symbol, agency, published_date, report_quarter]` | **类别 C** (RAW 存证) |
| 11 | `semiconductor_memory_price` | `semiconductor/price` | `semiconductor_memory_price.parquet` | `MemoryPriceCollector.collect_raw` | 复合多键 | **类别 B** (在线抓取) |
| 12 | `semiconductor_memory_benchmark` | `semiconductor/price` | `semiconductor_memory_benchmark.parquet` | `DataTrackMemoryPriceCollector` | `[report_month, product_family, indicator_id]` | **类别 B** (在线抓取) |
| 13 | `semiconductor_memory_taiwan_lead` | `semiconductor/price` | `semiconductor_memory_taiwan_lead.parquet` | `TaiwanMemoryLeadCollector` | `[report_month, symbol]` | **类别 B** (在线抓取) |

---

## 2. RAW 数据存储布局与存证规范

### 2.1 统一单数目录架构 (`data/raw/industry/semiconductor/`)

原先历史遗留的 `semiconductors/` 复数目录已彻底废除，顶层散落的 `lead_time/` 与 `tsmc/` 也已统一归并入 `semiconductor/`：

```
data/raw/industry/semiconductor/
├── sales/                           # RAW Tier 结构化表 (销售产出类)
│   ├── semiconductor_sales.parquet
│   └── semiconductor_lead.parquet
├── inventory/                       # RAW Tier 结构化表 (库存类)
│   ├── semiconductor_inventory_days.parquet
│   └── semiconductor_channel_inventory.parquet
├── equipment/                       # RAW Tier 结构化表 (设备类)
│   ├── semiconductor_equipment.parquet
│   └── semiconductor_equipment_semi.parquet
├── capacity/                        # RAW Tier 结构化表 (产能供给类)
│   ├── foundry_capacity_utilization.parquet
│   ├── chip_lead_time.parquet
│   ├── tsmc_advanced_packaging_revenue.parquet
│   └── tsmc_cowos_capacity_estimates.parquet
├── price/                           # RAW Tier 结构化表 (价格类)
│   ├── semiconductor_memory_price.parquet
│   ├── semiconductor_memory_benchmark.parquet
│   └── semiconductor_memory_taiwan_lead.parquet
├── sia/                             # WSTS 历史 Excel 底表与 SIA 新闻通稿快照
├── seaj/                            # SEAJ 日本设备出货额网页与快照
├── semi/                            # SEMI 全球设备出货官方新闻切片
├── foundry/                         # TSMC/SMIC 官方利用率运营报表原件 (PDF/HTML/CSV)
├── inventory/                       # 美股 IDM 10年财务 CSV 及 SEC 报表原始申报
├── korea_filings/                   # 韩国双雄官方 DART 报告 HTML 快照存证及双 Manifest
├── korea_memory_raw.csv             # 韩国双雄历史与增量财务存证底表 (与 korea_filings 关联)
├── tsmc_filings/                    # 台积电法说会官方 Management Report PDF 存证
├── cowos_estimates_sources/         # TrendForce 智库公报切片存证 (.txt)
├── datatrack/                       # TrendForce DataTrack JSON 原始缓存
├── taiwan_memory/                   # 台湾三大存储厂月营收网页抓取缓存
├── trendforce/                      # DRAM/NAND 现货与合约价格抓取快照
├── lead_time/                       # Susquehanna 芯片交期新闻与 RSS 快照
└── tsmc/                            # 台积电官网历史月度营收 HTML 归档
```

> [!NOTE]
> **产研分类物理隔离机制**：当 `runner.py` 将 RAW 2-Tier 数据写入产研分类子目录时（如 `semiconductor/sales/semiconductor_sales.parquet`），数据统一物理保存在对应产研维度子目录下，根目录下不再保留任何冗余软链接。

---

## 3. 三大采集机制与详细更新 SOP

### 3.1 类别 A：在线智能增量（Watermark / 动态嗅探驱动，无需人工介入）
- **核心逻辑**：自动感知本地已有水位，动态计算差额并向官方网络接口请求增量数据。
- **代表端点**：
  1. **`semiconductor_sales`**：
     - 每次运行时，[`SemiconductorCollector`](../../../../src/stock_data/fetcher/industry/semiconductor/collectors/sales.py#L42) 会自动请求 WSTS 官网公开入口页面（`https://www.wsts.org/67/Historical-Billings-Report`），提取最新发布的 `.xlsx` 下载链接并存证；
     - 同时并发抓取 SIA 官网最新通稿解析中国区月度数据与披露日；
     - 运行完成后**不再**派生 `semiconductor_china_series.parquet`（该 hook 已于 2026-09-10 退役：派生表与主表 `china_yoy_growth`/`china_mom_growth` 在 106 个共同月份上逐值一致、无独立消费方，真实消费方 `marts/semiconductor_research.py` 与 `scripts/industry_direction_three_layer.py` 读的都是主表）。
  2. **`chip_lead_time`**：通过 RSS 自动扫描尚未收录的最新月份 Susquehanna 交期数据。
   3. **`semiconductor_inventory_days`**：
      - 美股 5 家（TXN/ADI/STM/NXPI/MU）：在线请求 SEC EDGAR 补充最新披露的 10-Q/10-K；
      - 韩国双雄（三星 DS / SK 海力士）：增量采集由 [`KoreaMemoryDartCollector`](../../../../src/stock_data/fetcher/industry/semiconductor/collectors/korea_memory_dart.py#L118) 驱动，自动发现 DART 定期报告、按 `(filing_date, rcpNo)` 优选最新更正修订版、解析 Viewer HTML（分部存货/DS 营收利润/合并财务报表）、自动落地 HTML 存证与双 Manifest 并幂等合并回 `korea_memory_raw.csv`；
      - 校验与折算：强制要求两家信源 100% 来源 DART 官方报告（非 DART 来源在解析层会被 `ValueError` 阻断），执行三星 DS 存货比例安全区间门禁，并通过 FRED 汇率引擎按 IAS 21 准则完成双轨美元折算；网络不可用时自动回退已有 RAW；
      - **本土标的储备（CXMT）**：合肥长鑫（CXMT，长鑫科技集团股份有限公司，股票代码 `688825.SH`）已于 2026-07 在上交所科创板上市，其 2023–2025 年度审计财报及后续季报已具备法定公开数据通道，作为后续纳入第 8 家 IDM 存货天数跟踪的官方候选端点。
   4. **`foundry_capacity_utilization`**：
      - 按指定日期窗口在线爬取中芯国际与台积电官方公报；
      - **依赖受版本管理的 TSMC 历史利用率基线** `config/industry/semiconductor/tsmc_utilization_baseline.yaml`（加载与 schema 校验见 [`baseline.py`](../../../../src/stock_data/fetcher/industry/semiconductor/baseline.py)）：台积电自 2020 年代起季度管理报告不再给出利用率数字，[`build_foundry_raw_frame`](../../../../src/stock_data/fetcher/industry/semiconductor/transforms/foundry.py) 在官方值缺失时按报告期补齐并标 `tsmc_utilization_status = legacy_baseline`；
      - 基线文件缺失时**显式抛 `FileNotFoundError`**（不会静默清空 TSMC 信号）；基线覆盖外的季度（2026Q2 起）保持 NULL，严禁外推；
      - 基线 `provenance.status` 当前为 `unverified_upstream_injection`，**尚未与台积电官方披露逐条核对**：新增/修正必须人工确权后写入，并同步更新 `coverage` 声明（loader 会校验声明与条目是否一致）。
   5. **`tsmc_advanced_packaging_revenue`**：
      - 由 [`TsmcAdvPkgRevenueCrawler`](../../../../src/stock_data/fetcher/industry/semiconductor/collectors/tsmc_adv_pkg_crawler.py) 在线嗅探台积电官方 IR 结果页；
      - 自动探测并下载最新季度原生高清 Management Report PDF 存证至 `data/raw/industry/semiconductor/tsmc_filings/`；
      - 自动计算并比对 SHA-256 哈希防篡改指纹；
      - 自动提取新台币/美元营收、3/5/7nm先进技术占比、HPC平台占比、法说会日期，并安全追加写回 [`tsmc_adv_pkg_revenue_raw.csv`](../../../../data/raw/industry/semiconductor/tsmc_adv_pkg_revenue_raw.csv)，支持防重复与自动排序。

### 3.2 类别 B：按窗口在线采集，存储层增量合并（无需人工介入）
- **核心逻辑**：同步引擎把 Curated 水位转换为 `start_date/end_date`，采集器按上游可查询粒度只请求相关期间，返回结果再由 `save_curated_dataset` 按主键幂等合并。
- **`semiconductor_lead`（台积电月营收）**：按请求窗口只访问涉及的年度页面，解析后只返回窗口内月份；年度页面本身是上游最小请求粒度。
- **`semiconductor_equipment`（SEAJ 设备）**：窄的近期窗口只抓首页指向的最新速报 PDF；全量或较宽历史回填才下载历史 Excel。最新 PDF/历史 Excel 的结果均按窗口裁剪。
- **`semiconductor_memory_price`**：TrendForce 价格页是当前快照接口，采集器只保留请求窗口内的报价日期；接口没有历史区间参数，不把当前快照伪装成历史增量。
- **`semiconductor_memory_benchmark`（DataTrack）**：当前 DataTrack column API 返回完整历史序列且未提供有效日期查询参数，采集器仍按请求窗口过滤、只将窗口记录送入 ETL；网络层全历史响应属于上游接口限制，不能宣称为网络级区间请求。
- **`semiconductor_memory_taiwan_lead`**：按请求窗口限定年份和月份，只轮询窗口内的 MOPS 月度请求。

### 3.3 类别 C：RAW 存证与半自动驱动型（智库测算及未接入自动爬取源）
数据源头来自非结构化季报、第三方智库受控报告，需遵循 **2-Tier 存证与防篡改规范**：

#### SOP 1：台积电官方先进封装财务拆解 (`tsmc_advanced_packaging_revenue`)
> **状态：已全面实现程序化自动增量更新**。每季法说会后只需运行标准同步命令：
> `make sync-industry ENDPOINT=tsmc_advanced_packaging_revenue`
> 爬虫将全自动完成：嗅探新季度 -> 下载 PDF 存证 -> 计算 SHA-256 -> 结构化字段提取 -> RAW CSV 自动追加 -> 2-Tier ETL 刷新 Parquet。

若遇到极端网络阻断需进行**手动离线保底**时，可按以下步骤操作：
1. **获取源件**：访问 [TSMC IR](https://investor.tsmc.com/english/quarterly-results) 下载 **Management Report (PDF)**；
2. **存证归档**：存入 `data/raw/industry/semiconductor/tsmc_filings/tsmc_{year}q{quarter}_management_report.pdf`；
3. **计算哈希**：`shasum -a 256 data/raw/industry/semiconductor/tsmc_filings/tsmc_{year}q{quarter}_management_report.pdf | awk '{print $1}'`；
4. **录入/解析**：在 [`tsmc_adv_pkg_revenue_raw.csv`](../../../../data/raw/industry/semiconductor/tsmc_adv_pkg_revenue_raw.csv) 追加记录（或直接调用 `parse_tsmc_management_report_pdf` 自动提取），核心字段必须包含：`net_revenue_ntd_bn`、`net_revenue_usd_bn`、`advanced_wafer_pct`、`hpc_platform_pct`、`release_date`，硬约束 `data_status="actual"`。

#### SOP 2：智库 CoWoS 产能测算推演 (`tsmc_cowos_capacity_estimates`)
1. **获取源件**：访问 [TrendForce 官方新闻中心](https://www.trendforce.com/presscenter/) 获取 TSMC CoWoS 专项测算公报；
2. **存证归档**：保存原文文本至 `data/raw/industry/semiconductor/cowos_estimates_sources/trendforce_{YYYYMMDD}_cowos.txt`；
3. **计算哈希**：`shasum -a 256 data/raw/industry/semiconductor/cowos_estimates_sources/trendforce_{YYYYMMDD}_cowos.txt | awk "{print $1}"`；
4. **录入 RAW CSV**：在 [`cowos_capacity_estimates_raw.csv`](../../../../data/raw/industry/semiconductor/cowos_capacity_estimates_raw.csv) 追加一行，必须包含：`monthly_capacity_kwpm`、`lead_time_months`、`agency="TrendForce"`、真实 `published_date`。**若 `trade_date > published_date`，必须填 `data_status="forecast"`，严禁未来函数**。

#### SOP 3：SEMI 全球半导体设备季度出货 (`semiconductor_equipment_semi`)
1. **获取源件**：访问 [SEMI 新闻稿](https://www.semi.org/en/news-media-press-releases/semi-press-releases) 抓取 WWSEMS 季度与年度出货公报；
2. **存证归档**：新闻切片保存至 `data/raw/industry/semiconductor/semi/`（`.html.gz`），由 `parse_semi_article_text` 解析报告期、全球出货额，以及**仅年度公报才有**的 China 金额；
3. **增速口径（关键）**：`yoy_growth` / `qoq_growth` 一律由全球出货额序列 `pct_change` 自算，**不得采信新闻稿文本里的增速字符串**——页脚/侧栏"相关新闻"标题的增速会全文误抓（实测把 2018–2020 的 23 行 yoy 写成常数 `0.23`）。解析器已把季度与年度的增速提取都约束在「金额所在句」内；源端增速只保留在 RAW 作血统；
4. **重建方式**：`uv run python scripts/replay_industry_raw.py --metric semiconductor_equipment_semi`（离线重放，不联网；一次刷新 RAW 与 Curated）。重建后应无 `yoy_growth == 0.23`，且 yoy/qoq 与 `pct_change` 自算值逐值一致；
5. **中国区列口径（2026-09-11 补齐，当前覆盖 42/42 季）**：
   - **21 期**（2016-Q1~2016-Q3、2017-Q1~2017-Q3、2018-Q1~2020-Q3、2021-Q2/Q3、2022-Q1~Q3、2023-Q1）公报区域表是**文本表格**（6 列：区域 + 当季/上季/去年同期 + QoQ% + YoY%）。解析器 `_extract_regional_billings` 现按单元格读取；此前只认正文 `China … $X billion` 措辞，漏掉了 `China 2.64 1.77 2.01 49% 31%` 这类裸数字表。校验方式：**区域行加总 vs 全球出货额**，差额绝对值全 ≤0.05 B$；
   - **11 期**（2021-Q1、2023-Q2/Q3、2024-Q1~Q3、2025-Q1~Q3、2026-Q1/Q2）区域表为**内嵌图片**；已将官方图片快照保存到 `data/raw/industry/semiconductor/semi/`，并在 `regional_billings_image_ledger.csv` 中记录 URL、SHA-256、人工核对值和区域合计对账差额，最大绝对差额为 0.02 B$；
   - 另有 **10 期**（2016-Q4 至 2025-Q4 共 10 个 Q4）由**年度公报 China 值减前三季残差**推导，标记 `derived_from_annual`；其中 2016/2017 年度总额与 China 额优先从公报表格提取两位小数精确值（2016: 41.24/6.46，2017: 56.62/8.23），与次年回顾表 100% 严丝合缝；当前 China 列与全球总额全量覆盖 42/42 季（2016-Q1 至 2026-Q2）。
   ⇒ **禁止外推**；另注：**不要**用 SIA 的中国半导体**月度销售额**（`semiconductor_sales.china_yoy_growth`，原独立表 `semiconductor_china_series` 已退役）顶替本表 China **设备出货额**——两者是不同量。下游 `scripts/semi_seaj_reconciliation.py` 已带覆盖度声明。

#### SOP 4：全球通路商渠道库存天数 (`semiconductor_channel_inventory`)
> **状态：已接入 SEC XBRL companyfacts 在线采集（类别 C → 实为 API 拉取）**。主体为
> `ARW`（Arrow Electronics）与 `AVT`（Avnet），数据源 `source="SEC_companyfacts"`，
> 原始存证落在 `data/raw/industry/semiconductor/inventory/sec_companyfacts/` 与
> `data/raw/industry/semiconductor/sec_companyfacts/`（`.json.gz`）。
>
> ⚠️ **历史文档勘误**：本 SOP 早期版本记载"访问台湾公开资讯观测站（MOPS）下载大联大
> （3702.TW）与文晔科技（3036.TW）"，与实际数据源和主体均不符，已更正。
1. **获取源件**：调用 SEC `https://data.sec.gov/api/xbrl/companyfacts/CIK{...}.json` 拉取
   Arrow（ARW）/ Avnet（AVT）季度存货与营业成本；
2. **存证归档**：快照保存至 `data/raw/industry/semiconductor/inventory/sec_companyfacts/`，
   由 `ChannelInventoryCollector.collect_raw` 解析期末存货、营业成本并计算渠道 DOI
   （输出列 `channel_doi_days` / `channel_equal_doi_days` / `channel_weighted_doi_days`）。
   本表**无** `inventory_regime` 列。

#### SOP 5：韩国存储双雄存货与分部财务存证 (`semiconductor_inventory_days` 韩国部分)
由于韩国上市公司未接入 SEC EDGAR 标准 XBRL 体系，三星电子与 SK 海力士采用 **DART 官方财报自动增量存证 + 结构化底表驱动**：

1. **标准自动化增量（推荐方式）**：
   - 运行 `make sync-industry ENDPOINT=semiconductor_inventory_days` 时，系统自动通过 [`KoreaMemoryDartCollector`](../../../../src/stock_data/fetcher/industry/semiconductor/collectors/korea_memory_dart.py#L118) 扫描 DART 官方检索接口，自动完成报告发现、修订版过滤（`(report_quarter, filing_date, rcpNo)` 优选）、Viewer HTML 抽取、快照落地至 `korea_filings/`、Manifest 登记与 `korea_memory_raw.csv` 幂等合并；
   - **信源硬门禁**：三星 DS 与 SK 海力士必须 100% 来自 DART 定期报告（`SAMSUNG_DART_*` 与 `SK_HYNIX_DART_PERIODIC_REPORT`），任何非 DART 信源（如 SEC 6-K 或 IR 宣传材料）在加载时直接抛出 `ValueError` 阻断。

2. **断网/容灾人工回填 SOP（仅在自动化接口不可用时使用）**：
   - **获取源件**：
     - **三星电子**：访问 [DART](https://dart.fss.or.kr/) 官方 Interim/Business Report。DS 存货优先取报告的 `C. Inventory – The inventory status by Division`（韩文：`다. 재고자산 현황`），严禁从 IFRS `Segment Information - Balance Sheet` 推断；2016Q1–2021Q4 取旧表 `반도체` / `반도체 사업` 小计排除 DP，2022Q1 起取 `DS 부문`；DS 收入/营业利润取 `사업부문별 요약 재무 현황`；
     - **SK 海力士**：访问 [DART](https://dart.fss.or.kr/) 定期报告，解析 `2. 연결재무제표` 中的 `재고자산` 与 `매출원가`；IR、SEC 6-K 和债券 Prospectus 只可作人工交叉核验，不得作为 RAW 来源；
   - **存证归档与 Manifest**：保存在 `data/raw/industry/semiconductor/korea_filings/` 下，命名遵循 `samsung_electronics_{quarter}_{report_type}_inventory_by_division.html` 与 `sk_hynix_dart_{quarter}_{report_type}_consolidated_financial_statements.html`，同步更新 `samsung_dart_source_manifest.csv` 与 `sk_hynix_dart_source_manifest.csv`；
   - **录入 RAW 底表**：在 [`korea_memory_raw.csv`](../../../../data/raw/industry/semiconductor/korea_memory_raw.csv) 中追加记录：三星必须满足 `DS存货 / 集团存货 ∈ [35%, 70%]`（2021Q1 前旧组织表允许历史低位至 20%，2017Q3 实际约 21.9%）；COGS 代理使用 `cost_of_revenue_source=proxy_ds_revenue_minus_ds_operating_profit` 明确标记；SK 海力士记录期末合并存货与当季营业成本。

---

### 3.4 设备商 GM 四源增量与派生合并

设备商 GM 不再把四家公司混在一个在线采集器里：

- `semiconductor_equipment_gm_amat`、`semiconductor_equipment_gm_lrcx`、`semiconductor_equipment_gm_klac`：SEC accession + `release_date` 水位；RAW manifest 按公司保存；
- `tel_gm_quarterly`：TEL IR PDF URL 清单 + 发布日/文件名水位；RAW manifest 保存 PDF 哈希；
- `semiconductor_equipment_gm_multi`：只读取四张原子 Curated 表派生，不单独请求网络。

标准运行入口：

```bash
make sync-industry ENDPOINT=semiconductor_equipment_gm_bundle
```

四个原子任务必须全部成功或已是最新才允许重建 `multi`；任一任务失败会返回 `BLOCKED`，旧的 `multi` 表保持不变。需要吸收 SEC/IR 近期修订时才使用 `FORCE=1`。

## 4. 标准清洗落盘与数据运维命令

完成存证与 RAW 录入后，**严禁直接修改 Curated 黄金表**，必须通过系统标准 CLI 触发自动化 2-Tier ETL 处理：

```bash
# 半导体 13 个注册端点一起做水位感知增量同步（推荐）
make sync-industry ENDPOINT=semiconductor_bundle

# 等价的专用 Make 入口，避免误选跨行业 industry_tech_bundle
make sync-semiconductor

# 1. 增量同步单个端点
make sync-industry ENDPOINT=semiconductor_sales

# 2. 强制刷新整个半导体任务包（绕过水位/发布时间窗口/本地 RAW 命中，
#    但采集器仍遵守本次计划的 start_date/end_date 窗口）
make sync-industry ENDPOINT=semiconductor_bundle FORCE=1

# 3. 强制刷新单个端点
make sync-industry ENDPOINT=semiconductor_sales FORCE=1

# 4. 同步先进封装双轨端点
make sync-industry ENDPOINT=tsmc_advanced_packaging_revenue,tsmc_cowos_capacity_estimates

# 5. 只同步五个可按窗口增量采集的高频端点
make sync-industry ENDPOINT=semiconductor_lead,semiconductor_equipment,semiconductor_memory_price,semiconductor_memory_benchmark,semiconductor_memory_taiwan_lead

# 6. 设备商 GM 四个公司级增量源 + multi 派生表
make sync-industry ENDPOINT=semiconductor_equipment_gm_bundle
# 需要强制检查近期 SEC/IR 修订时：
make sync-industry ENDPOINT=semiconductor_equipment_gm_bundle FORCE=1
# 兼容历史 RAW 的离线重放/全量重建：
uv run --with pypdf python scripts/tel_quarterly_parse.py
uv run python scripts/equipment_giants_parse.py

# 7. 执行数据质量与完整性验证
make validate

# 8. 检查行业任务注册、任务包和别名
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_cli.task_health --provider industry

# 9. 运行半导体专项单测集合
make test TEST_PATH="tests/unit/stock_data/core/test_task_architecture.py tests/unit/stock_data/fetcher/test_semiconductor_paths.py tests/unit/stock_data/fetcher/test_industry_raw_contract.py tests/unit/stock_data/fetcher/test_semiconductor_inventory.py tests/unit/stock_data/fetcher/test_tsmc_adv_pkg_crawler.py tests/unit/stock_data/fetcher/test_tsmc_collector.py tests/unit/stock_data/fetcher/test_seaj_collector.py tests/unit/stock_data/fetcher/test_semiconductor_memory_price.py tests/unit/stock_data/fetcher/test_semiconductor_memory_benchmark.py"
```

`semiconductor_bundle` 覆盖本手册第 1 节列出的 13 个核心端点，展开后由统一同步引擎分别读取各任务水位、发布时间窗口和 RAW 缓存，再去重落盘；它不会把云厂商 CapEx、消费电子或设备商 GM 带入本次运行。

设备商 GM 使用独立的 `semiconductor_equipment_gm_bundle`：AMAT/LRCX/KLAC 分别维护 SEC accession 与 `release_date` 水位，TEL 维护 IR PDF 文件清单与发布日期水位；SEC RAW 位于 `data/raw/industry/semiconductor/equipment/sec_edgar/{AMAT,LRCX,KLAC}/`，TEL RAW 位于 `.../tel/ir_tanshin/`，每家公司目录均有 `manifest.csv`。四个原子 Curated 源表全部成功或已是最新后，才原子重建 `semiconductor_equipment_gm_multi`；任一源失败时保留旧合并表。

`industry_tech_bundle` 是跨行业科技观察包，包含半导体子集、云厂商 CapEx 和消费电子，缺少先进封装与 CoWoS 两个半导体专项端点；不能替代 `semiconductor_bundle`。

CoWoS 预测表属于 `manual_snapshot` 存证任务：已有 `published_date` 水位时，普通同步会标记为 `UP_TO_DATE`，只有新增或修订本地 RAW 后才使用 `FORCE=1` 重放，避免未来 `report_quarter` 造成重复采集。

注意：`make sync-industry` 不指定 `ENDPOINT` 时会同步 Industry Provider 的全部公开行业任务，不等于“半导体全量同步”。半导体日常同步应显式使用 `ENDPOINT=semiconductor_bundle`。

同步摘要中的 `SUCCESS` / `UP_TO_DATE` 表示已成功更新或已确认水位；`SKIPPED` 表示发布时间窗口未到；`NO_CHANGE` 表示请求成功但 Curated 没有变化；`EMPTY` 表示请求窗口内上游没有返回记录；`PARTIAL` 表示部分期间或来源缺失。当前 CLI 会将 `NO_CHANGE`、`EMPTY`、`PARTIAL` 计入非零退出码，因此退出码为 1 时必须结合摘要和对应 Parquet 最新水位判断，不能仅凭退出码认定任务包或数据管线失效。

---

## 5. 常见故障排查 (Troubleshooting)

1. **`AssertionError: RAW 快照文件不存在或 SHA-256 哈希不一致`**：
   - 检查 `raw_snapshot_path` 相对路径是否与物理文件完全一致；
   - 检查存证文件是否在生成哈希后被意外修改或追加了换行，重新运行 `shasum -a 256` 核对。
2. **`ValueError: 重复主键` 报错**：
   - 台积电官方表主键为 `[symbol, report_quarter]`，同一季度只能有一条官方法定事实；
   - CoWoS 智库推演表主键为 `[symbol, agency, published_date, report_quarter]`，若智库在不同时间对同一季度发布了调整预测，必须使用不同的 `published_date` 区分版本轨迹。
3. **`data_status 校验拦截`**：
   - 若预测期末 `trade_date` 晚于公报 `published_date`，`data_status` 必须为 `forecast` 或 `estimate`，填为 `actual` 将被质量门禁直接拦截阻断。
