# 纯碱因果链与反馈时钟：数据可用性与缺口清单

> 定位：评估「宏观 → 供需物理量 → 价差 → 利润 → 库存 → 企业盈利 → 股价」因果链与反馈时钟在本地数据底座上的可行性，并输出数据缺口清单与补采建议。
> 范围：只做评估与清单，不修改数据管线。
> 检查基准：本地数据快照（raw 采集批次 collected_at 约 2026-09-01 ~ 2026-09-15），报告基准月 2026-08。

## 0. 结论摘要

1. **主干可行**：NBS 官方产量、玻璃需求、GACC 出口、郑商所仓单、周度开工率、多工艺成本模型、申万 L2 估值分位、个股行情与财报均已落库；`scripts/soda_ash_mvp_pipeline.py` 已跑通 8 层最小闭环，产物见 `data/analytics/industry_strategy/soda_ash_mvp_panorama.md`。
2. **机制叙事/拐点定位（可立即做）**：2021 能耗双控大顶、2023-2024 远兴天然碱冲击、当前盈亏平衡附近的供给出清，用现有数据即可复盘与定位。
3. **严格量化进度**：
   - **连续周频「价差/利润」序列已攻克**：已落地生意社 100ppi 现货出厂基准日频表 `data/curated/industry/chemical_spot_price.parquet`（4,015 行）与 2019-12 至今 352 周连续价差事实表 `data/curated/industry/chemical_spreads.parquet`，支持现货出厂轨、期货主力连续轨、双吨理论利润与实时基差率；
   - 仍缺两类硬数据：
     - 社会库存 + 完整的周度厂库/出货率（未授权商业源，维持 NULL）；
     - 纯碱上市公司盈利 → 股价面板（公司映射、存货跌价科目待建）。
4. 另有产能/检修日历、期货主力持仓、宏观先行指标未接入等次级缺口。

## 1. 因果链数据资产盘点（按环节）

| 因果环节 | 核心指标 | 本地路径 | 覆盖 | 状态 |
| :--- | :--- | :--- | :--- | :---: |
| 1. 宏观 | M1/M2 | `data/curated/lixinger/market=CN/cn_m/data.parquet` | 在库 | 可用，未接入纯碱链 |
| 1. 宏观 | 社融 | `data/curated/lixinger/market=CN/sf_month/data.parquet` | 在库 | 可用，未接入纯碱链 |
| 1. 宏观 | 利率/国债/原油 | `data/curated/lixinger/market=CN/{interest_rates,national_debt,crude_oil}/data.parquet`；FRED 宏观序列 | 在库 | 可用，未接入纯碱链 |
| 1. 宏观 | 地产新开工/竣工/销售 | 未见本地 Curated 数据集 | 无 | **缺失** |
| 2. 供需物理量 | 纯碱月度产量 | `data/raw/industry/chemicals/nbs/nbs_soda_ash_monthly.csv` | 2016-09 ~ 2026-07（2026-01/02 为合并披露，2026-08 未出） | 可用 |
| 2. 供需物理量 | 平板玻璃产量 | `data/raw/industry/chemicals/nbs/nbs_plate_glass_monthly.csv` | 同期 | 可用（滞后物理量，非先行指标） |
| 2. 供需物理量 | 纯碱出口 | `data/curated/industry/customs_trade_gacc.parquet`（HS 28362000） | 在库 | 可用 |
| 2. 供需物理量 | 周度开工率/周产量 | `data/raw/industry/chemicals/operating_rates/weekly_survey.csv` | 纯碱约 296 行，2021-01 起 | 可用 |
| 2. 供需物理量 | 有效产能/投产事件 | `config/industry/chemicals/soda_ash/capacity_projects.yaml`；`data/raw/industry/chemicals/capacity/soda_ash_annual_capacity.csv` | 种子库（远兴/金山/连云港等） | 部分可用 |
| 3. 价差 | 现货价格与理论价差 | `data/curated/industry/chemical_spot_price.parquet`（100ppi 出厂基准，4,015 行日频）；`data/curated/industry/chemical_spreads.parquet`（352 周连续价差） | 现货 365 天日频 + 价差 2019-12 至今 352 周连续 | **已解决（双轨基准）** |
| 3. 价差 | 月度价格列 | `data/raw/industry/chemicals/chemical_operating_spreads.csv` | 价格/开工/社会库存列历史全空 | 缺失（由连续周表替代） |
| 3. 价差 | 多工艺成本模型 | `config/industry/chemicals/soda_ash/cost_models.yaml` | 联碱/氨碱/天然碱，2018 起 | 可用（品种级唯一维护源） |
| 4. 库存 | 郑商所纯碱注册仓单 | `data/raw/industry/chemicals/futures_inventory/SA.csv` | 2020-04 起日频连续（1,568 交易日） | **已解决** |
| 4. 库存 | 样本企业周度厂库 | `data/raw/industry/chemicals/operating_rates/weekly_survey.csv` | 2026 年多个月份缺失 | 部分可用 |
| 4. 库存 | 社会库存 | `chemical_social_inventory` 列 | 全空（未授权商业源，保持 NULL） | **缺失** |
| 5. 企业盈利 | 三大报表 | `data/curated/tushare/market=CN/{income,balancesheet,cashflow}/` | 2001 起季频，最新约 2026-06 | 可用，未建成纯碱面板 |
| 5. 企业盈利 | 公司主营暴露度 | `config/data/customs/company_segment_binding.csv` | 仅远兴能源 000683.SZ（纯碱 65%）、三友化工 600409.SH（13.8%） | 部分可用 |
| 6. 股价/估值 | 申万二级行业行情与 PE/PB 分位 | `data/curated/mart/industry_l2_daily.parquet`（220200 化学原料） | 日频 | 可用 |
| 6. 股价/估值 | 个股日线/估值因子 | `data/curated/tushare/market=CN/daily/`、`daily_basic/` | 2013-01 ~ 2026-07 | 可用 |
| 反馈时钟 | 期货主力前 20 席位持仓 | `data/curated/industry/futures_hold_rank.parquet`；raw `data/raw/industry/chemicals/futures_hold_rank/SA_20240828.csv` | SA 覆盖几乎为空 | **缺失** |

