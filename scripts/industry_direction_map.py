"""生成全球共振方向层映射表 global_resonance_map.parquet。

方向层口径（实证见 data/analytics/industry_strategy/industry_direction_layer.md）：
- direction_score = 全球产业景气代理的滚动分位合成（0-100）；
- 实证结论（AI 腿）：direction 与科技行业未来 60 日收益显著负相关 → 语义为「风险信号/防守」，
  在因子面板中作防守门（高位 × 非量价齐升 → 减分），不用于进攻加分。

映射腿：
- AI 算力腿：电子/通信/计算机 ← SOX（费半，日频三口径滚动分位合成）；
- 新能源腿：电力设备/有色 ← 光伏装机 + 新能源车销量（月频 YoY 滚动分位合成）。

输出：data/curated/mart/global_resonance_map.parquet
列：trade_date, industry_code, direction_score
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_data.catalog.service import DataCatalog

# 方向映射：申万行业 ← 全球景气代理腿（行业专属信号，不合成后复用）
# - AI 算力：电子/通信/计算机 ← SOX（费半）
# - 新能源-电力设备：光伏装机 ← 制造端（光伏设备/电池/电网设备）
# - 新能源-汽车：新能源车销量 ← 整车需求端
# 有色金属仅"能源金属"子板块相关，需能源金属价格信号，当前无对应数据故不映射。
_AI_INDUSTRIES = ["801080.SI", "801770.SI", "801750.SI"]  # 电子/通信/计算机
_OUTPUT = Path("data/curated/mart/global_resonance_map.parquet")


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


def build_sox_direction() -> pl.DataFrame:
    """AI 算力腿：SOX 相对 200 日均线偏离 / 20 日动量 / 60 日变化 的滚动分位合成（日频）。"""
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date", "sox_close"])
        .drop_nulls()
        .sort("trade_date")
    )
    sox = gm.with_columns(
        pl.col("sox_close").rolling_mean(window_size=200).alias("ma200"),
        pl.col("sox_close").log().diff(20).alias("mom20"),
        pl.col("sox_close").log().diff(60).alias("chg60"),
    ).with_columns(((pl.col("sox_close") / pl.col("ma200") - 1.0) * 100.0).alias("ma_bias"))
    return (
        sox.with_columns(
            _rolling_pct(sox["ma_bias"].cast(pl.Float64)).alias("d1"),
            _rolling_pct(sox["mom20"].cast(pl.Float64)).alias("d2"),
            _rolling_pct(sox["chg60"].cast(pl.Float64)).alias("d3"),
        )
        .select(["trade_date", "d1", "d2", "d3"])
        .with_columns(pl.mean_horizontal(["d1", "d2", "d3"]).alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def _monthly_pct(df: pl.DataFrame, value_col: str, window_months: int = 36) -> pl.DataFrame:
    """月频序列 → YoY → 滚动分位（月频，trade_date 对齐）。"""
    out = (
        df.select(["trade_date", value_col])
        .sort("trade_date")
        .with_columns(pl.col(value_col).pct_change(12).alias("yoy"))
        .drop_nulls()
    )
    pct = _rolling_pct(out["yoy"].cast(pl.Float64), window=window_months)
    return out.with_columns(pct.alias("pct")).select(["trade_date", "pct"])


def build_new_energy_direction() -> dict[str, pl.DataFrame]:
    """新能源腿：行业专属信号（月频 → 日频前向填充）。

    - 电力设备 ← 光伏装机 YoY 分位（制造端：光伏设备/电池/电网设备）
    - 汽车 ← 新能源车销量 YoY 分位（整车需求端）
    制造端信号不再合成后映射多个行业，按行业归属拆分。
    """
    cat = DataCatalog(data_source="industry")
    solar = cat.load_dataset("solar_capacity")
    nev = cat.load_dataset("nev_monthly_sales")

    solar_col = (
        "monthly_new_capacity_3mma"
        if "monthly_new_capacity_3mma" in solar.columns
        else "monthly_new_capacity_gw"
    )
    signals = {
        "801730.SI": _monthly_pct(solar, solar_col),  # 电力设备 ← 光伏装机
        "801880.SI": _monthly_pct(nev, "wholesale_volume_ten_thousand"),  # 汽车 ← 新能源车销量
    }

    # 月频 → 日频：对齐到交易日（前向填充）
    gm = (
        pl.read_parquet("data/curated/mart/global_macro_daily.parquet")
        .select(["trade_date"])
        .sort("trade_date")
    )
    result: dict[str, pl.DataFrame] = {}
    for code, monthly in signals.items():
        daily = (
            gm.join(monthly, on="trade_date", how="left")
            .sort("trade_date")
            .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
            .select(["trade_date", "direction_score"])
            .drop_nulls()
        )
        result[code] = daily
    return result


def build_global_resonance_map() -> pl.DataFrame:
    """各腿方向分 × 申万行业 → global_resonance_map 长表。"""
    sox_dir = build_sox_direction()
    ne_dir = build_new_energy_direction()

    rows = []
    for code in _AI_INDUSTRIES:
        rows.append(sox_dir.with_columns(pl.lit(code).alias("industry_code")))
    for code, daily in ne_dir.items():
        rows.append(daily.with_columns(pl.lit(code).alias("industry_code")))
    return pl.concat(rows).select(["trade_date", "industry_code", "direction_score"])


def main() -> None:
    map_df = build_global_resonance_map()
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    map_df.write_parquet(_OUTPUT)
    print(f"global_resonance_map 已生成: {_OUTPUT}")
    print(f"行数: {len(map_df)}, 行业: {sorted(map_df['industry_code'].unique().to_list())}")
    print(f"日期: {map_df['trade_date'].min()} ~ {map_df['trade_date'].max()}")
    for code in sorted(map_df["industry_code"].unique().to_list()):
        sub = map_df.filter(pl.col("industry_code") == code)
        print(
            f"  {code}: {len(sub)} 行, direction "
            f"min={sub['direction_score'].min():.1f} max={sub['direction_score'].max():.1f} "
            f"mean={sub['direction_score'].mean():.1f}"
        )


if __name__ == "__main__":
    main()
