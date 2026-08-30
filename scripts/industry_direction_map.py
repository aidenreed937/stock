"""生成全球共振方向层映射表 global_resonance_map.parquet。

方向层口径（实证见 data/analytics/industry_strategy/industry_direction_layer.md）：
- direction_score = SOX 相对 200 日均线偏离 / 20 日动量 / 60 日变化 的滚动分位合成（0-100）；
- 实证结论：direction 与科技行业未来 60 日收益显著负相关 → 语义为「风险信号/防守」，
  不用于进攻加分；在因子面板中作防守门（高位 × 非量价齐升 → 减分）。

当前映射：AI 算力腿（电子/通信/计算机 ← SOX + 全球半导体景气）。
新能源/机器人腿待装机/出货历史数据补齐后扩展。

输出：data/curated/mart/global_resonance_map.parquet
列：trade_date, industry_code, direction_score
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

# AI 算力方向映射的申万行业（实证对象：电子/通信/计算机）
_AI_INDUSTRIES = ["801080.SI", "801770.SI", "801750.SI"]
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


def build_direction_score() -> pl.DataFrame:
    """从 SOX 计算日频方向分（跨行业同值）。"""
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
    direction = (
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
    return direction


def build_global_resonance_map() -> pl.DataFrame:
    """方向分 × 申万行业 → global_resonance_map 长表。"""
    direction = build_direction_score()
    rows = []
    for code in _AI_INDUSTRIES:
        rows.append(direction.with_columns(pl.lit(code).alias("industry_code")))
    return pl.concat(rows).select(["trade_date", "industry_code", "direction_score"])


def main() -> None:
    map_df = build_global_resonance_map()
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    map_df.write_parquet(_OUTPUT)
    print(f"global_resonance_map 已生成: {_OUTPUT}")
    print(f"行数: {len(map_df)}, 行业: {sorted(map_df['industry_code'].unique().to_list())}")
    print(f"日期: {map_df['trade_date'].min()} ~ {map_df['trade_date'].max()}")
    print(
        f"direction_score 分布: min={map_df['direction_score'].min():.1f}, "
        f"max={map_df['direction_score'].max():.1f}, mean={map_df['direction_score'].mean():.1f}"
    )


if __name__ == "__main__":
    main()