## 2. 缺口清单

### P0（阻塞严格因果链，必须补）

1. **连续周频价差/利润序列（已解决）**
   - 现状：已于 2026-09 落地生意社 100ppi 现货出厂基准采集器（覆盖纯碱轻/重、尿素、动力煤等 11 品种日频），并与郑商所 SA 期货主力结算对齐，产出 352 周连续价差黄金事实表 `data/curated/industry/chemical_spreads.parquet`。
   - 指标体系：涵盖现货出厂轨、期货主力连续轨、双吨理论利润与实时基差率（最新重碱出厂 1090 元/吨 vs SA0 主力 1018 元/吨，基差 +72 元/吨，基差率 +7.07%）。
   - 数据状态机：明确区分 `actual`（调研实测）、`spot_benchmark`（100ppi 出厂基准）与 `benchmark`（期货主力折算）。

2. **社会库存 + 完整厂库/出货率**
   - 现状：`chemical_social_inventory` 列全空；周度厂库 2026 年多个月份为空，`shipment_rate_pct` 几乎全空。
   - 影响：被动累库/主动去库只能靠仓单 + 产量 + 价格代理，无法独立识别投机囤货与贸易商蓄水池。
   - 需补：隆众/百川口径社会库存、样本企业厂库补全、出货率；未获授权字段维持 NULL，不插值。

3. **纯碱上市公司盈利 → 股价面板**
   - 现状：财报与行情在库，但 `config/universe/watchlist.yaml` 无纯碱公司；公司暴露度只绑定远兴/三友；存货跌价准备科目未单独入库。
   - 需补：公司池（建议 000683.SZ 远兴能源、000822.SZ 山东海化、600328.SH 中盐化工、600409.SH 三友化工、000707.SZ 双环科技）+ 主营占比 binding + 季报归母净利/存货/存货跌价准备 + 个股 PB 5Y/10Y 分位。

### P1（影响反馈时钟完整度）

4. **宏观先行指标未接入纯碱链**
   - M2/社融/利率已在库但未与 MVP 合并；地产新开工/竣工/30 大中城市成交无本地数据；平板玻璃产量是滞后物理量，不能替代宏观先行腿。

