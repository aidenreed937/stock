"""生意社 100ppi 大宗商品现期基差与现货价格 10 年+ 历史回填脚本。

用法示例:
    # 1. 抽样测试指定日期窗口 (如 2026 年 3 月上旬)
    uv run python scripts/backfill_100ppi_basis.py --start-date 2026-03-01 --end-date 2026-03-07

    # 2. 回填近 3 年主要化工品 (PTA, 纯碱, 乙二醇, 甲醇, PVC, 尿素)
    uv run python scripts/backfill_100ppi_basis.py --start-date 2023-01-01 --symbols TA,SA,MEG,MA,V,UR

    # 3. 全量回填 2011 至今并显示统计
    uv run python scripts/backfill_100ppi_basis.py --start-date 2011-01-04
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys

from stock_data.fetcher.industry.chemicals.collectors.basis import SpotFuturesBasisCollector
from stock_data.fetcher.industry.chemicals.transforms.basis import (
    materialize_basis_records_to_curated,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_100ppi_basis")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="生意社 100ppi 现期基差与历史现货出厂价长周期回填工具"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2023-01-01",
        help="回填起始日期 (YYYY-MM-DD，默认 2023-01-01)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.date.today().isoformat(),
        help="回填截止日期 (YYYY-MM-DD，默认今日)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="待过滤的品类代码列表 (英文逗号分隔，如 TA,SA,MEG,MA,V,UR，留空表示全量采集)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="网络请求间隔秒数 (防爬限流，默认 0.3 秒)",
    )
    parser.add_argument(
        "--raw-dir",
        type=str,
        default="data/raw/industry/chemicals",
        help="RAW 快照存储根目录",
    )
    parser.add_argument(
        "--curated-dir",
        type=str,
        default="data/curated/industry",
        help="Curated 黄金事实表输出目录",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅下载与解析，不写入 Curated 黄金事实表",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载，忽略本地 RAW 快照缓存",
    )

    args = parser.parse_args()

    start_d = datetime.date.fromisoformat(args.start_date)
    end_d = datetime.date.fromisoformat(args.end_date)
    target_syms = {s.strip() for s in args.symbols.split(",") if s.strip()} or None

    logger.info(
        f"开始回填任务: 日期范围 [{start_d} ~ {end_d}], "
        f"目标品种: {target_syms or '全市场 40+ 品种'}, 延迟: {args.delay}s"
    )

    collector = SpotFuturesBasisCollector(raw_dir=args.raw_dir)
    records = collector.collect_date_range(
        start_date=start_d,
        end_date=end_d,
        symbols=target_syms,
        delay_seconds=args.delay,
        force=args.force,
    )

    logger.info(f"数据采集与解析完成，共获取 {len(records)} 条现期基差记录")

    if not records:
        logger.warning("未采集到任何记录，请检查日期范围或网络状态")
        sys.exit(0)

    # 统计覆盖品种分布
    sym_counts: dict[str, int] = {}
    for r in records:
        sym_counts[r.symbol] = sym_counts.get(r.symbol, 0) + 1

    logger.info("品种记录分布 top 10:")
    for sym, cnt in sorted(sym_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        logger.info(f"  - {sym:10s}: {cnt} 条")

    if args.dry_run:
        logger.info("--dry-run 模式，跳过 Curated 物化")
        return

    # 物化写入 Curated
    spot_inc, total_basis = materialize_basis_records_to_curated(
        records=records,
        curated_dir=args.curated_dir,
        update_spot_price=True,
    )
    logger.info(
        f"物化成功: chemical_spot_price 净增 {spot_inc} 行, "
        f"chemical_futures_basis 累计达 {total_basis} 行"
    )


if __name__ == "__main__":
    main()
