"""海关进出口贸易数据 (UN Comtrade / GACC) 命令行管理入口。

提供海关重点赛道历史回填、月度增量同步与配置字典检查三大核心指令。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger, setup_logger
from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.customs import (
    ComtradeCollector,
    records_to_customs_trade_frame,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-cli-customs",
        description="海关贸易数据 (UN Comtrade / GACC) 自动化管理工具",
    )
    subparsers = parser.add_subparsers(dest="action", help="执行操作子命令")

    # 1. 历史回填子命令: backfill
    p_backfill = subparsers.add_parser("backfill", help="跨年度历史贸易数据高效批量回填")
    p_backfill.add_argument("--start-year", type=int, default=2015, help="起始年份 (默认 2015)")
    p_backfill.add_argument("--end-year", type=int, default=2024, help="结束年份 (默认 2024)")
    p_backfill.add_argument(
        "--catalog",
        default="config/data/customs/hs_codes_catalog.csv",
        help="HS 编码字典表路径",
    )
    p_backfill.add_argument(
        "--curated",
        default="data/curated/industry/customs_trade.parquet",
        help="Curated 事实表输出路径",
    )
    p_backfill.add_argument("--force", action="store_true", help="强制重新拉取已存在的年份快照")

    # 2. 增量同步子命令: sync
    p_sync = subparsers.add_parser("sync", help="增量数据拉取或全量本地快照刷新")
    p_sync.add_argument(
        "-p",
        "--period",
        default=None,
        help="指定月份拉取 (格式: YYYY-MM，缺省时刷新本地所有 RAW 快照)",
    )
    p_sync.add_argument(
        "--catalog",
        default="config/data/customs/hs_codes_catalog.csv",
        help="HS 编码字典表路径",
    )

    # 3. 字典检查子命令: catalog
    p_catalog = subparsers.add_parser("catalog", help="打印当前配置的 39 个税号与 24 个赛道对照表")
    p_catalog.add_argument(
        "--catalog",
        default="config/data/customs/hs_codes_catalog.csv",
        help="HS 编码字典表路径",
    )

    return parser


def handle_backfill(args: argparse.Namespace) -> int:
    """处理 backfill 批量回填任务。"""
    collector = ComtradeCollector(catalog_path=args.catalog)
    rows = collector.backfill(
        start_year=args.start_year,
        end_year=args.end_year,
        force=args.force,
        curated_path=args.curated,
    )
    if rows > 0:
        logger.info(f"✅ 历史海关数据回填成功: 共生成 {rows} 行黄金事实数据")
        return 0
    logger.error("❌ 历史海关数据回填失败或未拉取到有效数据")
    return 1


def handle_sync(args: argparse.Namespace) -> int:
    """处理增量同步或本地快照重算任务。"""
    collector = ComtradeCollector(catalog_path=args.catalog)
    if args.period:
        period = args.period.strip().replace("-", "")
        logger.info(f"🚀 开始同步海关贸易月度数据: {args.period}")
        raw_items = collector.fetch_api(period=period)
        if not raw_items:
            logger.warning(f"⚠️ 未拉取到 {args.period} 的有效数据，尝试从本地已有快照重新刷新")
    else:
        logger.info("🚀 未指定 -p/--period 参数，正在从本地已有 RAW 快照重新计算并刷新事实表")

    all_records = collector.collect()
    if not all_records:
        logger.error("❌ 本地无任何海关有效记录")
        return 1

    df_curated = records_to_customs_trade_frame(all_records)
    curated_path = Path("data/curated/industry/customs_trade.parquet")
    row_count = save_curated_fact(
        df_curated,
        curated_path,
        primary_keys=["product_key", "hs_code", "report_month"],
    )
    logger.info(f"✅ 海关贸易事实表刷新成功 [{curated_path.name}]: 当前总行数 {row_count}")
    return 0


def handle_catalog(args: argparse.Namespace) -> int:
    """打印海关税号与行业对照表。"""
    catalog_path = Path(args.catalog)
    if not catalog_path.exists():
        logger.error(f"未找到税号配置文件: {catalog_path}")
        return 1

    df = pl.read_csv(catalog_path)
    logger.info(f"\n=== 海关重点出口品类与申万行业映射字典 ({len(df)} 行) ===\n")
    cols = [
        "category_name",
        "product_name",
        "hs_code",
        "quantity_unit",
        "target_l1_name",
        "target_l2_names",
    ]
    print(df.select([c for c in cols if c in df.columns]).to_pandas().to_string(index=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口点。"""
    setup_logger()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.action:
        parser.print_help()
        return 0

    if args.action == "backfill":
        return handle_backfill(args)
    if args.action == "sync":
        return handle_sync(args)
    if args.action == "catalog":
        return handle_catalog(args)

    logger.error(f"未知子命令: {args.action}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
