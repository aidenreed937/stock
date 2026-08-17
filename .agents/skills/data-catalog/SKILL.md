---
name: data-catalog
description: 本地落盘数据资产统一目录 (DataCatalog) 与极速查询技能。用于一键查看全库/单源各数据集最新落盘时间、数据覆盖率、缺口诊断、单表加载及 Python API 规范调用。
---

# 数据资产目录服务 (DataCatalog) 技能指南

本技能为量化投研系统提供统一的**本地落盘数据资产盘点、最新水位嗅探、数据加载与缺口诊断**的标准操作指南。通过 `DataCatalog` 统一入口屏蔽底层物理存储细节，支持 Hive 年月分区自动裁剪、时区容错、主键去重及 OHLC 有效性校验。

---

## 1. 全库黄金数据集资产速查表 (Datasets Inventory)

| 数据源 (`data_source`) | 核心数据集 (`dataset`) | 业务含义 | 标的粒度 / 典型覆盖 | 关键字段 |
| :--- | :--- | :--- | :--- | :--- |
| **`tushare`** | `stock_daily_bar` | A 股全市场个股日 K 线 | 5,000+ A 股 (2013 至今) | `open`, `high`, `low`, `close`, `volume`, `amount(元)` |
| **`tushare`** | `daily_basic` | A 股每日指标与估值 | 5,000+ A 股 (2013 至今) | `pe_ttm`, `pb`, `ps_ttm`, `dv_ttm`, `total_mv(万)`, `circ_mv` |
| **`tushare`** | `sw_daily` | 申万行业日线行情 | 439 个行业代码 (31个L1+L2/L3) | `open`, `high`, `low`, `close`, `amount(元)`, `pe`, `pb` |
| **`tushare`** | `index_classify` | 申万行业代码分类体系 | 一/二/三级行业分类 (SW2014) | `index_code`, `industry_name`, `level`, `industry_code` |
| **`tushare`** | `index_member` | 申万行业/指数成份股映射 | 历史各期纳入/剔除记录 | `index_code`, `con_code`, `in_date`, `out_date` |
| **`tushare`** | `adj_factor` | A 股复权因子 | 5,000+ A 股全历史 | `symbol`, `trade_date`, `adj_factor` |
| **`tushare`** | `fund_daily` | 场内基金与 ETF 日 K 线 | 26 只核心观察池 ETF 等 | `open`, `high`, `low`, `close`, `volume`, `amount` |
| **`tushare`** | `etf_share_size` | ETF 份额与规模序列 | 核心 ETF 全历史 | `symbol`, `trade_date`, `fd_share`, `n_shares` |
| **`tushare`** | `moneyflow` | 个股大单小单资金流向 | 全市场个股资金流 | `buy_sm_amount`, `buy_md_amount`, `buy_lg_amount`, `buy_elg_amount` |
| **`tushare`** | `report_rc` | 卖方机构盈利预测明细 (一致预期) | 全市场 4,390 股 (2020 至今 20.6 万行) | `quarter`, `np(万元)`, `eps`, `tp(目标价)`, `rating`, `org_name` |
| **`tushare`** | `forecast` | 上市公司业绩预告 (PIT) | 全市场 4,712 股 (2020 至今 1.5 万行) | `type`, `p_change_min`, `p_change_max`, `net_profit_min`, `summary` |
| **`tushare`** | `express` | 上市公司业绩快报 (PIT) | 全市场 1,810 股 (2022 至今 4.3 千行) | `revenue`, `operate_profit`, `n_income`, `yoy_net_profit`, `diluted_roe` |
| **`lixinger`** | `sw_2021_fs_non_financial` | 申万 29 非金融行业合并财报 | 29 个非金融行业 (2020 至今 705 行) | `ps.toi.c_y2y`, `ps.np.c_y2y`, `ps.gp_m.ttm`, `m.roe.ttm` |
| **`lixinger`** | `sw_2021_fs_bank` | 申万银行行业合并财报 | 商业银行 (2020 至今 63 行) | `ps.nii.c_y2y`, `ps.np.c_y2y`, `ps.cir.ttm`, `m.roe.ttm` |
| **`lixinger`** | `sw_2021_fs_security` | 申万证券行业合并财报 | 证券公司 (2020 至今 25 行) | `ps.ib_n_inc.c_y2y`, `ps.np.c_y2y`, `m.roe.ttm` |
| **`lixinger`** | `sw_2021_fs_insurance` | 申万保险行业合并财报 | 保险公司 (2020 至今 25 行) | `ps.ep.c_y2y`, `ps.np.c_y2y`, `m.roe.ttm` |
| **`lixinger`** | `sw_2021_constituents` | 申万 2021 行业成份股图谱 | 797 个行业全量挂载关系 | `symbol(行业代码)`, `constituents(成份股数组)` |
| **`lixinger`** | `sw_2021_l2_fundamental` | 申万 2021 二级行业估值 | 162 个二级行业 12 年连续日度 | `pe_ttm.ew`, `pb.ew`, `ps_ttm.ew`, `dyr.ew`, `mc(元)` |
| **`lixinger`** | `sw_2021_fundamental` | 申万 2021 一级行业估值 | 31 个一级行业 12 年连续日度 | `pe_ttm.ew`, `pb.ew`, `ps_ttm.ew`, `dyr.ew`, `mc(元)` |
| **`lixinger`** | `index_fundamental` | 9 大核心指数基本面估值 | 沪深300/中证500/上证50等 | `pe_ttm.mcw`, `pb.mcw`, `dyr.mcw`, `mc` |
| **`yfinance`** | `stock_daily_bar` | 美股科技巨头日 K 线 | AAPL, MSFT, NVDA, GOOGL 等 | `open`, `high`, `low`, `close`, `volume` |
| **`yfinance`** | `index_daily_bar` | 外盘核心指数日 K 线 | 标普500, 纳指100, 罗素2000 等 | `open`, `high`, `low`, `close`, `volume` |
| **`yfinance`** | `macro_indicators` | 全球宏观资产行情 | 黄金、美原油、美元指数、美债等 | `symbol`, `trade_date`, `close`, `volume` |
| **`fred`** | `macro_indicators` | 美联储官方核心宏观指标 | 基准利率、CPI、非农、失业率、利差 | `symbol`, `trade_date`, `value` |