5. **产能/检修日历不全**
   - `config/industry/chemicals/soda_ash/capacity_projects.yaml` 是种子库（远兴/金山/连云港），非全行业按工艺路线/厂家的投产-检修-退出日历；边际成本曲线出清模拟只能近似。

6. **期货主力持仓（聪明钱）覆盖空**
   - `futures_hold_rank` 的 SA 数据几乎为空（raw 仅 2024-08-28 一个快照），MVP 报告中「前 20 净多单」全部 `--`。

### P2（口径/时效细节）

7. NBS 单月缺失：2026-01/02 为合并披露、2026-08 未发布（T+20 时效所致），处理时用累计值口径。
8. 成本模型参数（天然碱 800~1000 元/吨、氨碱现金保本 1400~1500 元/吨等）为配置估算，缺实时装置级现金成本核验；建议用稀疏锚点定期校准并标注置信度。

## 3. 缺口对研究目标的影响

| 研究目标 | 可行性 | 前提 |
| :--- | :---: | :--- |
| 机制叙事 + 大拐点复盘（2021 大顶、2023-2024 远兴冲击） | 可行 | 现有数据即可 |
| 周期定位 + 左侧/右侧/逃顶门禁 | 基本可行 | 价差/利润用稀疏锚点 + 模型测算，标注低置信 |
| 环节间领先/滞后时滞与因果强度估计 | 暂不可行 | 需 P0 连续价差/库存序列（样本 ≥ 2020-2026） |
| 估值反向时钟 / 戴维斯双击回测 | 部分可行 | 行业 L2 分位可用；个股级需先建公司面板 |
| 完整反馈时钟（暴利 → Capex → 2-3 年后供给反噬） | 部分可行 | 需全行业产能/检修日历 + 10Y 数据 |

## 4. 补采建议（仅清单，不实施）

- **价格/价差**：隆众 / 百川 / 生意社周频现货（纯碱、氯化铵、原盐、合成氨、动力煤、块煤、石灰石），2019-12 起；郑商所 SA 期货日频与基差。
- **库存**：社会库存（隆众/百川口径）；厂库、出货率周频补全。
- **公司面板**：watchlist 增加纯碱公司池；`company_segment_binding.csv` 补主营占比；财报提取存货与存货跌价准备；`daily_basic` 计算 PB 分位。
- **宏观先行**：NBS/中指/克而瑞地产新开工、竣工、销售面积；把 M2/社融/利率接入 MVP 月度主表。
- **供给日历**：按工艺路线拆分全行业有效产能表，维护检修/复产/退出事件。
- **期货**：补 SA 主力持仓龙虎榜日频（2020 起）。

## 5. 与现有代码/配置的一致性风险

- `config/data_sources/chemicals_registry.yaml` 将 `chemical_spreads`、`chemical_capacity_utilization_10y` 标为 `unavailable`，但 MVP 管线已在消费价差/产能文件；后续应区分「连续序列」与「稀疏锚点」两种状态，避免误用。
- MVP 报告 `data/analytics/industry_strategy/soda_ash_mvp_panorama.md` 中 2026-01/02/08 产量、2026 多个月厂库/利润为 `--`，是真实数据缺口而非管线故障。

## 6. 检查基准与证据

- 本清单依据本地文件核对（2026-09-15 会话）：
  - `data/raw/industry/chemicals/chemical_spreads.csv`（13 行，SA 8 点）
  - `data/raw/industry/chemicals/chemical_operating_spreads.csv`（NBS 列有值，价格/库存列空）
  - `data/raw/industry/chemicals/operating_rates/weekly_survey.csv`（纯碱约 296 行，2021-01 起）
  - `data/raw/industry/chemicals/nbs/nbs_soda_ash_monthly.csv`（2016-09 ~ 2026-07）
  - `data/curated/tushare/market=CN/daily_basic/`（2013-01 ~ 2026-07）、`income/` 等（2001 起季频）
  - `data/curated/lixinger/market=CN/{cn_m,sf_month,interest_rates}/`
  - `data/curated/mart/industry_l2_daily.parquet`、`data/curated/industry/futures_hold_rank.parquet`
  - `config/data_sources/chemicals_registry.yaml`、`config/industry/chemicals/soda_ash/cost_models.yaml`、`config/industry/chemicals/soda_ash/capacity_projects.yaml`
