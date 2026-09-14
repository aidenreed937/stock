# 半导体本地黄金事实表投研消费与读取指南 (Golden Tables Access Guide)

> 适用角色：量化研究员、策略分析师、宏观与产业投研人员。
> 核心目标：提供半导体全产业链 16 张 Curated 黄金事实表的**全景字段字典、时钟频率、主键契约与开箱即用的 Python/DuckDB 读取代码模版**。
> 底层数据采集、爬虫注册及 RAW 存证维护请参考：[`data_maintenance_guide.md`](data_maintenance_guide.md)。

---

## 1. 5 大产研分类维度资产全景表

所有半导体垂直产业事实表物理归集于 `data/curated/industry/semiconductor/<category>/`，消费层统一通过 `DataCatalog("industry")` 别名解析或规范子路径直接读取，根目录不再保留历史软链接。

### 1.1 销售与产出类 (`sales`) —— 同步产出流水确认
| 黄金表名称 | 物理相对路径 | 核心字段 | 主键 (Primary Keys) | 频次与见报日 | 投研角色 |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **`semiconductor_sales`** | `semiconductor/sales/semiconductor_sales.parquet` | `global_sales_usd`, `yoy_growth`, `mom_growth`, `china_sales_usd`, `china_yoy_growth`, `china_mom_growth`, `americas_sales_usd`, `europe_sales_usd`, `japan_sales_usd`, `asia_pacific_sales_usd`, `americas_yoy_growth`, `europe_yoy_growth`, `japan_yoy_growth`, `asia_pacific_yoy_growth` | `[report_month]` | 月频<br>(含 `release_date`) | 全球半导体总流水（3MMA），中观 Beta 基准线；分区域绝对额 + 分区域 YoY（口径与全球一致）供"分区域增速分化"分析 |
| **`semiconductor_lead`** | `semiconductor/sales/semiconductor_lead.parquet` | `tsmc_revenue_ntd_million`, `tsmc_revenue_usd_million`, `tsmc_revenue_yoy`, `tsmc_revenue_mom`, `tsmc_revenue_3mma_usd` | `[report_month]` | 月频<br>(次月10日披露) | 台积电（TSMC）月度营收，领先 SIA 约 1 个月 |
| **`cloud_capex_quarterly`** | `cloud_capex_quarterly.parquet` | `total_capex_billion_usd`, `msft_capex_billion_usd`, `goog_capex_billion_usd`, `meta_capex_billion_usd`, `amzn_capex_billion_usd`, `yoy_growth`, `qoq_growth` | `[report_quarter]` | 季频<br>(34 季) | 北美四大云厂商官方 10-Q 真实资本开支，AI/HPC 时代主导需求领先指标。注意：`release_date` 缺失回退 `trade_date`，消费时注意防范前视偏差 |

> [!NOTE]
> `semiconductor_sales` 的 4 个分区域 YoY 列已写入 Curated（前 12 个月为空属同比预热期）。
> **中国区列现状**：`china_sales_usd` 当前保持 NULL（SIA 只披露区域增速，从不披露中国区绝对额）；
> 中国区动能一律读取主表 `semiconductor_sales.china_yoy_growth`（主表 106 非空）与 `china_mom_growth`（主表 112 非空）。
> 历史曾独立存在的派生表 `semiconductor_china_series` 已彻底退役（与主表两列逐值一致，无独立消费方）；
> **任何情况下不得用代理或推算数据回填中国区绝对额。**

