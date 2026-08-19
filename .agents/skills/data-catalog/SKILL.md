---
name: data-catalog
description: 本地落盘数据资产统一目录 (DataCatalog) 与极速查询技能。用于一键查看全库/单源各数据集最新落盘时间、数据覆盖率、缺口诊断、单表加载及 Python API 规范调用。
---

# 数据资产目录服务 (DataCatalog) 技能指南

本技能为量化投研系统提供统一的**本地落盘黄金数据资产盘点、最新水位嗅探、数据加载与缺口诊断**的标准操作指南。

遵循**渐进式披露**原则，本入口聚合高频 Python 查询 API 与数据集快速路由索引；深入数据字典、分析范例与时滞避坑请查阅对应专题。

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

运行时通过 `DataRuntimeContext` 统一注入 `data/raw`、`data/curated` 和 `data/cache`；下游读取 Curated 仍使用 `DataCatalog`。`market_daily` 与领域 Mart 不属于 DataCatalog 数据集目录，统一通过 `FeatureStore` 读取，例如 `FeatureStore().get_domain_mart("repurchase_daily")`。

---

## 2. 各领域核心数据集快速路由索引

| 投研业务领域 | 核心数据集 (`dataset`) | 推荐数据源 | 关键字段概览 |
| :--- | :--- | :--- | :--- |
| **A 股个股行情** | `stock_daily_bar`, `adj_factor` | `tushare` | `open`, `high`, `low`, `close`, `volume`, `amount(元)` |
| **A 股每日估值** | `daily_basic` | `tushare` | `pe_ttm`, `pb`, `ps_ttm`, `dv_ttm`, `total_mv(元)`, `turnover_rate` |
| **微观资金流向** | `moneyflow`, `moneyflow_hsgt` | `tushare` | `buy_elg_amount`, `buy_lg_amount`, `net_mf_amount` (均为元) |
| **指数基本面估值** | `index_fundamental`, `national_debt` | `lixinger` | `pe_ttm.mcw`, `pb.mcw`, `dyr.mcw`, `tcm_y10`(10年国债) |
| **申万行业体系** | `sw_daily`, `sw_2021_fundamental`, `sw_2021_constituents` | `tushare` / `lixinger` | 31 行业行情、估值序列与 797 行业成份股图谱 |
| **卖方预测与业绩** | `report_rc`, `forecast`, `express` | `tushare` | 一致预期盈利预测 (`np`, `tp`)、业绩预告与快报 |
| **场内基金与 ETF** | `fund_daily`, `etf_share_size` | `tushare` | 26 只核心自选 ETF 历史日线与份额规模 |
| **可转债与期权** | `cb_basic`, `cb_daily`, `opt_basic`, `opt_daily` | `tushare` | 可转债静态/日行情、期权合约静态/日行情 |
| **公司行为事件** | `stk_holdertrade`, `repurchase`, `block_trade` | `tushare` | 增减持、回购与大宗交易事件明细 |
| **领域 Mart** | `market_daily`、`convertible_bond_daily`、`insider_activity_daily`、`repurchase_daily`、`block_trade_daily`、`settlement_iv_proxy_daily` | `FeatureStore` | 聚合事实与观察项；不通过 `DataCatalog` 直接加载 |
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
6. **性能与内存裁剪（按需加载）**：
   调用 `load_bars` 或 `load_dataset` 时，**必须优先指定 `start_date`、`end_date`、`symbols` 与 `columns`**，利用 Hive 年月物理分区裁剪与 Polars 列投影，避免无过滤加载全历史全市场数千万行数据造成内存溢出或 CPU 假死。
7. **临时脚本与衍生数据隔离 (Scratch Cleanliness)**：
   为回答用户问题编写的一次性分析脚本、测试排查代码或生成的临时中间结果（`.py`, `.csv`, `.parquet`），**严禁直接写在项目源码区（`src/`）或数据核心区（`data/`）**；必须统一输出至临时目录（如 scratch 目录），用完及时清理，保持 Git 工作区干净。
8. **大表跨表聚合优先与引擎选型 (Rollup First & Tool Selection)**：
   * **聚合表优先**：分析大盘估值、行业轮动或宏观时钟时，**优先消费现成的上层聚合表**（如行业估值 `sw_2021_fundamental`、指数估值 `index_fundamental`、北向资金 `moneyflow_hsgt`、两融大盘 `margin`），避免无谓拿千万级底层个股明细表（`stock_daily_bar` / `moneyflow`）进行沉重扫表；
   * **合适工具下推**：海量数据跨表关联或复杂 Group By 聚合时，选用合适工具（内存轻量分析用 **Polars Lazy/DataFrame**；复杂跨多分区大表关联可用 **DuckDB 向量化 SQL**），最大化节省计算资源与响应时间。

---

## 4. 专题进阶手册 (Deep-Dive References)

* 📘 [01_全库 40+ 黄金数据集完整数据字典](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/01_datasets_directory.md)：详细字段表、主键组合、覆盖时间跨度与数据源划分。
* 📘 [02_高频量化投研分析实战范例](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/02_investigative_recipes.md)：申万二级行业主力资金聚合、沪深300估值分位数、分析师预期上修比例等 Polars 高性能代码模板。
* 📘 [03_数据资产查询细节与避坑参考](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/03_data_query_caveats.md)：更新时钟与时滞矩阵、微观单笔资金流分级、股债利差 (ERP) 计算公式与防过拟合自检。
