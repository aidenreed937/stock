# 化工大宗与周期品量化投研配置总索引 (Chemicals Configuration Index)

本目录为 A 股大宗化工与周期品投研体系的**核心配置总索引**。

全库严格推行**“模块高内聚、品种独立自治、单一信任源 (SSOT)”**架构。原有单体大一统门面文件（`chemical_cost_models.yaml`、`company_elasticities.yaml`、`cyclical_trading_gates.yaml`）已全部解耦并物理移除，所有物理单耗、工艺成本、在建产能、公司画像、单吨业绩弹性与量化交易门禁均下沉至对应品种的独立子目录中。

---

## 1. 品种分类与子模块索引矩阵

全体系遵循大宗化工**三元分类法定价体系**：
- **A 类（大宗标准化与期货品种）**：完全竞争、由边际现金成本底线出清与交割仓单蓄水池强力支配；
- **B 类（周期性中游寡头品种）**：全球 CR5 > 75%，由寡头协同检修与月度挂牌价控盘强力支配；
- **C 类（行政配额管制型品种）**：法定冻结生产配额，切断高利润刺激盲目扩产的周期负反馈，由下游核心终端排产驱动。

| 子模块目录 | 品类代码 | 分类属性 | 核心覆盖标的 | 子模块完备文件清单 | 核心消费链路 |
| :--- | :---: | :---: | :--- | :--- | :--- |
| **[`soda_ash/`](soda_ash/)** | `SA` | A 类大宗 | 远兴能源、山东海化、中盐化工、三友化工、双环科技 | `cost_models.yaml`<br>`companies.yaml`<br>`capacity_projects.yaml`<br>`trading_gates.yaml`<br>`README.md` | `soda_ash/pipeline.py`<br>`soda_ash_company_panel.py`<br>`chemical_spreads.parquet` |
| **[`pta/`](pta/)** | `TA`<br>`POY` | A 类大宗 | 恒力石化、荣盛石化、桐昆股份、新凤鸣、恒逸石化 | `cost_models.yaml`<br>`companies.yaml`<br>`capacity_projects.yaml`<br>`trading_gates.yaml`<br>`company_projections.yaml`<br>`README.md` | `pta/pipeline.py`<br>`pta_company_panel.py`<br>`pta/projections.py` |
| **[`tio2/`](tio2/)** | `TIO2` | B 类寡头 | 龙佰集团、钛能化学、鲁北化工、安纳达、金浦钛业 | `cost_models.yaml`<br>`companies.yaml`<br>`capacity_projects.yaml`<br>`trading_gates.yaml`<br>`company_projections.yaml`<br>`README.md` | `tio2/pipeline.py`<br>`tio2_company_panel.py`<br>`tio2/projections.py` |
| **[`meg/`](meg/)** | `MEG` | A 类大宗 | 恒力石化、荣盛石化、华鲁恒升、东方盛虹、桐昆股份 | `cost_models.yaml`<br>`companies.yaml`<br>`capacity_projects.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`ChemicalSpreadCalculator` |
| **[`methanol/`](methanol/)** | `MA`<br>`UR` | A 类大宗 | 宝丰能源、华鲁恒升、兖矿能源、恒源煤电、金牛化工 | `cost_models.yaml`<br>`companies.yaml`<br>`capacity_projects.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`ChemicalSpreadCalculator` |
| **[`pvc/`](pvc/)** | `V` | A 类大宗 | 中泰化学、新疆天业、三友化工、中盐化工、氯碱化工、鲁西化工 | `cost_models.yaml`<br>`companies.yaml`<br>`capacity_projects.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`ChemicalSpreadCalculator` |
| **[`polyurethane/`](polyurethane/)** | `MDI`<br>`TDI` | B 类寡头 | 万华化学 | `companies.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_elasticity_mart.py`<br>周期策略与交易门禁引擎 |
| **[`refrigerant/`](refrigerant/)** | `R32`<br>`R134A` | C 类配额 | 巨化股份、三美股份 | `companies.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_elasticity_mart.py`<br>周期策略与交易门禁引擎 |
| **[`urea/`](urea/)** | `UR` | A 类大宗 | 华鲁恒升、阳煤化工、宝丰能源、鲁西化工 | `cost_models.yaml`<br>`companies.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`chemical_cross_section_mart.py` |
| **[`caustic_soda/`](caustic_soda/)** | `SH` | A 类大宗 | 中盐化工、三友化工、氯碱化工、新疆天业、中泰化学 | `cost_models.yaml`<br>`companies.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`chemical_cross_section_mart.py` |
| **[`styrene/`](styrene/)** | `EB` | A 类大宗 | 恒力石化、荣盛石化、华锦股份、新凤鸣、卫星化学 | `cost_models.yaml`<br>`companies.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`chemical_cross_section_mart.py` |
| **[`polypropylene/`](polypropylene/)** | `PP` | A 类大宗 | 宝丰能源、东华能源、恒力石化、中煤能源 | `cost_models.yaml`<br>`companies.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`chemical_cross_section_mart.py` |
| **[`paraxylene/`](paraxylene/)** | `PX` | A 类大宗 | 荣盛石化、恒力石化、东方盛虹、恒逸石化 | `cost_models.yaml`<br>`companies.yaml`<br>`trading_gates.yaml`<br>`README.md` | `chemical_cost_curves.py`<br>`chemical_elasticity_mart.py`<br>`chemical_cross_section_mart.py` |

---

## 2. 子模块标准文件规范 (Standard Artifacts Specification)

每个品种目录按照“基础设施完备、职责边界清晰”的标准进行组织：

### 2.1 `cost_models.yaml` (工艺理论成本与利润模型)
- **职责**：维护不同工艺路线（如天然碱/联碱/氨碱、煤制/油制、硫酸法/氯化法）的理论单耗系数、固定及折旧制造加工费、现金保本成本底线以及利润相位区间阈值（`high_profit`, `normal`, `near_breakeven`, `deep_loss`）。
- **消费方**：`stock_data.fetcher.industry.chemicals.collectors.spreads.ChemicalSpreadCalculator` 与 `chemical_cost_curves.py`。

### 2.2 `companies.yaml` (核心上市公司画像与业绩弹性库)
- **职责**：
  1. **定性画像**：工艺类型、生产基地、主营业务暴露度（`revenue_share_approx`）、成本曲线阶梯（`cost_tier`）及核心逻辑驱动因素；
  2. **量化弹性参数**：有效年产能（`annual_capacity_w_tons`）、权益比例（`equity_ratio`）、内部结转自用扣减比例（`internal_conversion_ratio`）、有效税率（`effective_tax_rate`）、增值税率（`vat_rate`）；
  3. **多品种扩展**：支持通过 `products` 挂载伴生/下游衍生品（如 PTA 下的涤纶长丝 `POY`、甲醇下的副产尿素 `UR`、聚氨酯下的 `TDI`、巨化股份下的 `R134a`）。
- **消费方**：`src/stock_analytics/marts/chemical_elasticity_mart.py` 及品种专用公司面板 Mart（如 `soda_ash_company_panel.py`）。

### 2.3 `capacity_projects.yaml` (重大新增与在建工程种子库)
- **职责**：跟踪国内拟建、在建装置的所属企业、基地位置、工艺路线、规划产能、预计点火与达产季度，防范远期供给反噬。
- **消费方**：`src/stock_data/fetcher/industry/chemicals/capacity_updater.py` 与各品种供需平衡表管线。

### 2.4 `trading_gates.yaml` (周期股分阶段量化交易门禁)
- **职责**：维护基于边际出清与库存时钟的分阶段买卖门禁规则：
  - **左侧赔率建仓门禁 (`left_side_odds`)**：跌破边际现金保本底线、深度破净低 PB、配置底仓上限（20%~35%）；
  - **右侧胜率确认门禁 (`right_side_confirmation`)**：装置实质性停产/检修负荷下降、连续去库周数、期货平水升水修复、放量突破 MA20、外需海关出口验证；
  - **逃顶一票否决门禁 (`top_escape`)**：开工率打满钝化、超额暴利极值、被动累库显现、个位数静态低 PE 诱多陷阱一票清仓；
  - **标的池映射 (`target_universe_mapping`)**：左侧抗亏龙头（`alpha_leader`）与右侧高弹性贝塔（`beta_elastic`）池。
- **消费方**：各品种专用管线 `gates.py`（如 `soda_ash/gates.py`、`pta/gates.py`、`tio2/gates.py`）及全市场中观轮动实盘推演。

### 2.5 `company_projections.yaml` (SOTP 业务分部预测模型 - 深度专用品种)
- **职责**：针对大炼化（恒力/桐昆）与钛白粉龙头（龙佰/钛能）等多业务复合标的，维护分部产能、自用抵消、工序 OPEX Bridge、情景利差标尺与财务去杠杆参数。
- **消费方**：`src/stock_analytics/pipelines/{pta,tio2}/projections.py`。

---

## 3. 全局自动化扫描与聚合消费架构

系统通过无状态加载器实现对各子模块配置的自适应聚合，杜绝根目录软链接或冗余同步：

1. **业绩弹性 Mart 自动聚合**：
   [`src/stock_analytics/marts/chemical_elasticity_mart.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_analytics/marts/chemical_elasticity_mart.py) 在不指定单一文件时，自动扫描 `config/industry/chemicals/*/companies.yaml`，提取并归一化全部 8 大品类、39 条标的弹性记录。
