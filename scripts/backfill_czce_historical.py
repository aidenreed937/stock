#!/usr/bin/env python3
"""郑商所 (CZCE) 2018~2019 日行情与 2018~2020 仓单历史 RAW 回填专用脚本。

仅处理郑商所品种（TA, MA, SA, UR, SH, FG），完全隔离大商所文件路径，
支持断点续传与安全并发。
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.collectors.inventory import (
    FuturesInventoryCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.official import (
    backfill_futures_daily_raw,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("czce_historical")

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = WORKSPACE_ROOT / "data" / "raw" / "industry"

CZCE_DAILY_META: dict[str, dict[str, str]] = {
    "TA": {"name": "PTA", "main_contract": "TA0", "exchange": "CZCE"},
    "MA": {"name": "甲醇", "main_contract": "MA0", "exchange": "CZCE"},
    "UR": {"name": "尿素", "main_contract": "UR0", "exchange": "CZCE"},
    "SA": {"name": "纯碱", "main_contract": "SA0", "exchange": "CZCE"},
    "SH": {"name": "烧碱", "main_contract": "SH0", "exchange": "CZCE"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description="郑商所历史行情与仓单 RAW 回填")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--daily-start",
        type=date.fromisoformat,
        default=date(2018, 1, 1),
        help="日行情回填起始日期 (默认 2018-01-01)",
    )
    parser.add_argument(
        "--daily-end",
        type=date.fromisoformat,
        default=date(2019, 12, 5),
        help="日行情回填结束日期 (默认 2019-12-05，纯碱上市前一日)",
    )
    parser.add_argument(
        "--inv-start",
        type=date.fromisoformat,
        default=date(2018, 1, 1),
        help="仓单回填起始日期 (默认 2018-01-01)",
    )
    parser.add_argument(
        "--inv-end",
        type=date.fromisoformat,
        default=date(2020, 4, 8),
        help="仓单回填结束日期 (默认 2020-04-08，纯碱首个仓单日前一日)",
    )
    parser.add_argument("--skip-daily", action="store_true", help="跳过日行情回填")
    parser.add_argument("--skip-inventory", action="store_true", help="跳过仓单回填")
    args = parser.parse_args()

    # 1. 郑商所日行情回填
    if not args.skip_daily:
        logger.info(
            "=== 步骤 1/2: 正在回填郑商所日行情 (%s ~ %s) ===",
            args.daily_start,
            args.daily_end,
        )
        daily_dir = args.raw_dir / "chemicals" / "futures_daily"
        summary, fetched = backfill_futures_daily_raw(
            daily_dir,
            CZCE_DAILY_META,
            start_date=args.daily_start,
            end_date=args.daily_end,
            full=False,
        )
        logger.info("郑商所日行情回填汇总: %s, 新增/刷新: %d 份", summary, len(fetched))

    # 2. 郑商所仓单回填
    if not args.skip_inventory:
        logger.info(
            "=== 步骤 2/2: 正在回填郑商所交割仓单 (%s ~ %s) ===",
            args.inv_start,
            args.inv_end,
        )
        inv_coll = FuturesInventoryCollector(raw_dir=args.raw_dir)
        inv_sum, inv_fetched = inv_coll.backfill_raw(
            start_date=args.inv_start,
            end_date=args.inv_end,
            download=True,
        )
        logger.info("郑商所仓单回填汇总: %s, 新增/刷新: %d 份", inv_sum, len(inv_fetched))

    logger.info("郑商所历史回填全部完成！")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
