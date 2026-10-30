#!/usr/bin/env python3
"""构建公司海外营收布局 Mart（海外营收/占比/同比，point-in-time 无前视）。

用法:
    uv run python scripts/build_overseas_revenue_mart.py
    uv run python scripts/build_overseas_revenue_mart.py --output data/analytics/industry
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import cast

import polars as pl

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from stock_analytics.marts.overseas_revenue import (  # noqa: E402
    DEFAULT_INCOME_DIR,
    DEFAULT_MAINBZ_DIR,
    build_overseas_revenue_mart,
    save_overseas_revenue_mart,
)

DEFAULT_OUTPUT = Path("data/analytics/industry")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--income", default=str(DEFAULT_INCOME_DIR))
    parser.add_argument("--mainbz", default=str(DEFAULT_MAINBZ_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    mart = build_overseas_revenue_mart(
        income_dir=args.income,
        mainbz_dir=args.mainbz,
    )
    pq, csv_path = save_overseas_revenue_mart(mart, args.output)

    latest_end = cast("date", mart["end_date"].max())
    n = mart.filter(pl.col("end_date") == latest_end)
    overseas = n.filter(pl.col("overseas_revenue") > 0)
    print(f"=== 海外营收布局 Mart（最新报告期 {latest_end.isoformat()}）===")
    print(f"公司总数: {n.height}   有海外营收的公司: {overseas.height}")
    print("\n披露质量分布（最新报告期）:")
    for disc, cnt in (
        n.group_by("disclosure").agg(pl.len().alias("n")).sort("n", descending=True).iter_rows()
    ):
        print(f"  {disc:<14} {cnt}")
    print("\n海外营收 Top10（亿元）:")
    top = (
        overseas.sort("overseas_revenue", descending=True)
        .head(10)
        .select(
            [
                "symbol",
                "overseas_revenue",
                "overseas_ratio",
                "overseas_gross_margin",
                "overseas_revenue_yoy",
                "disclosure",
            ]
        )
    )
    print(
        top.with_columns(
            pl.col("overseas_revenue").round(1),
            pl.col("overseas_ratio").round(3),
            pl.col("overseas_gross_margin").round(3),
            pl.col("overseas_revenue_yoy").round(3),
        )
        .to_pandas()
        .to_string(index=False)
    )
    print(f"\n已写出: {pq}")
    print(f"已写出: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
