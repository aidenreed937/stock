---
name: data-catalog
description: 本地落盘数据资产统一目录 (DataCatalog) 与极速查询技能。用于一键查看全库/单源各数据集最新落盘时间、数据覆盖率、缺口诊断、单表加载及 Python API 规范调用。
---

# 数据资产目录服务 (DataCatalog) 技能指南

本技能为量化投研系统提供统一的**本地落盘黄金数据资产盘点、最新水位嗅探、数据加载与缺口诊断**的标准操作指南。

遵循**渐进式披露**原则，本入口聚合高频 Python 查询 API 与数据集快速路由索引；深入数据字典、分析范例与时滞避坑请查阅对应专题。

领域职责与分析层落点以 [`docs/architecture/domain-responsibilities.md`](../../../docs/architecture/domain-responsibilities.md) 为准：`DataCatalog` 负责 Curated 黄金数据集查询，`FeatureStore` 负责 `market_daily`、Feature 长表和领域 Mart；本技能不改变上游采集边界，也不要求领域 Mart 直接请求远程 API。

申万行业是例外的跨源查询场景：行业行情和估值仍读取各自源表，但 SW2021 行业维度与股票成分统一读取 `derived` 下的跨源黄金表。查询时必须区分“分类版本”（`classification=SW2021`）与“证据来源”（黄金表的 `src=TUSHARE` / `LIXINGER`），不能再从裸 `index_member` 或理杏仁快照的 `symbol` 字段猜版本。

---

## 1. 核心 Python API 极速速查 (SSOT)

所有下游策略、分析与报表**严禁直接遍历 Parquet 物理目录**，统一通过 [`DataCatalog`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/catalog/service.py) 纯读接口加载：

```python
from datetime import date
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

# 1. 实例化 DataCatalog (支持指定数据源或全库)
runtime = DataRuntimeContext.from_root("data")
cat_ts = DataCatalog(data_source="tushare", runtime=runtime)
cat_lx = DataCatalog(data_source="lixinger", runtime=runtime)
cat_derived = DataCatalog(data_source="derived", runtime=runtime)

# 2. 获取某数据集最新落盘交易日 (防时滞错位)
latest_date = cat_ts.get_latest_trade_date("stock_daily_bar")

# 3. 加载日 K 线行情 (自动处理年月分区裁剪与复权)
df_bars = cat_ts.load_bars(
    symbols=["600519.SH", "000001.SZ"],
    start_date=date(2026, 1, 1),
    end_date=latest_date,
    columns=["symbol", "trade_date", "close", "amount"]
)

# 4. 加载任意 Curated 黄金数据集 (估值/资金流/宏观/两融/行业)
df_basic = cat_ts.load_dataset(
    "daily_basic",
    start_date=date(2026, 8, 1),
    symbols=["600519.SH"]
)

# 5. 输出全库/单源资产大盘点
df_summary = DataCatalog().summary()
```

### 1.1 申万行业数据读取路由（SW2021）

| 查询目标 | 推荐 `data_source` | 推荐数据集/入口 | 必要口径 |
| :--- | :--- | :--- | :--- |
| 行业日行情、成交、行业 PE/PB | `tushare` | `cat_ts.load_dataset("sw_daily", ...)` | 只保留 `classification=SW2021`，再按 `industry_level` 选择 `L1`/`L2`/`L3`；不要把层级混算 |
| 行业维度、代码、名称、父子层级 | `derived` | `load_sw_2021_industry_dimension(...)` | 默认 `classification=SW2021`；按 `level` 筛选；`src` 是证据覆盖来源 |
| 当前或历史股票成分 | `derived` | `load_sw_2021_industry_members(...)` | 当前截面用 `current_only=True`；历史时点用 `as_of_date=...`；默认 `canonical_only=True` |
| 指定行业当前股票代码 | `derived` | `load_sw_2021_industry_symbols(...)` | `industry_code` 与 `level` 必须同时指定/确认；返回六位股票代码 |
| TuShare 内部的 SW2021 历史成分 | `tushare` | `load_index_member_for_classification(cat_ts, classification="SW2021")` | 优先读 `index_member_versioned`；它由 `index_member + index_classify` 派生 |
| 申万一级/二级估值序列 | `lixinger` | `sw_2021_fundamental` / `sw_2021_l2_fundamental` | `symbol` 是行业代码；按 `trade_date` 裁剪；当前没有把它当作成分表 |
| 理杏仁原始成分快照（仅血缘/回退） | `lixinger` | `sw_2021_constituents` | 原表 `industryCode` 是行业代码、`symbol` 是六位股票代码；不直接作为统一下游成分接口 |