### 1.2 库存与出清类 (`inventory`) —— 供需边际与周期防守门
| 黄金表名称 | 物理相对路径 | 核心字段 | 主键 (Primary Keys) | 频次与见报日 | 投研角色 |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **`semiconductor_inventory_days`** | `semiconductor/inventory/semiconductor_inventory_days.parquet` | `doi_days`, `idm_equal_doi_days`, `idm_weighted_doi_days`, `memory_weighted_doi_days`, `analog_weighted_doi_days`, `inventory_regime`, `inventory_scope`, `cost_of_revenue_source`, `memory_inventory_status` | `[report_quarter, symbol]` | 季频<br>(含 `release_date`) | 全球 7 大原厂（美股5家+三星DS+海力士）加权库存天数，防守门一票否决。**覆盖注意**：三星 DS 与 SK 海力士各 42 期（2016Q1–2026Q2）；2016Q1–2026Q2 共 42 个季度均具备 7 家原厂，成分漂移已消除。当前 Curated 另有 2026Q3 的 ADI 单行，但因主体数不足，季度级聚合与相态留空。主体数 < 4 时（`MIN_INVENTORY_CONSTITUENTS`，7 家面板的半数）季度级聚合与相态**一律留空**，避免单家公司冒充行业口径；个股 `doi_days` 与合计不受影响。**三星 DS 口径边界（不可越界引用）**：`inventory_scope` = `legacy_semiconductor_business`(2016Q1–2021Q4) / `ds_division`(2022Q1 起)，仅整体半导体存货、已剔除 DP/SDC；`cost_of_revenue_source` 为 `proxy_ds_revenue_minus_ds_operating_profit`，**非官方 DS COGS**。故可用于库存趋势与 DOI 成本代理，但**不可**据此宣称纯 Memory/DRAM/NAND/HBM 存货（`memory_inventory_status = not_disclosed`）；跨公司对比须经 parser 统一单位与 KRW→USD 折算，勿直接消费 RAW CSV。依据：`docs/research/semiconductor/06_korea_memory_doi_integration_spec.md`。<br>• **本土 IDM 标的更新**：合肥长鑫（CXMT，长鑫科技集团股份有限公司，股票代码 `688825.SH`）已于 2026-07 在科创板挂牌上市，已具备法定审计年报与季度披露，为后续国内 DRAM 样本扩充与供给释放观察储备。 |
| **`semiconductor_channel_inventory`** | `semiconductor/inventory/semiconductor_channel_inventory.parquet` | `company`, `channel_doi_days`, `channel_equal_doi_days`, `channel_weighted_doi_days`, `inventory_usd_million`, `cost_of_revenue_usd_million` | `[report_quarter, symbol]` | 季频<br>(含 `release_date`) | 全球通路商渠道存货天数（`ARW` Arrow Electronics、`AVT` Avnet），反映终端出清速度。**注意**：主体为美国/全球通路商而非亚太通路商；本表**无** `inventory_regime` 列（渠道相态由 `stock_analytics` Mart 按阈值派生） |

