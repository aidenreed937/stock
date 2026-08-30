"""方向层口径验证：全球半导体景气方向 vs A 股科技行业未来收益。

验证「全球资本开支方向（SOX / 全球半导体销售额）→ 申万电子/通信/计算机」的预测力，
为 direction_score 选择口径。对齐产业趋势跟踪三层框架的方向层。

口径（均为 0-100 方向分，越高越景气）：
- sox_ma_bias：SOX 相对 200 日均线偏离（按历史滚动分位归一）
- sox_mom20：SOX 20 日动量（历史滚动分位）
- semi_yoy_pct：全球半导体销售额 YoY（月度，前向填充，历史滚动分位）
- composite：三口径等权均值

目标：申万电子(801080.SI)/通信(801770.SI)/计算机(801750.SI) 等权组合未来 20 日收益。
指标：时间序列 Spearman 相关（方向分 vs 未来收益）、按方向分高低分组的未来收益差。
"""

from __future__ import annotations

import polars as pl

from stock_data.catalog.service import DataCatalog

_TRADING_DAYS = 252.0


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

    # 1. SOX（日频）与半导体销售额（月频）
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date", "sox_close"])
        .drop_nulls()
    )
    semi = (
        cat.load_dataset("semiconductor_sales")
        .select(["trade_date", "global_sales_usd"])
        .sort("trade_date")
    )

    # 2. 科技行业日线（电子/通信/计算机）
    ind = (
        pl.read_parquet("data/curated/mart/industry_daily.parquet")
        .filter(pl.col("industry_code").is_in(["801080.SI", "801770.SI", "801750.SI"]))
        .select(["trade_date", "industry_code", "close"])
        .sort(["trade_date", "industry_code"])
    )

    # 3. SOX 口径
    sox = gm.with_columns(
        pl.col("sox_close").rolling_mean(window_size=200).alias("ma200"),
        pl.col("sox_close").log().diff(20).alias("mom20"),
        pl.col("sox_close").log().diff(60).alias("chg60"),
    ).with_columns(
        ((pl.col("sox_close") / pl.col("ma200") - 1.0) * 100.0).alias("ma_bias"),
    )
    sox = sox.with_columns(
        _rolling_pct(sox["ma_bias"].cast(pl.Float64)).alias("sox_ma_bias"),
        _rolling_pct(sox["mom20"].cast(pl.Float64)).alias("sox_mom20"),
        _rolling_pct(sox["chg60"].cast(pl.Float64)).alias("sox_chg60"),
    ).select(["trade_date", "sox_ma_bias", "sox_mom20", "sox_chg60"])

    # 4. 半导体销售额 YoY（月频，pct_change(12)，60 个月滚动分位 → 日频前向填充）
    semi_pct = semi.with_columns(
        pl.col("global_sales_usd").pct_change(12).alias("yoy")
    ).drop_nulls()
    semi_pct = semi_pct.with_columns(
        _rolling_pct(semi_pct["yoy"].cast(pl.Float64), window=60).alias("semi_yoy_pct")
    ).select(["trade_date", "semi_yoy_pct"])

    # 5. 行业组合未来 20/60 日收益（等权）
    ind_wide = ind.pivot(on="industry_code", index="trade_date", values="close").sort("trade_date")
    combo = ind_wide.with_columns(
        pl.mean_horizontal(
            [pl.col(c) for c in ["801080.SI", "801770.SI", "801750.SI"] if c in ind_wide.columns]
        ).alias("combo")
    ).select(["trade_date", "combo"])
    combo = combo.with_columns(
        (pl.col("combo").shift(-20) / pl.col("combo") - 1.0).alias("fwd20"),
        (pl.col("combo").shift(-60) / pl.col("combo") - 1.0).alias("fwd60"),
    ).drop_nulls()

    # 6. 合并（月频指标前向填充到日频）
    merged = (
        sox.join(semi_pct, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("semi_yoy_pct").fill_null(strategy="forward"))
        .join(combo, on="trade_date", how="inner")
        .drop_nulls()
    )
    merged = merged.with_columns(
        pl.mean_horizontal(["sox_ma_bias", "sox_mom20", "sox_chg60", "semi_yoy_pct"]).alias(
            "composite"
        )
    )
    # 方向变化口径：composite 的 60 日环比（景气改善/恶化）
    merged = merged.sort("trade_date").with_columns(
        (pl.col("composite") - pl.col("composite").shift(60)).alias("composite_chg60")
    )

    print(
        f"样本: {len(merged)} 交易日, {merged['trade_date'].min()} ~ {merged['trade_date'].max()}"
    )

    # 7. 时间序列 Spearman IC（未来 20 日 / 60 日）
    from scipy.stats import spearmanr

    for horizon in ["fwd20", "fwd60"]:
        print(f"\n=== 方向分 vs 科技组合未来 {horizon[-2:]} 日收益 (Spearman) ===")
        for col in [
            "sox_ma_bias",
            "sox_mom20",
            "sox_chg60",
            "semi_yoy_pct",
            "composite",
            "composite_chg60",
        ]:
            rho, p = spearmanr(
                merged.select([col, horizon]).drop_nulls()[col],
                merged.select([col, horizon]).drop_nulls()[horizon],
            )
            print(f"  {col}: rho={rho:.4f}, p={p:.4f}")

    # 8. 方向分高/低分组的未来 60 日收益（按 composite 分 5 组）
    print("\n=== composite 方向分 5 分组未来 60 日收益 ===")
    groups = merged.with_columns(
        (pl.col("composite").rank() / pl.col("composite").count() * 5)
        .cast(pl.Int32)
        .clip(0, 4)
        .alias("g")
    )
    for g in range(5):
        sub = groups.filter(pl.col("g") == g)
        if not sub.is_empty():
            print(
                f"  组{g} (最低): n={len(sub)}, 未来60日收益均值={sub['fwd60'].mean() * 100:.2f}%"
            )


if __name__ == "__main__":
    main()
