#!/usr/bin/env python3
"""构建申万三级行业日频行情 Mart（industry_l3_daily）。

数据源：TuShare 申万指数日线黄金表 ``data/curated/tushare/market=CN/sw_daily``
（2013-01 起，含 L1/L2/L3 三层，6 位 industry_code 口径）。

产出：``data/curated/mart/industry_l3_daily.parquet``
字段：trade_date / industry_code（6 位）/ industry_name / parent_code / close / amount。

用途：L3 行业指数收益事件研究（如「复苏后上车区间」L2 vs L3 对比）的行情底座；
与 ``industry_l2_daily`` 同源（sw_daily）、只切 L3 层，口径对齐。

用法（仓库根目录）：
    uv run python scripts/build_industry_l3_daily.py [--out data/curated/mart/industry_l3_daily.parquet]
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import polars as pl

SW_DAILY_ROOT = Path("data/curated/tushare/market=CN/sw_daily")
DEFAULT_OUT = Path("data/curated/mart/industry_l3_daily.parquet")

SELECT = ["trade_date", "industry_code", "name", "parent_code", "close", "amount"]


def load_sw_daily_l3(root: Path) -> pl.DataFrame:
    """读取全部 sw_daily 分区并过滤 L3 层。"""
    files = sorted(glob.glob(str(root / "year=*/month=*/data.parquet")))
    if not files:
        raise FileNotFoundError(f"sw_daily 分区未找到: {root}")
    frames = []
    for f in files:
        d = pl.read_parquet(f)
        if "industry_level" not in d.columns:
            continue
        l3 = d.filter(pl.col("industry_level") == "L3")
        if l3.is_empty():
            continue
        frames.append(
            l3.select(
                "trade_date",
                "industry_code",
                "parent_code",
                "close",
                "amount",
                pl.col("name").alias("industry_name"),
            ).with_columns(
                pl.col("industry_code").cast(pl.Utf8, strict=False),
                pl.col("industry_name").cast(pl.Utf8, strict=False),
                pl.col("parent_code").cast(pl.Utf8, strict=False),
                pl.col("close").cast(pl.Float64, strict=False),
                pl.col("amount").cast(pl.Float64, strict=False),
            )
        )
    if not frames:
        raise ValueError("sw_daily 无 L3 行")
    return (
        pl.concat(frames)
        .unique(subset=["trade_date", "industry_code"], keep="first")
        .drop_nulls(subset=["trade_date", "industry_code", "close"])
        .sort(["industry_code", "trade_date"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    df = load_sw_daily_l3(SW_DAILY_ROOT)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(args.out)
    print(f"industry_l3_daily 写入: {args.out}")
    print(
        f"  rows={df.height} codes={df['industry_code'].n_unique()} "
        f"range={df['trade_date'].min()}~{df['trade_date'].max()}"
    )


if __name__ == "__main__":
    main()