---

## 2. 核心 Python API 速查 (标准调用规范)

`DataCatalog` 提供单例化、类型安全、容错的查询接口，避免直接手写 Parquet 遍历。

### ① 一键输出全库/单源资产看板 (`summary`)
```python
from stock_data.catalog import DataCatalog

catalog = DataCatalog()

# 查看全库所有数据源 (TuShare / LiXinger / YFinance / FRED) 完整看板
df_all = catalog.summary()
print(df_all)

# 查看指定数据源资产清单
df_ts = catalog.summary(data_source="tushare")
print(df_ts)
```

### ② 毫秒级查询数据集最新落盘日期 (`get_latest_trade_date`)
内置任务别名自动解析（如传入 `"daily"` 自动映射到 `"stock_daily_bar"`）：

```python
from stock_data.catalog import DataCatalog

catalog = DataCatalog()

# A 股全市场日 K 最新日期
latest_bar = catalog.get_latest_trade_date("stock_daily_bar", data_source="tushare")
# -> date(2026, 8, 14)

# 申万二级行业估值最新日期
latest_sw = catalog.get_latest_trade_date("sw_2021_l2_fundamental", data_source="lixinger")
# -> date(2026, 8, 14)

# 美股巨头行情最新日期
latest_us = catalog.get_latest_trade_date("stock_daily_bar", data_source="yfinance")
# -> date(2026, 8, 14)
```

### ③ 安全加载日 K 线黄金表 (`load_bars`)
自带主键去重、时钟对齐、别名归一与 OHLC 物理有效性校验：

```python
from datetime import date
from stock_data.catalog import DataCatalog

catalog = DataCatalog(data_source="tushare")

# 加载指定标的区间日 K 线 (自动 Hive 年月分区裁剪)
df_bars = catalog.load_bars(
    symbols=["600519.SH", "000858.SZ"],
    start_date=date(2026, 1, 1),
    end_date=date(2026, 8, 14),
    adjustment="raw",
)
```