### 1.3 设备与资本开支类 (`equipment`) —— 资本开支物化与先导
| 黄金表名称 | 物理相对路径 | 核心字段 | 主键 (Primary Keys) | 频次与见报日 | 投研角色 |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **`semiconductor_equipment`** | `semiconductor/equipment/semiconductor_equipment.parquet` | `billings_3mma_jpy`, `yoy_growth_3mma`, `mom_growth_3mma` | `[report_month]` | 月频 | 日本半导体设备制造协会（SEAJ）月度出货（3MMA 口径） |
| **`semiconductor_equipment_semi`** | `semiconductor/equipment/semiconductor_equipment_semi.parquet` | `global_billings_billion_usd`, `china_billings_billion_usd`, `yoy_growth`, `qoq_growth`, `china_share_pct` | `[report_quarter]` | 季频 | 全球半导体产业协会（SEMI）全球与区域设备出货。**覆盖范围**：已回填至 2016Q1–2026Q2 共 42 季（100% 具备官方源端快照与真实发布日）。**增速口径**：`yoy_growth` / `qoq_growth` 一律由全球出货额序列自算（`pct_change(4)` / `pct_change(1)`），**不采信新闻稿文本里的增速**；源端增速字符串只留在 RAW 层作血统。**中国区列口径（42/42 季全覆盖）**：21 期来自公报文本区域表，11 期来自官方内嵌区域图片的人工核对 ledger，另 10 个 Q4 由年度 China 值减前三季残差推导并标记 `derived_from_annual`。图片 URL、快照 SHA-256、China 值和区域合计对账差额见 `data/raw/industry/semiconductor/semi/regional_billings_image_ledger.csv`。**口径警告**：SIA 中国区**月度销售额增速**（`semiconductor_sales.china_yoy_growth`；原独立表 `semiconductor_china_series` 已退役）与本表的 China **设备出货额**是两个不同量，**不可互相填充**。yoy/qoq 一律由出货额序列 `pct_change` 自算，不采信新闻稿文本增速 |
| **`semiconductor_equipment_gm`** | `semiconductor/equipment/semiconductor_equipment_gm.parquet` | `net_sales_eur_m`, `gross_profit_eur_m`, `gross_margin_pct`, `net_income_eur_m`, `net_bookings_eur_m`, `systems_backlog_eur_m`, `gm_guidance_next_pct` | `[report_quarter]` | 季频 | ASML 季度法定毛利率与净销售额 |
| **`semiconductor_equipment_gm_multi`** | `semiconductor/equipment/semiconductor_equipment_gm_multi.parquet` | `company`, `gross_margin_pct`, `gm_guidance_next_pct`, `services_share_pct` | `[company, report_quarter]` | 季频 | 四家设备商 GM 派生合并表（LRCX/KLAC/AMAT/TEL）。由四个公司级增量源表全部成功或已是最新后原子重建；无 `symbol` 列，主体列名为 `company` |
| **四个设备商 GM 原子表** | `semiconductor/equipment/semiconductor_equipment_gm_{amat,lrcx,klac}.parquet` + `tel_gm_quarterly.parquet` | SEC 三家含 `report_period_end`；TEL 保留 `period_end`、日本 GAAP 字段 | `[company, report_quarter]` / `[report_quarter]` | 季频，按 `release_date` 水位 | `semiconductor_equipment_gm_amat/lrcx/klac` 从 SEC accession 增量采集；`tel_gm_quarterly` 从 TEL IR PDF URL 清单增量采集；源 RAW 下各自维护 `manifest.csv` |

### 1.4 供给约束与先进制造类 (`capacity`) —— 瓶颈刚性与交期约束
| 黄金表名称 | 物理相对路径 | 核心字段 | 主键 (Primary Keys) | 频次与见报日 | 投研角色 |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **`foundry_capacity_utilization`** | `semiconductor/capacity/foundry_capacity_utilization.parquet` | `tsmc_utilization_pct`, `smic_utilization_pct`, `foundry_weighted_utilization_pct`, `foundry_proxy_utilization_pct`, `proxy_status`, `utilization_regime` | `[report_quarter]` | 季频 | 晶圆代工产能利用率（TSMC/SMIC 出货面积加权）。**留空即正确**：单侧利用率不可得时加权值与 `utilization_regime` 同步留空（如 2026Q2 TSMC 侧 `unavailable`），是正确留空而非缺陷。**TSMC 基线口径（已收敛）**：2016Q1–2026Q1 共 41 个季度的利用率来自**受版本管理的基线文件** `config/industry/semiconductor/tsmc_utilization_baseline.yaml`，由 `build_foundry_raw_frame` 在官方值缺失时按报告期补齐并标 `tsmc_utilization_status = legacy_baseline`（加载与 schema 校验见 `src/stock_data/fetcher/industry/semiconductor/baseline.py`），live 采集与离线重放同源，重放已可复现线上全部 42 行信号。基线覆盖之外（2026Q2 起官方不再披露）保持 NULL，**严禁外推填补**。⚠️ 基线 `provenance.status = unverified_upstream_injection`：数值尚未与台积电官方披露逐条核对，**不可当作"台积电官方当期披露"引用**，对外引用前须先确权。⚠️ 已知未收敛项：重放重建的 `source_url` / `tsmc_source_url` / `smic_source_url` 与线上不同（线上是具体 PDF/公报 URL，重放回落到 IR 首页），故 `--strict-drift` 对该表仍会命中这 3 列，属**溯源列差异**而非信号改写 |
| **`chip_lead_time`** | `semiconductor/capacity/chip_lead_time.parquet` | `avg_lead_time_weeks`, `mcu_lead_time_weeks`, `lead_time_status` | `[report_month]` | 月频 | Susquehanna 芯片交期周数，拉长提示供给紧张 |
| **`tsmc_advanced_packaging_revenue`** | `semiconductor/capacity/tsmc_advanced_packaging_revenue.parquet` | `net_revenue_ntd_bn`, `net_revenue_usd_bn`, `advanced_wafer_pct`, `hpc_platform_pct`, `packaging_testing_others_pct` | `[symbol, report_quarter]` | 季频 | 台积电官方先进封测与财务拆解（actual） |
| **`tsmc_cowos_capacity_estimates`** | `semiconductor/capacity/tsmc_cowos_capacity_estimates.parquet` | `monthly_capacity_kwpm`, `lead_time_months`, `data_status` | `[symbol, agency, published_date, report_quarter]` | 动态更新 | TrendForce 智库 CoWoS 产能测算与交期（严格标记 forecast） |

