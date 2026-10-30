#!/usr/bin/env python3
"""郑商所 (CZCE) 化工大宗商品注册仓单回放脚本（仅写 RAW，Curated 由 pipeline 物化）。

支持 SA (纯碱), FG (玻璃), UR (尿素), MA (甲醇), SH (烧碱), TA (PTA)
从本地缓存的 czce_daily/*.xls|xlsx 快速回放，按品种生成 RAW CSV
(``chemicals/futures_inventory/{symbol}.csv``)。

下载/解析/合并逻辑已收编到 ``stock_data.fetcher.industry.chemicals.collectors``
（``FuturesInventoryCollector.backfill_raw``）；本脚本只做本地快照回放与 RAW
落盘，Curated ``futures_inventory.parquet`` 由
``make sync SOURCE=industry ENDPOINT=chemical_futures_inventory`` 统一物化。

历史首次下载请先运行：
    uv run scripts/backfill_czce_soda_ash_inventory.py
（SA 全历史含上市前零仓单合成行；其余品种按需补拉后可再回放本脚本）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from stock_data.fetcher.industry.chemicals.collectors.inventory import (
    FuturesInventoryCollector,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = WORKSPACE_ROOT / "data" / "raw" / "industry"


def main() -> int:
    parser = argparse.ArgumentParser(description="郑商所化工仓单 RAW 回放（仅写 RAW）")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=RAW_DIR,
        help="RAW 根目录（含 industry/chemicals 布局，默认 data/raw/industry）",
    )
    args = parser.parse_args()

    collector = FuturesInventoryCollector(raw_dir=args.raw_dir)
    summary, fetched = collector.backfill_raw(download=False)

    print("\n" + "=" * 70)
    print(" 郑商所仓单 RAW 回放汇总")
    print("=" * 70)
    for sym, count in sorted(summary.items()):
        print(f"{sym:<8} {count:>6} 行")
    print("-" * 70)
    print(f"处理快照标签数: {len(fetched)}")
    print("RAW CSV 已落盘；请运行以下命令物化 Curated：")
    print("  make sync SOURCE=industry ENDPOINT=chemical_futures_inventory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
