"""三层共振补充测试：全球景气方向 × 量价齐升 对未来 60 日收益的共振效应。

背景：单因子测试显示 direction_score（SOX/半导体景气方向分）与科技行业未来 60 日收益
显著负相关（追高反向）。本脚本验证三层共振框架的「供需层」能否改变这一结论：
- 若「方向高 × 量价齐升」象限收益显著为正 / 优于「方向高 × 非量价齐升」，
  则量价齐升筛选对方向层有增量（共振有效）；
- 若共振象限仍差，则方向层作为进攻因子整体证伪，应转为防守/预警语义。

口径：
- direction：SOX 相对 200 日均线偏离 + 20/60 日动量 + 半导体 YoY 的合成滚动分位（0-100）；
- direction_high / low：滚动分位 > 66 / < 33；
- 量价齐升：revenue_growth_ttm > 0 且 profit_growth_ttm > 0（供需层质量门）；
- 目标：电子(801080.SI)/通信(801770.SI)/计算机(801750.SI) 未来 60 日收益。
"""

from __future__ import annotations

import polars as pl

from stock_data.catalog.service import DataCatalog


def _rolling_pct(series: pl.Series, window: int = 756) -> pl.Series:
    """滚动历史分位 (0-100)：每个时点在过去 window 天内的分位。"""
    return (
        series.to_frame("v")
        .select(
            pl.col("v").rolling_map(
                lambda x: float((x <= x[-1]).mean()) * 100.0, window_size=window
            )
        )["v"]
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def main() -> None:
    cat = DataCatalog(data_source="industry")
    tech = ["801080.SI", "801770.SI", "801750.SI"]

    # 1. 方向层（跨行业同值，日频）: 融合美股定价 (SOX) 与 全球需求总量 (SIA Global Sales)
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date", "sox_close"])
        .drop_nulls()
        .sort("trade_date")
    )
    semi_sales = (
        cat.load_dataset("semiconductor_sales")
        .select(["release_date", "global_sales_usd", "yoy_growth", "china_yoy_growth"])
        .sort("release_date")
    )
    # 按 release_date 防未来函数广播至日频交易日
    gm_semi = gm.join_asof(
        semi_sales,
        left_on="trade_date",
        right_on="release_date",
        strategy="backward",
    )
    sox = gm_semi.with_columns(
        pl.col("sox_close").rolling_mean(window_size=200).alias("ma200"),
        pl.col("sox_close").log().diff(20).alias("mom20"),
        pl.col("sox_close").log().diff(60).alias("chg60"),
    ).with_columns(((pl.col("sox_close") / pl.col("ma200") - 1.0) * 100.0).alias("ma_bias"))
    direction = (
        sox.with_columns(
            _rolling_pct(sox["ma_bias"].cast(pl.Float64)).alias("d1"),
            _rolling_pct(sox["mom20"].cast(pl.Float64)).alias("d2"),
            _rolling_pct(sox["chg60"].cast(pl.Float64)).alias("d3"),
            _rolling_pct(sox["yoy_growth"].cast(pl.Float64)).alias("d4"),
        )
        .select(["trade_date", "d1", "d2", "d3", "d4"])
        .with_columns(pl.mean_horizontal(["d1", "d2", "d3", "d4"]).alias("direction"))
        .select(["trade_date", "direction"])
    )

    # 2. 供需层（量价齐升，行业×日频）与行业未来 60 日收益
    panel = (
        pl.read_parquet("data/curated/mart/industry_panel_daily.parquet")
        .filter(pl.col("industry_code").is_in(tech))
        .select(["as_of_date", "industry_code", "revenue_growth_ttm", "profit_growth_ttm"])
        .rename({"as_of_date": "trade_date"})
    )
    ind = (
        pl.read_parquet("data/curated/mart/industry_daily.parquet")
        .filter(pl.col("industry_code").is_in(tech))
        .select(["trade_date", "industry_code", "close"])
        .sort(["trade_date", "industry_code"])
    )
    ind_wide = ind.pivot(on="industry_code", index="trade_date", values="close").sort("trade_date")
    fwd = ind_wide.with_columns(
        [
            (pl.col(c).shift(-60) / pl.col(c) - 1.0).alias(f"fwd_{c}")
            for c in tech
            if c in ind_wide.columns
        ]
    ).select(["trade_date"] + [f"fwd_{c}" for c in tech if c in ind_wide.columns])
    # 长表化：行业 × 日期 × 未来收益
    fwd_long = (
        fwd.unpivot(index="trade_date", on=[f"fwd_{c}" for c in tech], variable_name="_v")
        .with_columns(
            (pl.col("_v").str.extract(r"fwd_(\d+)\.SI", 1) + ".SI").alias("industry_code"),
            pl.col("value").alias("fwd60"),
        )
        .drop_nulls()
        .select(["trade_date", "industry_code", "fwd60"])
    )

    # 3. 合并：方向（跨行业）× 量价齐升 × 未来收益
    merged = (
        fwd_long.join(direction, on="trade_date", how="inner")
        .join(panel, on=["trade_date", "industry_code"], how="left")
        .drop_nulls()
    )
    merged = merged.with_columns(
        pl.when((pl.col("revenue_growth_ttm") > 0.0) & (pl.col("profit_growth_ttm") > 0.0))
        .then(pl.lit("量价齐升"))
        .otherwise(pl.lit("非量价齐升"))
        .alias("qlq"),
        pl.when(pl.col("direction") > 66.0)
        .then(pl.lit("方向高"))
        .when(pl.col("direction") < 33.0)
        .then(pl.lit("方向低"))
        .otherwise(pl.lit("方向中"))
        .alias("dir_group"),
    )

    print(
        f"样本: {len(merged)} 行业×日, {merged['trade_date'].min()} ~ {merged['trade_date'].max()}"
    )
    print(
        f"量价齐升占比: {merged.filter(pl.col('qlq') == '量价齐升').height / len(merged) * 100:.1f}%"
    )

    # 4. 四象限（方向高/低 × 量价齐升/非）
    print("\n=== 四象限未来 60 日收益 ===")
    for dg in ["方向高", "方向低"]:
        for q in ["量价齐升", "非量价齐升"]:
            sub = merged.filter((pl.col("dir_group") == dg) & (pl.col("qlq") == q))
            if sub.is_empty():
                print(f"  {dg}×{q}: 无样本")
            else:
                print(
                    f"  {dg}×{q}: n={len(sub)}, 未来60日收益均值={sub['fwd60'].mean() * 100:.2f}%, "
                    f"中位数={sub['fwd60'].median() * 100:.2f}%"
                )

    # 5. 关键对比：量价齐升子样本内 direction 的 IC（条件 IC）
    from scipy.stats import spearmanr

    print("\n=== 条件 IC：direction vs 未来 60 日收益 ===")
    for q in ["量价齐升", "非量价齐升"]:
        sub = merged.filter(pl.col("qlq") == q)
        if len(sub) > 30:
            rho, p = spearmanr(sub["direction"], sub["fwd60"])
            print(f"  {q} 子样本: n={len(sub)}, rho={rho:.4f}, p={p:.4f}")
    rho, p = spearmanr(merged["direction"], merged["fwd60"])
    print(f"  全样本: n={len(merged)}, rho={rho:.4f}, p={p:.4f}")


if __name__ == "__main__":
    main()