### 1.5 价格与存储基准类 (`price`) —— 价格弹性高敏雷达
| 黄金表名称 | 物理相对路径 | 核心字段 | 主键 (Primary Keys) | 频次与见报日 | 投研角色 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`semiconductor_memory_price`** | `semiconductor/price/semiconductor_memory_price.parquet` | `product_family`, `price_scope`, `item`, `average_usd`, `high_usd`, `low_usd`, `session_change`, `average_change`, `low_change` | 复合多键<br>(`trade_date` × `product_family` × `price_scope` × `table_index` × `item`) | 日频/周频 | TrendForce DRAM/NAND 现货与合约价格跟踪。**注意**：该表为**覆盖式快照**，当前仅含 2 个 `trade_date`，**无法用于一阶导/二阶导计算**，亦无法产出任何合法分位；`item_raw` 仅属于 RAW 主键 |
| **`semiconductor_memory_benchmark`** | `semiconductor/price/semiconductor_memory_benchmark.parquet` | `product_family`, `indicator_id`, `indicator_name`, `price_usd`, `price_mom`, `price_yoy` | `[report_month, product_family, indicator_id]` | 月频 | TrendForce DataTrack 现货月度基准指标。**注意**：该表同一 `product_family` 下存在**多指标序列**，消费前必须先按 `indicator_id` 分区（详见 4.1 避坑规范）：<br>• `6105` Mainstream DRAM Spot Price（官方口径 **DDR5 16G (2Gx8) 4800/5600**）：覆盖 44 个月（2022-12 至 2026-07），来源纯 TrendForce；<br>• `61050` DRAM DDR4 16Gb 单列（来源 DRAMeXchange Wayback + DataTrack 现货，`data_status='wayback_proxy'`）：覆盖 2021-08 至 2026-08 共 **61 个月**，价格从 8.201 美元涨至 89.015 美元，**已满足 5Y 门槛（61 >= 60）**。**与 6105 规格不同（DDR4 vs DDR5），严禁拼入 6105 序列作单价格序列**，但推荐用于计算新旧代际比价系数（$\text{Price Parity Ratio} = \text{DDR4 16Gb} / \text{DDR5 16Gb}$）；<br>• `6106` Mainstream NAND Flash Wafer Spot Price（官方口径 **512Gb TLC**）：覆盖 60 个月（2021-08 至 2026-07，前 16 月为 Wayback 回补、后 44 月为 TrendForce，两段口径一致，**已满足 5Y 门槛**）。Curated 层通过 `datatrack_release_calendar.yaml` 补齐 `release_date`（标记 `release_date_status='proxy_calendar'`，含回补 16 个月），已支持严格 PIT 时钟截面对齐；RAW 层维持源端真实原貌（`unavailable`） |
| **`semiconductor_memory_taiwan_lead`** | `semiconductor/price/semiconductor_memory_taiwan_lead.parquet` | `symbol`, `company_name`, `revenue_ntd_million`, `revenue_usd_million`, `revenue_yoy`, `revenue_yoy_derived`, `revenue_mom`, `revenue_3mma_usd` | `[report_month, symbol]` | 月频 | 中国台湾存储厂月度营收先导。包含 2 个主体 —— `2408` 南亚科技（DRAM 原厂）、`3260` 威刚科技（模组龙头）；`revenue_yoy` 保留源端披露，`revenue_yoy_derived` 按 Curated NTD 营收重算，量化因子优先使用后者；已回填 2016-01 至 2026-08 全量 128 个月（共 256 条连续记录），**已满足 5Y 滚动分位门槛**；`release_date` 全为空（MOPS 月度营收表不含精确见报日） |