推荐调用方式：

```python
from datetime import date

import polars as pl

from stock_data.catalog import DataCatalog, load_index_member_for_classification
from stock_data.core.runtime import DataRuntimeContext
from stock_data.catalog.sw_industry_golden import (
    load_sw_2021_industry_dimension,
    load_sw_2021_industry_members,
    load_sw_2021_industry_symbols,
)

runtime = DataRuntimeContext.from_root("data")
cat_ts = DataCatalog(data_source="tushare", runtime=runtime)
cat_derived = DataCatalog(data_source="derived", runtime=runtime)

# 行情：先做时间/列裁剪，再隔离 SW2021 与行业层级
df_sw_daily_l1 = cat_ts.load_dataset(
    "sw_daily",
    start_date=date(2026, 8, 1),
    end_date=date(2026, 8, 14),
    columns=(
        "symbol",
        "trade_date",
        "close",
        "amount",
        "classification",
        "industry_level",
        "industry_code",
    ),
).filter(
    (pl.col("classification") == "SW2021") & (pl.col("industry_level") == "L1")
)

# 维度：不依赖名称猜测，按层级读取
df_l2 = load_sw_2021_industry_dimension(
    cat_derived,
    level="L2",
    columns=("industry_code", "industry_name", "index_code", "level", "src"),
)

# 当前截面：只取 canonical 归属，避免同一股票在同一层级重复
df_members = load_sw_2021_industry_members(
    cat_derived,
    current_only=True,
    level="L2",
    canonical_only=True,
    columns=("symbol", "industry_code", "industry_name", "level", "src"),
)

# 历史时点：TuShare 有效期优先，理杏仁无日期快照不能伪装成历史
df_members_at_date = load_sw_2021_industry_members(
    cat_derived,
    as_of_date=date(2025, 12, 31),
    level="L2",
    src="TUSHARE",
    canonical_only=True,
    columns=("symbol", "industry_code", "level", "valid_from", "valid_to", "src"),
)

stock_codes = load_sw_2021_industry_symbols(cat_derived, "110100", level="L2")
df_ts_history = load_index_member_for_classification(
    cat_ts,
    classification="SW2021",
    columns=("src", "index_code", "con_code", "in_date", "out_date"),
)
```

黄金表的 `src` 取值含义如下：维度表可能是 `TUSHARE`、`LIXINGER` 或 `TUSHARE+LIXINGER`（后者表示两边均有该行业代码）；成员表的证据行是 `TUSHARE` 或 `LIXINGER`，用 `canonical_source`、`source_status`、`is_canonical` 和 `conflict_flag` 表示裁决结果。`canonical_only=False` 只用于审计两侧证据，不能直接拿来做下游聚合。

黄金表未物化时，先用 `cat_derived.list_datasets()` 检查；应通过 `make rebuild-sw-industry-golden` 先 dry-run，再按 `data-pipeline` 的人工确认规则执行 `APPLY=1`。如果发现旧文件仍是 `src=SW2021` 与 `evidence_source` 结构，说明物化结果落后于当前契约，应先重建，不能把旧 `src` 当作证据来源。

### 1.2 `industry/energy` 多级目录读取