### ④ 加载通用/基本面/估值数据集 (`load_dataset`)
支持按标的列表和起止交易日快速过滤：

```python
from datetime import date
from stock_data.catalog import DataCatalog

# 加载 A 股个股每日基本面估值表
catalog_ts = DataCatalog(data_source="tushare")
df_basic = catalog_ts.load_dataset(
    "daily_basic",
    start_date=date(2026, 8, 1),
    end_date=date(2026, 8, 14),
    symbols=["600519.SH"],
)

# 加载理杏仁申万二级行业全历史估值
catalog_lx = DataCatalog(data_source="lixinger")
df_sw_val = catalog_lx.load_dataset("sw_2021_l2_fundamental")
```

---

## 3. 常见投研分析场景实战范例 (Investigative Recipes)

### 范例 1：申万二级行业最近成交额 Top 5 及估值水平分析
```python
from datetime import date
import polars as pl
from stock.data.catalog import DataCatalog

cat_lx = DataCatalog(data_source="lixinger")
cat_ts = DataCatalog(data_source="tushare")

# 1. 读取申万 2021 成份股图谱并提取二级行业
df_sc = cat_lx.load_dataset("sw_2021_constituents")
symbols = df_sc["symbol"].to_list()
l2_codes = [s for s in symbols if s.endswith("00") and not s.endswith("0000")]
df_l2_sc = df_sc.filter((pl.col("symbol").is_in(l2_codes)) & (pl.col("constituents").list.len() > 0))

# 展平行业与成份股代码
flat_map = []
for row in df_l2_sc.to_dicts():
    ind_code = row["symbol"]
    for c in row["constituents"]:
        flat_map.append({"industry_code": ind_code, "stock_code": c["stockCode"]})
df_con = pl.DataFrame(flat_map)

# 2. 读取最近一个月 (如最近 24 个交易日) 个股日 K 线成交额
df_bars = cat_ts.load_bars(
    start_date=date(2026, 7, 14),
    end_date=date(2026, 8, 14)
).select(["symbol", "trade_date", "amount"])

df_bars = df_bars.with_columns(pl.col("symbol").str.slice(0, 6).alias("stock_code"))

# 3. 聚合计算行业成交额 (元 -> 亿元)
df_turnover = df_bars.join(df_con, on="stock_code", how="inner").group_by("industry_code").agg([
    (pl.col("amount").sum() / 1e8).alias("total_amount_yi"),
    pl.col("stock_code").n_unique().alias("stock_count")
]).sort("total_amount_yi", descending=True)

# 4. 关联理杏仁二级行业估值与 12 年历史分位数
df_l2_val = cat_lx.load_dataset("sw_2021_l2_fundamental")
latest_val_date = df_l2_val["trade_date"].max()
# 计算当前行业最新 PE-TTM、PB 及其在 2014~2026 间的历史分位点
```

### 范例 2：指数基本面估值与历史水位追踪
```python
from stock.data.catalog import DataCatalog
import polars as pl

cat = DataCatalog(data_source="lixinger")
df_idx = cat.load_dataset("index_fundamental")

# 筛选沪深300 (000300) 最新估值及历史分位数
hs300 = df_idx.filter(pl.col("symbol") == "000300").sort("trade_date")
latest = hs300.tail(1).to_dicts()[0]

pe = latest["pe_ttm.mcw"]
pe_pct = (hs300.filter(pl.col("pe_ttm.mcw") > 0)["pe_ttm.mcw"] < pe).mean() * 100
print(f"沪深300 最新 PE-TTM: {pe:.2f}, 历史分位数: {pe_pct:.1f}%")
```

### 范例 3：全库数据健康度与最新落盘交易日快速对齐
```python
from stock.data.catalog import DataCatalog
import polars as pl

cat = DataCatalog()
summary_df = cat.summary()

# 筛选最新日期落后的数据集
lagging = summary_df.filter(
    (pl.col("latest_date") != "N/A") & (pl.col("latest_date") < "2026-08-13")
)
print("需关注的滞后数据集:")
print(lagging)
```