### 1.6 时间窗口可行性提示（对齐 `quant-metric-standards`）

`quant-metric-standards` 规定：**5Y 滚动窗口**为月频 60 期 / 季频 20 期，滚动窗口要求有效样本 ≥ 窗口长度的 80%（月频 ≥48 期 / 季频 ≥16 期）。半导体属于 3~5 年强周期产业，投研与特征工程统一以 **5Y 滚动分位**为核心基准，不强制要求 10Y。下表列出当前无法满足 5Y 滚动窗口的表（含分指标口径）：

| 表 | 频次 | 实际期数 | 5Y 可行性 | 缺口说明与核心制约 |
| :--- | :---: | ---: | :---: | :--- |
| `semiconductor_memory_price` | 日 | 2 | ❌ 缺 58 | **覆盖式快照**，仅含 2 个交易日，无法计算一阶导/二阶导与分位 |
| `tsmc_cowos_capacity_estimates` | 季 | 7 | ❌ 缺 13 | 智库测算推演（严格标记 forecast），历史样本极少 |
| `semiconductor_memory_benchmark` (6105 DRAM DDR5) | 月 | 44 | ❌ 缺 16 | DataTrack 官方 DDR5 序列仅 44 个月（2022-12 起），未达 60 月；**严禁用 61050 DDR4 拼接充数**（规格不同） |
| `semiconductor_memory_benchmark` (61050 DRAM DDR4) | 月 | 61 | ✅ 已达成 | 2021-08 至 2026-08 达 61 个月，可独立产出 5Y 滚动分位与一阶导/二阶导（严禁与 6105 拼接，建议做比价比值） |
| `semiconductor_memory_benchmark` (6106 NAND) | 月 | 60 | ✅ 已达成 | 2021-08 起 60 个月（Wayback 回补 16 月 + DataTrack 44 月，口径一致 512Gb TLC），可产出合法 5Y 分位 |

> [!WARNING]
> - `semiconductor_memory_benchmark` 的 5Y 判定**必须按 `indicator_id` 分区**：**6106 (NAND, 60月)** 与 **61050 (DDR4 16Gb, 61月)** 均已达成 5Y 门槛；6105 (DRAM DDR5) 仍为 44 月，不可单独产出合法 5Y 分位。
> - 61050 与 6105 是**两种不同规格**（DDR4 16Gb vs DDR5 16G），2022-12 前后价格不可直接连续化，**严禁将其拼接为一条伪连续价格序列**；但可构造无量纲指标 $\text{Price Parity Ratio} = \text{P}_{61050} / \text{P}_{6105}$ 观察技术迭代期的结构性倒挂与需求破坏。
> - 其余表（如 `semiconductor_memory_taiwan_lead` 已补齐至 128 月、`tsmc_advanced_packaging_revenue` 已补齐至 34 季、`semiconductor_equipment_semi` 已补齐至 42 季覆盖 2016Q1–2026Q2、`chip_lead_time` 104 月等）虽均已满足 5Y 门槛，但对于面板长表、见报日缺失表及成分漂移表，下游消费计算 5Y 滚动分位时必须严格遵循第 4 节避坑规范，严禁无分区或无去重直接滚动。

---

## 2. 规范读取指南与代码模版

### 2.1 方式一：DataCatalog 规范加载（推荐方式）

推荐在分析管线与研究脚本中优先使用 `DataCatalog`，系统已内置别名与分类多级路由：

```python
from stock_data.catalog import DataCatalog

cat = DataCatalog("industry")

# 1. 直接通过简短表名加载 (自动通过 StorageCompat 路由到子目录)
sales_df = cat.load_dataset("semiconductor_sales")
inventory_df = cat.load_dataset("semiconductor_inventory_days")

# 2. 或显式使用产研分类子路径加载
lead_df = cat.load_dataset("semiconductor/sales/semiconductor_lead")
cowos_df = cat.load_dataset("semiconductor/capacity/tsmc_cowos_capacity_estimates")

# 3. 检查加载结果
print("全球半导体销售额总月数:", len(sales_df))
print("最新月份:", sales_df["report_month"].max())
```