`data/curated/industry/energy/` 是 `industry` 数据源下的业务子目录，不是独立的 `data_source`。目录结构类似：

```text
data/curated/industry/
├── semiconductor_sales.parquet
└── energy/
    ├── global_energy_macro_baseline.parquet
    ├── global_oil_gas_balance.parquet
    ├── global_power_generation.parquet
    ├── global_renewable_capacity.parquet
    └── energy_cross_source_audit.parquet
```

使用 `DataCatalog(data_source="industry")` 时，按以下规则寻址：

| 读取目标 | `load_dataset()` 参数 | 物理定位 | 说明 |
| :--- | :--- | :--- | :--- |
| energy 子目录中的单个逻辑数据集 | `"global_power_generation"` 等 | `energy/global_power_generation.parquet` | 通过 `StorageCompat` 自动映射；推荐用于分析 |
| energy 子目录全部文件聚合 | `"energy"` | `energy/*.parquet` | 仅用于有意进行跨表探索；异构列会按列并集合并，缺失列为 null |
| 未登记别名的多级数据集 | `"energy/new/deep_asset"` | `energy/new/deep_asset.parquet` | 未命中别名时直接按相对于 `data/curated/industry/` 的路径定位，不需要先加别名 |
| 显式子路径定位 | `"energy/global_power_generation"` | `energy/global_power_generation.parquet` | 受支持的精确定位写法；不要传入 `data/curated/...` 完整物理路径 |

推荐调用：

```python
from datetime import date

from stock_data.catalog import DataCatalog

cat_industry = DataCatalog(data_source="industry", runtime=runtime)

# 单表读取：使用逻辑数据集名，按需做时间和列裁剪
df_generation = cat_industry.load_dataset(
    "global_power_generation",
    start_date=date(2025, 1, 1),
    end_date=date(2026, 9, 4),
    columns=("geo_code", "trade_date", "technology", "generation_twh"),
)

# 聚合读取：只有在明确需要合并 energy 下多个异构表时使用
df_energy = cat_industry.load_dataset("energy", dedup=False)

# 没有别名时：直接传相对于 data/curated/industry/ 的安全相对路径
df_new = cat_industry.load_dataset(
    "energy/new/deep_asset",
    columns=("trade_date", "value"),
)
```

当前正式登记的 energy 短名别名只有：`global_energy_macro_baseline`、`global_oil_gas_balance`、`global_power_generation`、`global_renewable_capacity`、`energy_cross_source_audit`。未登记别名的数据集不需要修改别名表，直接使用相对于 `data/curated/industry/` 的安全路径即可；路径不能是绝对路径，也不能包含 `.` 或 `..` 越界片段。`list_datasets()` / `available_datasets()` 会将当前 energy 直系文件按物理父目录展示为一个逻辑数据集 `energy`，因此列表中看不到单个文件名不代表文件缺失。若要让新数据集进入采集、质量、去重和正式目录契约，仍需补充任务注册与测试。

运行时通过 `DataRuntimeContext` 统一注入 `data/raw`、`data/curated` 和 `data/cache`；下游读取 Curated 仍使用 `DataCatalog`。`market_daily`、Feature 长表与领域 Mart 不属于 DataCatalog 数据集目录，统一通过 `stock_analytics.features` 的 `FeatureStore` 读取，例如 `FeatureStore().get_domain_mart("repurchase_daily")`。

### 1.3 理杏仁行业财报与 Curated TTM 派生字段

理杏仁申万行业合并财报按层级和行业类型拆成 12 个数据集：
`sw_2021_fs_*`、`sw_2021_l2_fs_*`、`sw_2021_l3_fs_*`，其中 `*` 为
`non_financial`、`bank`、`security`、`insurance`。统一通过 `cat_lx.load_dataset()` 读取，
不要直接遍历 Parquet 物理目录。

财报 `q` 结构中的关键字段如下：

