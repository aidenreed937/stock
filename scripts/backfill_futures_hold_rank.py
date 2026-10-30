#!/usr/bin/env python3
"""基础化工期货主力合约龙虎榜席位持仓回填脚本。

数据来源:
- 上游: akshare.futures_hold_pos_sina (新浪财经-期货会员持仓龙虎榜)
- 主力合约推断:
  - 当日: ak.futures_zh_realtime 动态获取持仓量最大合约;
  - 历史: 郑商所 (CZCE) / 大商所 (DCE) 官方逐日行情缓存提取持仓量最大主力合约。
- 覆盖品种:
  - SA (纯碱), SH (烧碱), TA (PTA), UR (尿素), MA (甲醇), PP (聚丙烯), L (塑料), FG (玻璃)

物化路径:
- RAW: data/raw/industry/chemicals/futures_hold_rank/{symbol}_{YYYYMMDD}.csv
- Curated: data/curated/industry/futures_hold_rank.parquet (通过 execute_single_industry_task 物化)

用法:
    uv run scripts/backfill_futures_hold_rank.py --start-date YYYY-MM-DD [--end-date YYYY-MM-DD] \\
        [--symbols SA SH TA] [--delay 0.3] [--force] [--no-sync]
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.chemicals.collectors.futures_hold_rank import (
    CHEMICAL_FUTURES_MAP,
    FuturesHoldRankCollector,
    _save_raw_tables,
)
from stock_data.fetcher.industry.chemicals.transforms.hold_rank import (
    build_hold_rank_curated_frame,
    build_hold_rank_raw_frame,
)
from stock_data.fetcher.industry.curated_store import save_curated_dataset

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = WORKSPACE_ROOT / "data" / "raw" / "industry"
DEFAULT_CURATED_DIR = WORKSPACE_ROOT / "data" / "curated" / "industry"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def backfill_hold_rank(
    start_date: date,
    end_date: date,
    symbols: list[str] | None = None,
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    curated_dir: Path | str = DEFAULT_CURATED_DIR,
    delay: float = 0.3,
    force: bool = False,
    sync: bool = True,
) -> dict[str, Any]:
    """批量回填指定日期与品种的席位持仓龙虎榜。"""
    raw_path = Path(raw_dir)
    curated_path = Path(curated_dir)
    target_symbols = symbols or list(CHEMICAL_FUTURES_MAP.keys())
    for sym in target_symbols:
        if sym not in CHEMICAL_FUTURES_MAP:
            raise ValueError(f"未知品种 [{sym}]，支持的品种为: {list(CHEMICAL_FUTURES_MAP.keys())}")

    collector = FuturesHoldRankCollector(raw_dir=raw_path)
    rank_dir = raw_path / "chemicals" / "futures_hold_rank"
    rank_dir.mkdir(parents=True, exist_ok=True)

    trading_dates: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            trading_dates.append(cursor)
        cursor += timedelta(days=1)

    logger.info(
        "启动龙虎榜席位持仓回填: 窗口=%s ~ %s (%d 个工作日), 品种=%s, 强制刷新=%s",
        start_date.isoformat(),
        end_date.isoformat(),
        len(trading_dates),
        target_symbols,
        force,
    )

    fetched_count = 0
    cached_count = 0
    missing_count = 0
    errors: list[str] = []

    for trade_date in trading_dates:
        query_date = trade_date.strftime("%Y%m%d")
        for sym in target_symbols:
            snapshot_path = rank_dir / f"{sym}_{query_date}.csv"
            if snapshot_path.exists() and snapshot_path.stat().st_size > 0 and not force:
                cached_count += 1
                continue

            contract = collector._resolve_contract(sym, query_date)
            if not contract:
                missing_count += 1
                msg = f"{sym}:{query_date} 未能确定主力合约"
                errors.append(msg)
                logger.warning(msg)
                continue

            tables = collector._fetch_tables(sym, contract, query_date)
            if tables is None:
                missing_count += 1
                msg = f"{sym}:{query_date} ({contract}) 上游接口无数据返回"
                errors.append(msg)
                logger.warning(msg)
                continue

            df_long, df_short = tables
            _save_raw_tables(
                collector.raw_dir,
                collector.rank_dir,
                sym,
                contract,
                query_date,
                df_long,
                df_short,
            )
            fetched_count += 1
            logger.info("已保存快照 [%s %s %s]", sym, contract, query_date)

            if delay > 0:
                time.sleep(delay)

    logger.info(
        "RAW 采集完成: 新抓取=%d, 命中缓存=%d, 缺失/跳过=%d",
        fetched_count,
        cached_count,
        missing_count,
    )

    curated_records = 0
    if sync:
        logger.info("正在执行 2-Tier 物化 pipeline (从 RAW 快照离线聚合)...")
        raw_df = collector.load_raw_snapshots()
        if not raw_df.is_empty():
            raw_target = raw_path / "chemicals" / "futures_hold_rank.parquet"
            save_curated_dataset(
                build_hold_rank_raw_frame(raw_df),
                raw_target,
                primary_keys=["symbol", "trade_date", "side", "member_name_raw"],
            )
            curated_df = build_hold_rank_curated_frame(raw_df)
            curated_target = curated_path / "futures_hold_rank.parquet"
            curated_records = save_curated_dataset(
                curated_df,
                curated_target,
                primary_keys=["symbol", "trade_date"],
            )
        logger.info("Curated 物化完成: %d 条记录", curated_records)

    return {
        "fetched": fetched_count,
        "cached": cached_count,
        "missing": missing_count,
        "curated_records": curated_records,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="基础化工期货主力合约龙虎榜席位持仓回填（新浪/官方合约源）"
    )
    parser.add_argument(
        "--start-date", type=date.fromisoformat, required=True, help="起始日期 YYYY-MM-DD"
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="结束日期 YYYY-MM-DD（默认同起始日期）",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="待回填品种列表（默认全部 8 品种: SA SH TA UR MA PP L FG）",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="RAW 根目录（默认 data/raw/industry）",
    )
    parser.add_argument(
        "--curated-dir",
        type=Path,
        default=DEFAULT_CURATED_DIR,
        help="Curated 根目录（默认 data/curated/industry）",
    )
    parser.add_argument(
        "--delay", type=float, default=0.3, help="单次请求间隔延时秒数（默认 0.3s）"
    )
    parser.add_argument("--force", action="store_true", help="强制覆盖已有 RAW 快照")
    parser.add_argument("--no-sync", action="store_true", help="仅落盘 RAW，不触发 Curated 物化")

    args = parser.parse_args()
    end_date = args.end_date or args.start_date
    if args.start_date > end_date:
        logger.error("起始日期 %s 晚于结束日期 %s", args.start_date, end_date)
        return 1

    res = backfill_hold_rank(
        start_date=args.start_date,
        end_date=end_date,
        symbols=args.symbols,
        raw_dir=args.raw_dir,
        curated_dir=args.curated_dir,
        delay=args.delay,
        force=args.force,
        sync=not args.no_sync,
    )

    print("\n" + "=" * 60)
    print(" 席位持仓龙虎榜回填报告")
    print("=" * 60)
    print(f"新增拉取: {res['fetched']:>6} 份快照")
    print(f"命中缓存: {res['cached']:>6} 份快照")
    print(f"未能抓取: {res['missing']:>6} 份快照")
    if not args.no_sync:
        print(f"Curated 物化记录: {res['curated_records']:>6} 行")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