### 2.2 方式二：Polars 直接读取

利用 Polars 直接读取 5 大产研维度的规范物理文件：

```python
from pathlib import Path
import polars as pl

# 通过 5 大产研物理路径读取:
sales_path = Path("data/curated/industry/semiconductor/sales/semiconductor_sales.parquet")
sales_df = pl.read_parquet(sales_path)

print("加载行数:", len(sales_df))
```

### 2.3 方式三：DuckDB 极速跨表关联查询

用于多表 Join 与周期相位对齐：

```python
import duckdb

con = duckdb.connect()

# 关联 2024 年至今的全球销售额增速与全球原厂 IDM 存货周转天数
query = """
SELECT
    s.report_month,
    s.trade_date,
    s.global_sales_usd,
    s.yoy_growth AS sales_yoy,
    s.china_yoy_growth,
    i.idm_weighted_doi_days,
    i.memory_weighted_doi_days,
    i.inventory_regime
FROM "data/curated/industry/semiconductor/sales/semiconductor_sales.parquet" s
LEFT JOIN "data/curated/industry/semiconductor/inventory/semiconductor_inventory_days.parquet" i
    ON strftime(s.trade_date, "%YQ") || cast(quarter(s.trade_date) as varchar) = i.report_quarter
    AND i.symbol = "005930.KS_DS"
WHERE s.report_month >= "2024-01"
ORDER BY s.report_month DESC
LIMIT 12;
"""

result = con.execute(query).pl()
print(result)
```

---

## 3. 周期分析规范与投研纪律

1. **Ground Truth First**：所有数字必须读取自本地 Curated 黄金表，严禁凭记忆估算；
2. **严格防范前视偏差（Look-ahead Bias）**：
   - 回测与信号触发时，必须以数据行中的 `release_date`（真实见报日）作为可观测生效时间点，严禁以业务期间期末日 `trade_date` 发生逻辑穿梭；
   - 先进封装 CoWoS 测算等数据，需严格过滤 `data_status == "actual"` 或按 `published_date` 动态挂载 forecast。
3. **一阶导定方向，二阶导定拐点**：
   - 销售额与设备出货看同比增速 `yoy_growth` 定周期阶段；
   - 拐点判决看二阶导加速度 $\Delta\text{YoY} = \text{YoY}_t - \text{YoY}_{t-1}$。
4. **无量纲化去通胀**：
   - 严禁直接比较跨周期的绝对美元金额；一律采用分位数、YoY 增速或 DOI 天数比率。

---

## 4. 下游量化消费与特征工程避坑规范 (Downstream Guardrails)

为确保特征工程、量化回测与周期研报的数据真实性与统计严谨性，下游消费上述黄金表时必须严格遵守以下 5 项避坑规范：

### 4.1 面板长表（Panel Data）的分区与广播去重规范

| 黄金表 | 样本结构与期数 | 易踩陷阱 | 规范消费方式 |
| :--- | :--- | :--- | :--- |
| **`semiconductor_memory_taiwan_lead`** | 256 行（含 `2408`、`3260` 两个主体各 128 月） | 直接全表 `rolling(60)` 会导致两家公司跨标的数据串扰 | 必须 `PARTITION BY symbol` 或过滤单个标的计算 |
| **`semiconductor_inventory_days`** | 295 行（2016Q1–2026Q2 共 42 季 × 7 家原厂 + 2026Q3 单家 ADI 1 行） | 对 `idm_weighted_doi_days` 等聚合列直接 rolling，单个季度被重复统计 7 次 | 聚合列必须先 `SELECT DISTINCT report_quarter, ...` 降采样为单序列再计算滚动分位 |
| **`semiconductor_equipment_gm_multi`** | 172 行（4 家设备商） | 全表未按主体分组 rolling 会导致跨厂商毛利率混合 | 必须 `PARTITION BY company` 分组计算 |
| **`semiconductor_memory_benchmark`** | 120 行（`6105` DRAM 44 月 + `61050` DRAM 回补 16 月 + `6106` NAND 60 月） | 不按 `indicator_id` 分区直接 rolling 会把 DDR5(6105)、DDR4(61050)、NAND(6106) 三条规格序列混算；且 61050 与 6105 拼接会伪造 2022-12 规格切换跳变 | 必须 `PARTITION BY indicator_id`（或过滤单个 indicator）计算；61050 仅作独立对照，严禁与 6105 拼接 |