| 字段 | 含义 | 使用规则 |
| :--- | :--- | :--- |
| `q.ps.toi.t` | 营业总收入 YTD 累计值 | 用 `standardDate` 按季度排序后还原单季值 |
| `q.ps.np.t` | 净利润 YTD 累计值 | 同上；允许负值，不把负利润当缺失 |
| `q.ps.toi.ttm_y2y` / `q.ps.np.ttm_y2y` | 理杏仁官方 TTM 同比 | 官方值优先，不覆盖 |
| `q.ps.toi.ttm_y2y_derived` / `q.ps.np.ttm_y2y_derived` | Curated 派生 TTM 同比 | 仅补官方字段缺失且四季度数据足够的记录 |

TTM 派生口径为：Q1 单季=`t`，Q2/Q3/Q4 单季=`本期 t - 上一报告期 t`；
再对连续四个单季求和。同比使用已与理杏仁官方值对账的口径：

```text
ttm_y2y_derived = (本期 TTM - 上期 TTM) / abs(上期 TTM)
```

`standardDate` 是财务报告期末，应用于季度计算；`reportDate` 是披露日期，应用于
PIT/可用性对齐；不能用披露日期代替财务期末。`trade_date` 在这些 Curated 财报表中
对应报告期末，不能据此推断披露时点。缺少连续季度、基期 TTM 为零或累计值缺失时，
派生字段保持 null，不用单季同比平滑值冒充正式 TTM。

推荐读取和回退方式：

```python
import polars as pl

fs = cat_lx.load_dataset(
    "sw_2021_l3_fs_non_financial",
    columns=("symbol", "reportType", "reportDate", "standardDate", "trade_date", "q"),
)

toi = pl.col("q").struct.field("ps").struct.field("toi")
np_ = pl.col("q").struct.field("ps").struct.field("np")
facts = fs.select(
    "symbol",
    "reportDate",
    "standardDate",
    pl.coalesce(
        [toi.struct.field("ttm_y2y"), toi.struct.field("ttm_y2y_derived")]
    ).alias("revenue_ttm_yoy"),
    pl.coalesce(
        [np_.struct.field("ttm_y2y"), np_.struct.field("ttm_y2y_derived")]
    ).alias("profit_ttm_yoy"),
)
```

查询时如需检查补齐范围，分别统计官方字段 null 与派生字段非空；不要把仍为 null
的早期记录判定为采集失败，它们可能缺少完整的四季度历史。现有 Curated 表的派生
字段物化/重建使用：

```bash
make rebuild-lixinger-industry-financial-ttm          # dry-run，只读预览
make rebuild-lixinger-industry-financial-ttm APPLY=1  # 确认后原子写入
```

`APPLY=1` 会在每张表旁保留 `data.pre_ttm.bak.parquet`；RAW 保持源端原样，不增加
派生字段。新增财报增量通过 Curated 合并链自动补算。

---

## 2. 各领域核心数据集快速路由索引