### 范例 4：申万 31 行业分析师盈利预测上修比例 (Revision Ratio)
```python
from datetime import date
from stock.data.catalog import DataCatalog
import polars as pl

cat_ts = DataCatalog(data_source="tushare")

# 1. 加载 2026 年全市场券商研报预测明细
df_rc = cat_ts.load_dataset("report_rc", start_date=date(2026, 1, 1))

# 2. 加载申万行业成分股关系并过滤出最新在册成分
df_mem = cat_ts.load_dataset("index_member").filter(
    (pl.col("in_date") <= "20260814") & ((pl.col("out_date").is_null()) | (pl.col("out_date") > "20260814"))
)

# 3. 关联行业成分计算各申万一级行业研报覆盖度与平均目标价空间
df_sector_rc = df_rc.join(df_mem, left_on="symbol", right_on="con_code", how="inner").group_by("index_code").agg([
    pl.col("symbol").n_unique().alias("covered_stocks"),
    pl.col("tp").mean().alias("avg_target_price"),
    pl.col("np").mean().alias("avg_predicted_np_wan"),
    pl.count().alias("report_count"),
]).sort("report_count", descending=True)
print(df_sector_rc.head(10))
```

---

## 4. 规范与避坑指南 (Contracts & Pitfalls)

1. **金额单位口径统一为元 (CNY)**：
   * `stock_daily_bar`、`sw_daily` 中的 `amount` 经过 Curated 黄金层清洗后统一为**元 (CNY)**，换算为亿元直接除以 `1e8`。
   * `daily_basic` 中的 `total_mv` 和 `circ_mv` 经过 Curated 黄金层清洗后统一为**元 (CNY)**。
2. **Polars 聚合多列重名冲突防范**：
   * 在使用 Polars 执行 `select([pl.col("date").min(), pl.col("date").max()])` 时，新版 Polars 会因投影重名触发 `DuplicateError`。
   * **正确写法**：必须使用显式别名：
     ```python
     df.select([
         pl.col("trade_date").min().alias("min_date"),
         pl.col("trade_date").max().alias("max_date"),
     ])
     ```
3. **Hive 年月分区自动裁剪**：
   * 在调用 `load_daily_bars` 或 `load_dataset` 时，**强烈建议传入 `start_date` 和 `end_date`**。
   * `DataCatalog` 底层会自动拦截无交集的 `year=YYYY/month=MM` 目录，只读取目标月份 Parquet 文件，提升查询速度 10~50 倍。
4. **标的代码规范 (Symbol Conventions)**：
   * A 股个股：`000001.SZ`, `600519.SH`, `688001.SH`
   * 申万行业：`801xxx.SI`（Tushare 申万指数）或 6 位纯数字 `270100`（申万 2021 二级行业分类）
   * 外盘指数：`^GSPC` (标普500), `^IXIC` (纳斯达克), `^DJI` (道琼斯)
   * 宏观指标：`CPIAUCSL`, `fedfunds`, `t10y2y`, `gdp`

---

## 5. 终端 CLI 运维与数据审计指令

```bash
# 1. 全库 Parquet 物理主审计盘点 (包含行数、标的数、起止时间与文件健康度)
make master-audit

# 2. 估值指标专项对账审计 (daily_basic 与 index_fundamental 对齐率)
make audit TYPE=valuation

# 3. 因子专项对账审计 (复权因子与申万行业行情覆盖率)
make audit TYPE=factor

# 4. RAW vs Curated 双向物理对账 (确保清洗过程零丢行)
make audit TYPE=reconciliation

# 5. 发现数据缺口时快速自动补齐
make sync SOURCE=tushare
make backfill START=2014-08-01 END=2026-08-14 SOURCE=lixinger ENDPOINT=sw_2021_l2_fundamental
```

---

## 6. 进阶参考文档 (References)

* [数据资产查询细节、时滞处理与避坑参考](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/data_query_caveats.md)：涵盖资金流向微观穿透 (`moneyflow`)、股债利差时钟 (ERP)、通配符隔离防错、Schema 历史类型容错以及数据集入库时滞对齐矩阵。
