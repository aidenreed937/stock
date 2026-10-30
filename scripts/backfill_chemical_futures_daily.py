#!/usr/bin/env python3
"""基础化工期货主力合约日度行情回填脚本（仅写 RAW，Curated 由 pipeline 物化）。

数据权威源:
- CZCE 品种 (SA/SH/TA/UR/MA/FG)：郑商所官网逐日官方行情文件 ``FutureDataDaily.txt``
  （含全部合约的今开盘/最高/最低/今收盘/今结算/成交量/持仓量），按当日持仓量最大
  合约确认为"主力"，取其结算价等组成主力连续日序列；
- DCE 品种 (V/PP/L/EB)：大商所官网逐日官方行情导出 (``publicweb/quotesdata``
  ``exportDayQuotesChData.html``)，同样按当日持仓量最大合约确认为"主力"。

下载/解析/增量合并逻辑已收编到
``stock_data.fetcher.industry.chemicals.collectors.official``，本脚本只负责把
官方快照物化为 RAW CSV (``chemicals/futures_daily/{symbol}.csv``)；Curated
``futures_daily.parquet`` 由 ``make sync SOURCE=industry ENDPOINT=chemical_futures_daily``
统一物化。

用法:
    uv run scripts/backfill_chemical_futures_daily.py [--start-date YYYY-MM-DD] \\
        [--end-date YYYY-MM-DD] [--full] [--raw-dir data/raw/industry]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.collectors.futures_price import (
    FuturesPriceCollector,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = WORKSPACE_ROOT / "data" / "raw" / "industry"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="基础化工期货主力合约日度行情回填（郑商所/大商所官方源，仅写 RAW）"
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="RAW 根目录（含 industry/chemicals 布局，默认 data/raw/industry）",
    )
    parser.add_argument("--start-date", type=date.fromisoformat, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=date.fromisoformat, help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量回填（DCE 检测到新浪旧行时会自动切全量，默认增量补拉）",
    )
    args = parser.parse_args()

    collector = FuturesPriceCollector(raw_dir=args.raw_dir)
    summary, fetched = collector.backfill_raw(
        start_date=args.start_date,
        end_date=args.end_date,
        full=args.full,
    )

    print("\n" + "=" * 70)
    print(" 期货日行情 RAW 回填汇总")
    print("=" * 70)
    for sym, count in sorted(summary.items()):
        print(f"{sym:<8} {count:>6} 行")
    print("-" * 70)
    print(f"新增/刷新标签数: {len(fetched)}")
    print("RAW CSV 已落盘；请运行以下命令物化 Curated：")
    print("  make sync SOURCE=industry ENDPOINT=chemical_futures_daily")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