#### Polars 规范示例 1：行业原厂加权 DOI 5Y 滚动分位（先去重降采样再滚动）
```python
import polars as pl

df = pl.read_parquet("data/curated/industry/semiconductor/inventory/semiconductor_inventory_days.parquet")

# 1. 先去重抽取季度级唯一的行业加权 DOI 序列
# 2. 季频 5Y 窗口为 20 期 (有效样本 >= 16 期)
quarterly_doi_5y = (
    df.select(["report_quarter", "idm_weighted_doi_days"])
    .unique(subset=["report_quarter"])
    .sort("report_quarter")
    .with_columns(
        pl.col("idm_weighted_doi_days")
        .rolling_map(
            function=lambda s: float((s.rank().to_numpy()[-1] - 1) / (len(s) - 1) * 100) if len(s) >= 16 else None,
            window_size=20,
            min_samples=16,
        )
        .alias("idm_doi_5y_percentile")
    )
)
```

#### Polars 规范示例 2：台湾存储先导月度营收 5Y 滚动分位（必须按 symbol 分区）
```python
import polars as pl

df = pl.read_parquet("data/curated/industry/semiconductor/price/semiconductor_memory_taiwan_lead.parquet")

# 必须按 symbol 分区计算滚动分位，严禁全表混算；月频 5Y 窗口为 60 期 (有效样本 >= 48 期)
df_with_pct = df.sort(["symbol", "report_month"]).with_columns(
    pl.col("revenue_yoy")
    .rolling_map(
        function=lambda s: float((s.rank().to_numpy()[-1] - 1) / (len(s) - 1) * 100) if len(s) >= 48 else None,
        window_size=60,
        min_samples=48,
    )
    .over("symbol")
    .alias("revenue_yoy_5y_percentile")
)
```

### 4.2 见报日缺失表的时钟代理规范（严格防范前视偏差）

1. **时钟状态说明与分类**：
   * `semiconductor_memory_benchmark`（60 个月，含 Wayback 回补 16 个月）：源端 RAW 不含发布日（RAW 维持 `unavailable` 存证），Curated 层已通过受控发布日历（`config/industry/semiconductor/datatrack_release_calendar.yaml`）注入次月第 3 工作日保守代理（回补段同样按日历补齐），显式标记 `release_date_status = "proxy_calendar"`，下游可直接消费 `release_date` 进行无未来函数的 PIT 截面对齐；
   * `semiconductor_memory_taiwan_lead`（128 个月）：`release_date` 100% 缺失（`release_date_status = "unavailable"`，MOPS 月度营运简报源端不含精确日）；
   * `semiconductor_sales` 早期历史（1986–2015）`release_date` 缺失（全表覆盖率 32.3%）。
2. **下游处理禁令与代理方案**：
   * **严禁行为**：严禁在日频回测或信号生成时直接以业务期末日（`trade_date`，如 2026-08-31）作为特征生效日，这属于严重的未来函数穿梭；
   * **标准时钟代理**：针对 `release_date_status = "unavailable"` 的无精确 `release_date` 月频序列，在回测与截面挂载时统一强制应用**披露滞后代理**：
     $$\text{effective\_date} = \text{report\_month 次月 10 日}$$
     （依据台湾证期局规定，上市柜公司须于次月 10 日前公告上月营运简报；WSTS 全球销售额亦通常于次月下旬发布）。对于已标记 `proxy_calendar` 的表则可直接消费其已对齐的 `release_date`。

