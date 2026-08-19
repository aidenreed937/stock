# 高频量化投研分析实战范例 (Investigative Recipes)

本手册汇总了使用 `DataCatalog` 进行跨表 Join、行业聚合、估值分位数与资金流微观穿透的高性能 Polars 实战代码模板。

---

## 范例 1：申万二级行业近 5 日主力资金净流入与估值强弱排序

```python
from datetime import date
import polars as pl
from stock_data.catalog import DataCatalog

cat_lx = DataCatalog(data_source="lixinger")
cat_ts = DataCatalog(data_source="tushare")

# 1. 加载申万 2021 行业成份股图谱与二级行业估值
df_map = cat_lx.load_dataset("sw_2021_constituents")
df_val = cat_lx.load_dataset("sw_2021_l2_fundamental", start_date=date(2026, 8, 1))

# 2. 加载近 5 日全市场微观个股资金流
df_mf = cat_ts.load_dataset("moneyflow", start_date=date(2026, 8, 8))

# 3. 展开成份股并按二级行业聚合主力资金净流入 (超大单 + 大单)
df_exploded = df_map.explode("constituents").rename(
    {"symbol": "industry_code", "constituents": "stock_symbol"}
)

df_joined = df_mf.join(
    df_exploded, left_on="symbol", right_on="stock_symbol", how="inner"
)

df_rank = (
    df_joined.group_by("industry_code")
    .agg(
        [
            (pl.col("buy_elg_amount") + pl.col("buy_lg_amount")).sum().alias("main_inflow_yuan"),
            (pl.col("sell_elg_amount") + pl.col("sell_lg_amount")).sum().alias("main_outflow_yuan"),
            pl.col("net_mf_amount").sum().alias("net_inflow_yuan"),
        ]
    )
    .sort("net_inflow_yuan", descending=True)
)

print("=== 申万二级行业主力资金净流入 Top 5 (亿元) ===")
print(df_rank.head(5).with_columns((pl.col("net_inflow_yuan") / 1e8).round(2)))
```

---

## 范例 2：沪深 300 指数基本面估值与 10 年历史水位分位数

```python
from stock_data.catalog import DataCatalog
import polars as pl

cat = DataCatalog(data_source="lixinger")
df_idx = cat.load_dataset("index_fundamental", symbols=["000300"])

# 计算 PE-TTM 的 10 年滚动分位数 (Percentile)
df_pe = (
    df_idx.sort("trade_date")
    .select(
        [
            pl.col("trade_date"),
            pl.col("pe_ttm.mcw").alias("pe_ttm"),
            pl.col("pb.mcw").alias("pb"),
            pl.col("dyr.mcw").alias("dividend_yield"),
            (
                (pl.col("pe_ttm.mcw").rank() - 1) / (pl.col("pe_ttm.mcw").count() - 1) * 100
            ).alias("pe_percentile_10y"),
        ]
    )
    .tail(1)
)

print("=== 沪深 300 最新估值与 10 年历史水位 ===")
print(df_pe)
```

---

## 范例 3：跨数据源交易日动态对齐与时滞防御

```python
from stock_data.catalog import DataCatalog
import polars as pl

cat = DataCatalog()

# 获取 TuShare 日 K 与 理杏仁估值分别就绪的最新交易日
latest_bar_date = cat.get_latest_trade_date("stock_daily_bar", data_source="tushare")
latest_val_date = cat.get_latest_trade_date("index_fundamental", data_source="lixinger")

# 取两者的安全交集日期进行对齐 Join，避免因时滞导致空值
safe_trade_date = min(latest_bar_date, latest_val_date)
print(f"安全对齐分析基准日: {safe_trade_date}")
```

---

## 范例 4：申万 31 行业分析师一致预期上修比例 (Revision Ratio)

```python
from datetime import date
from stock_data.catalog import DataCatalog
import polars as pl

cat_ts = DataCatalog(data_source="tushare")
# 加载最近 30 天卖方机构最新盈利预测
df_rc = cat_ts.load_dataset("report_rc", start_date=date(2026, 7, 1))

# 按个股与机构分组计算目标价与净利润调整方向
df_revision = (
    df_rc.group_by("symbol")
    .agg(
        [
            pl.len().alias("forecast_count"),
            pl.col("np").mean().alias("avg_forecast_np"),
        ]
    )
    .sort("forecast_count", descending=True)
)

print("=== 近期分析师关注度与预期盈利最高的标的 Top 5 ===")
print(df_revision.head(5))
```