| 投研业务领域 | 核心数据集 (`dataset`) | 推荐数据源 | 关键字段概览 |
| :--- | :--- | :--- | :--- |
| **A 股个股行情** | `stock_daily_bar`, `adj_factor` | `tushare` | `open`, `high`, `low`, `close`, `volume`, `amount(元)` |
| **A 股每日估值** | `daily_basic` | `tushare` | `pe_ttm`, `pb`, `ps_ttm`, `dv_ttm`, `total_mv(元)`, `turnover_rate` |
| **微观资金流向** | `moneyflow`, `moneyflow_hsgt` | `tushare` | `buy_elg_amount`, `buy_lg_amount`, `net_mf_amount` (均为元) |
| **指数基本面估值** | `index_fundamental`, `national_debt` | `lixinger` | `pe_ttm.mcw`, `pb.mcw`, `dyr.mcw`, `tcm_y10`(10年国债) |
| **申万行业行情** | `sw_daily` | `tushare` | `symbol`, `trade_date`, `classification`, `industry_level`, `industry_code`, `close`, `amount`；按 `SW2021 + L1/L2/L3` 筛选 |
| **申万行业维度/成分** | `sw_2021_industry_dimension_golden`, `sw_2021_industry_member_golden` | `derived` | 版本化维度、父子层级、历史有效期、当前快照、来源裁决与冲突标记 |
| **申万行业估值/财报** | `sw_2021_fundamental`, `sw_2021_l2_fundamental`, `sw_2021_fs_*`, `sw_2021_l2_fs_*`, `sw_2021_l3_fs_*` | `lixinger` | 一级/二级/三级行业估值与行业合并财报；财报 TTM 优先官方、缺失时使用 Curated 派生字段；不替代黄金成分表 |
| **垂直产业数据** | 顶层逻辑数据集及 `energy/<dataset>` 子目录数据集 | `industry` | 通过 `DataCatalog(data_source="industry")` 按逻辑名读取；`energy` 仅表示子目录聚合 |
| **卖方预测与业绩** | `report_rc`, `forecast`, `express` | `tushare` | 一致预期盈利预测 (`np`, `tp`)、业绩预告与快报 |
| **财务指标（个股）** | `fina_indicator` | `tushare` | **百分数原值**：`grossprofit_margin` / `netprofit_margin` / `roe` / `or_yoy` / `netprofit_yoy` / `debt_to_assets`（31.9 = 31.9%，展示直接用，转小数才 ÷100）；低基数同比（如净利 yoy>±1000%）按异常值处理，不作趋势强度 |
| **场内基金与 ETF** | `fund_daily`, `fund_adj`, `etf_share_size` | `tushare` | 63 只核心 ETF 全历史日线、复权因子(含分红)与份额规模 |
| **可转债与期权** | `cb_basic`, `cb_daily`, `opt_basic`, `opt_daily` | `tushare` | 可转债静态/日行情、期权合约静态/日行情 |
| **公司行为事件** | `stk_holdertrade`, `repurchase`, `block_trade`, `share_float` | `tushare` | 增减持、回购、大宗交易与限售解禁事件明细 |
| **领域 Mart** | `market_daily`、`industry_daily`、`industry_panel_daily`、`market_temperature_derived_facts`、`convertible_bond_daily`、`insider_activity_daily`、`repurchase_daily`、`block_trade_daily`、`unlock_pressure_daily`、`settlement_iv_proxy_daily`、`overseas_revenue` | `FeatureStore` | 市场、行业、温度、衍生品、公司行为与海外营收布局聚合事实；不通过 `DataCatalog` 直接加载 |
| **外盘与全球宏观** | `stock_daily_bar`, `index_daily_bar`, `macro_indicators` | `yfinance` / `fred` | 美股巨头、外盘指数、美债/黄金/原油/VIX、FED 宏观序列 |

---

## 3. 核心调用黄金法则 (Golden Rules)

1. **零臆造与缺失如实说明 (Ground Truth First)**：
   严禁凭大模型记忆输出历史估值、点位或点数；必须先运行 Python 代码读取本地 Curated 黄金表。**若本地查不到数据，必须如实说明数据缺失，严禁凭空编造；确需补充外部数据时，必须通过权威途径检索并显式注明来源与时效**。
2. **严禁编造指标与策略公式 (Authoritative Definitions)**：
   **严禁胡乱臆造量化指标定义、计算公式或交易策略**。若对指标公式（如布林带、ATR、ERP、分位数、上修比例）或策略因果机制不确定，必须检索外部权威金融文献、交易所/指数公司官方编制方案或券商金工研报，明确其数学定义与金融依据。
3. **金额单位统一为元**：
   Curated 层资金与市值已归一化为**元**。分析层代码严禁根据数据源额外 `* 10000` 或 `* 1_000_000`（展示为亿元时直接除以 `1e8`）。
4. **时滞感知与安全对齐**：
   不同数据集入库时间不同（日 K 线 17:00、估值 18:00、外盘次日 06:00）。多表 Join 前，必须通过 `cat.get_latest_trade_date()` 取交集基准日。