### 4.3 CoWoS 预测修订的版本感知增速规范

`tsmc_cowos_capacity_estimates` 的主键包含 `published_date`，同一 `report_quarter` 可以有多条智库修订。Curated 的 `capacity_yoy` / `capacity_qoq` 必须只引用当前行 `published_date` 当时已经可见的上一期或去年同期版本；禁止按当前全表排序后让同一报告期的修订值互相计算。

下游回测或截面挂载仍需先按 `published_date <= as_of_date` 过滤，再按 `(agency, report_quarter)` 选最新版本；`trade_date` 是预测目标期，不是预测生效日。`data_status = "forecast"` 不得参与实际值序列的 5Y 分位或库存周期事实腿。

### 4.4 比例字段的统一尺度契约

半导体 Curated 统一使用两种显式尺度：

- `ratio`：小数比例，例如 `0.74` 表示 74%；增长率也以小数保存；
- `percent_points`：百分点评分，例如 `74.0` 表示 74 个百分点，适用于利用率、毛利率和中国设备份额。

`advanced_wafer_pct`、`hpc_platform_pct`、`packaging_testing_others_pct` 属于 `ratio`；`*_utilization_pct`、`gross_margin_pct`、`gm_guidance_next_pct`、`services_share_pct`、`china_share_pct` 属于 `percent_points`。`lead_time_yoy_weeks` / `lead_time_mom_weeks` 是 `weeks_delta`，不是 ratio。

设备商 GM 已拆成四个公司级增量任务，并通过 `semiconductor_equipment_gm_bundle` 调度；`semiconductor_equipment_gm_multi` 仅是派生合并表，不直接采集。ASML 的 `semiconductor_equipment_gm` 仍由本地解析脚本维护。滚动计算必须按 `company` 分区，并以 `release_date` 做可用性对齐。

### 4.5 序列断点与合法留空（Valid NULLs）防虚假填充

1. **晶圆代工产能利用率断点**：
   * `foundry_capacity_utilization` 中台积电官方自 2026Q2 起停止披露单季产能利用率，导致 2026Q2 的 `foundry_weighted_utilization_pct` 和 `utilization_regime` 依法留空（NULL）；
2. **下游消费规范**：
   * 该留空属于数据契约规定的**合法留空**（并非流水断流或系统 Bug）；
   * **严禁无条件 `ffill()`**：特征工程中严禁对其调用前向填充（`ffill`）或插值，否则会凭空伪造高景气信号；
   * **特征容错**：下游多因子与规则引擎必须允许利用率相关特征合法缺失，并进入防御分支或回落至单侧/代理指标。

### 4.4 历史成分结构漂移（Composition Shift）已消除说明

1. **原厂库存样本历史同构（2016Q1–2026Q2）**：
   * `semiconductor_inventory_days` 的 2016Q1–2026Q2 连续 42 个季度均覆盖全球 7 家原厂（美股 5 家 + 三星 DS + SK 海力士），历史成分漂移已彻底消除；
   * 2016 年以来的任意连续 5Y（20 季）与 10Y（40 季）滚动窗口均满足同构样本要求，无需再针对 2016–2017 年做样本非对称声明。
2. **最新未结季度留空纪律**：
   * 2026Q3 目前仅 ADI 1 家已披露，由于主体数低于 `MIN_INVENTORY_CONSTITUENTS = 4` 门槛，季度聚合列与相态主动留空（NULL），避免单家主体冒充行业整体；
   * 下游特征工程在消费最新季度时，须兼容合法 NULL 值，严禁无条件 `ffill()`。

### 4.5 冗余表防多重共线性规范

1. **TEL 季度毛利率表**：
   * `tel_gm_quarterly`（57 季）与 `semiconductor_equipment_gm_multi` 中 `company = "TEL"` 的子集（57 季，FY2011-Q4 ~ FY2027-Q1）完全等价；
2. **规范消费**：
   * 下游构建量化特征矩阵时，建议统一读取 `semiconductor_equipment_gm_multi`；
   * 严禁同时将两张表作为两项独立因子喂入下游模型，避免引入 100% 线性相关的冗余特征。
