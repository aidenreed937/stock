#!/usr/bin/env python3
"""给 GACC 黄金表回写 release_date（海关在线查询数据发布时间，确定性规则）。

依据 ``stock_data.fetcher.industry.customs.release_calendar`` 的公布时间表规则，
对 ``data/curated/industry/customs_trade_gacc.parquet`` 逐行按 ``report_month``
生成 ``release_date`` 并回写（先备份原文件到 ``.bak``）。

用法:
    uv run python scripts/backfill_customs_release_date.py            # 回写
    uv run python scripts/backfill_customs_release_date.py --dry-run  # 只打印统计
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import polars as pl

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from stock_data.fetcher.industry.customs.release_calendar import release_date_for  # noqa: E402

GOLD_PATH = Path("data/curated/industry/customs_trade_gacc.parquet")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = parser.parse_args()

    df = pl.read_parquet(GOLD_PATH)
    before = df["release_date"].is_not_null().sum()

    df = df.with_columns(
        pl.col("report_month")
        .map_elements(release_date_for, return_dtype=pl.Date)
        .alias("release_date")
    )

    after = df["release_date"].is_not_null().sum()
    print(f"report_month 范围: {df['report_month'].min()} ~ {df['report_month'].max()}")
    print(f"release_date 非空: {before} → {after}（共 {df.height} 行）")
    print("\nrelease_date 分布样例（按 report_month 去重）:")
    sample = (
        df.select(["report_month", "release_date"])
        .unique()
        .sort("report_month")
    )
    print(sample.to_pandas().to_string(index=False))

    if args.dry_run:
        print("\n[dry-run] 未写文件")
        return 0

    backup = GOLD_PATH.with_name(GOLD_PATH.name + ".bak")
    shutil.copy2(GOLD_PATH, backup)
    df.write_parquet(GOLD_PATH)
    print(f"\n已回写 {GOLD_PATH}（原文件备份至 {backup}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