5. **禁止通配符读取**：
   禁止手写 `moneyflow*` 或 `margin*` 通配符遍历目录，必须使用 `DataCatalog.load_dataset()` 精确加载。
6. **申万版本与来源必须显式筛选**：
   * `index_classify` / `index_member_versioned` 中的 `src` 表示分类版本，申万 2021 使用 `src="SW2021"`；
   * 黄金维度/成员表中 `classification` 表示分类版本，`src` 表示证据来源；成员查询默认使用 `canonical_only=True`，并明确 `level`；
   * 需要历史成员时使用 `as_of_date` 或 `load_index_member_for_classification`，不能把无日期的 `sw_2021_constituents` 快照回填成历史；
   * 成分股票与行业行情/资金流联接前，确认代码格式（黄金成员是六位代码，TuShare 行情通常带交易所后缀），不要直接假定字符串可等值连接。
7. **性能与内存裁剪（按需加载）**：
   调用 `load_bars` 或 `load_dataset` 时，**必须优先指定 `start_date`、`end_date`、`symbols` 与 `columns`**，利用 Hive 年月物理分区裁剪与 Polars 列投影，避免无过滤加载全历史全市场数千万行数据造成内存溢出或 CPU 假死。
8. **临时脚本与衍生数据隔离 (Scratch Cleanliness)**：
   为回答用户问题编写的一次性分析脚本、测试排查代码或生成的临时中间结果（`.py`, `.csv`, `.parquet`），**严禁直接写在项目源码区（`src/`）或数据核心区（`data/`）**；必须统一输出至临时目录（如 scratch 目录），用完及时清理，保持 Git 工作区干净。
9. **大表跨表聚合优先与引擎选型 (Rollup First & Tool Selection)**：
   * **聚合表优先**：分析大盘估值、行业轮动或宏观时钟时，**优先消费现成的上层聚合表**（如行业估值 `sw_2021_fundamental`、指数估值 `index_fundamental`、北向资金 `moneyflow_hsgt`、两融大盘 `margin`），避免无谓拿千万级底层个股明细表（`stock_daily_bar` / `moneyflow`）进行沉重扫表；
   * **合适工具下推**：海量数据跨表关联或复杂 Group By 聚合时，选用合适工具（内存轻量分析用 **Polars Lazy/DataFrame**；复杂跨多分区大表关联可用 **DuckDB 向量化 SQL**），最大化节省计算资源与响应时间。
10. **百分数刻度与原值约定 (Percent Scale)**：
    * `fina_indicator` 等财务指标字段为 **百分数原值**（31.9 = 31.9%），展示百分数直接用原值，只有需要小数（如回归/相乘）才 ÷100——禁止再 ×100；
    * customs 分析面板（`customs_l2_volume_price_monthly` / `customs_product_volume_price` / 观察表 / H8 信号）的 `*_yoy_3mma` / `yoy_growth_3mma` 为**小数**（1.0 = +100%），与财务指标刻度相反，两生态拼装前必须统一口径；
    * 读表怀疑刻度时，用已知合理量级反校（如行业毛利中位约 20-40%、ROE 中位约 5-15%），不要凭感觉 ×100 或 ÷100。

---

## 4. 专题进阶手册 (Deep-Dive References)

* 📘 [01_全库 40+ 黄金数据集完整数据字典](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/01_datasets_directory.md)：详细字段表、主键组合、覆盖时间跨度与数据源划分。
* 📘 [02_高频量化投研分析实战范例](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/02_investigative_recipes.md)：申万二级行业主力资金聚合、沪深300估值分位数、分析师预期上修比例等 Polars 高性能代码模板。
* 📘 [03_数据资产查询细节与避坑参考](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/03_data_query_caveats.md)：更新时钟与时滞矩阵、微观单笔资金流分级、股债利差 (ERP) 计算公式与防过拟合自检。