2. **多工艺边际成本曲线自动聚合**：
   [`src/stock_analytics/marts/chemical_cost_curves.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_analytics/marts/chemical_cost_curves.py) 与 `ChemicalSpreadCalculator` 按需装配各子模块的 `cost_models.yaml`，计算覆盖率阶梯与左侧极值出清信号。
3. **管线单一信任源直读**：
   各独立分析管线配置（`config/analytics/{soda_ash,pta,tio2}.yaml`）直接将对应子目录文件作为显式输入，不经由任何中间门面层。

---

## 4. 新增化工子模块标准作业程序 (SOP)

当未来扩展新化工品（如烧碱、工业硅、锂盐、化肥等）时，按以下规范创建：

1. **新建目录**：创建 `config/industry/chemicals/<new_product_slug>/`；
2. **落地标准四要素**：
   - 创建 `cost_models.yaml`：定义单耗、固定费与利润带；
   - 创建 `companies.yaml`：声明 `default_commodity_code` 并填报标的画像与弹性参数；
   - 创建 `capacity_projects.yaml`：列示行业在建新增装置；
   - 创建 `trading_gates.yaml`：依据品类属性（A/B/C）选配左侧/右侧/逃顶门禁；
   - 创建 `README.md`：说明品种基本面、核心驱动与代码消费方；
3. **测试门禁验证**：
   运行 `uv run pytest tests/unit/stock_analytics/pipelines/test_chemical_config_decoupling.py`，确保通过自洽性与完备性断言；
4. **更新本文档**：
   在第一节的索引矩阵中追加新模块行。
