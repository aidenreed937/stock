"""全球能源与国家能源局 (NEA / IRENA) 命令行管理工具。

提供能源数据增量同步、黄金事实表体检与快捷交互查询三大核心指令。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger, setup_logger
from stock_data.pipeline.energy_pipeline import sync_all_energy_data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-cli-energy",
        description="全球能源与国家能源局 (NEA / IRENA) 数据自动化管理工具",
    )
    subparsers = parser.add_subparsers(dest="action", help="执行操作子命令")

    # 1. 同步子命令: sync
    p_sync = subparsers.add_parser("sync", help="增量或全量同步能源数据")
    p_sync.add_argument(
        "-s",
        "--source",
        choices=["all", "cn_nea", "irena", "ember"],
        default="all",
        help="目标数据源 (默认 all)",
    )
    p_sync.add_argument("--force", action="store_true", help="强制重新拉取")

    # 2. 状态检查子命令: inspect
    subparsers.add_parser("inspect", help="查看已落盘的 Curated 黄金事实表摘要")

    # 3. 快速查询子命令: query
    p_query = subparsers.add_parser("query", help="快速查询装机或发电时序")
    p_query.add_argument(
        "-t",
        "--table",
        choices=["capacity", "generation"],
        default="capacity",
        help="目标事实表 (capacity: 装机, generation: 发电)",
    )
    p_query.add_argument("-g", "--geo", default="CHN", help="国家/区域代码 (默认 CHN)")
    p_query.add_argument("--tech", default=None, help="细分技术类型 (如 SOLAR_PV, WIND_TOTAL)")
    p_query.add_argument("-n", "--limit", type=int, default=20, help="最多显示记录数 (默认 20)")

    # 4. 历史回填子命令: backfill
    p_backfill = subparsers.add_parser("backfill", help="历史多年度长周期数据全量回填与差分重构")
    p_backfill.add_argument(
        "-s",
        "--source",
        choices=["all", "cn_nea", "irena", "ember"],
        default="all",
        help="目标回填数据源 (默认 all)",
    )
    p_backfill.add_argument("--force", action="store_true", help="强制刷新并重构历史数据")

    return parser


def _handle_backfill(args: argparse.Namespace) -> int:
    sources = None if args.source == "all" else [args.source]
    logger.info(f"开始执行能源历史全量回填: sources={sources}, force={args.force}")
    results = sync_all_energy_data(sources=sources)
    logger.info(f"历史回填完成，黄金表更新结果: {results}")
    return 0


def _handle_sync(args: argparse.Namespace) -> int:
    sources = None if args.source == "all" else [args.source]
    logger.info(f"开始同步能源数据: sources={sources}")
    results = sync_all_energy_data(sources=sources)
    logger.info(f"同步完成，落盘结果: {results}")
    return 0


def _handle_inspect() -> int:
    cap_path = Path("data/curated/industry/energy/global_renewable_capacity.parquet")
    gen_path = Path("data/curated/industry/energy/global_power_generation.parquet")

    logger.info("=== 全球能源 Curated 黄金事实表状态 ===")
    if cap_path.exists():
        df_cap = pl.read_parquet(cap_path)
        min_yr = str(df_cap["year"].min())
        max_yr = str(df_cap["year"].max())
        logger.info(
            f"[装机事实表] {cap_path.name}: 总记录 {df_cap.height} 行, "
            f"覆盖国家 {df_cap['geo_code'].n_unique()} 个, "
            f"年份跨度 {min_yr} ~ {max_yr}"
        )
    else:
        logger.warning(f"[装机事实表] 缺失: {cap_path}")

    if gen_path.exists():
        df_gen = pl.read_parquet(gen_path)
        min_dt = str(df_gen["trade_date"].min())
        max_dt = str(df_gen["trade_date"].max())
        logger.info(
            f"[发电事实表] {gen_path.name}: 总记录 {df_gen.height} 行, "
            f"覆盖国家 {df_gen['geo_code'].n_unique()} 个, "
            f"日期范围 {min_dt} ~ {max_dt}"
        )
    else:
        logger.warning(f"[发电事实表] 缺失: {gen_path}")
    return 0


def _handle_query(args: argparse.Namespace) -> int:
    if args.table == "capacity":
        file_path = Path("data/curated/industry/energy/global_renewable_capacity.parquet")
    else:
        file_path = Path("data/curated/industry/energy/global_power_generation.parquet")

    if not file_path.exists():
        logger.error(f"数据文件不存在: {file_path}")
        return 1

    df = pl.read_parquet(file_path)
    if "geo_code" in df.columns:
        df = df.filter(pl.col("geo_code") == args.geo.upper())

    if args.tech and "technology" in df.columns:
        df = df.filter(pl.col("technology") == args.tech.upper())

    if "year" in df.columns:
        df = df.sort("year")
    elif "trade_date" in df.columns:
        df = df.sort("trade_date")

    display_df = df.tail(args.limit)
    with pl.Config(tbl_cols=-1, tbl_rows=args.limit + 5, tbl_width_chars=160):
        print(f"\n--- 查询结果: table={args.table}, geo={args.geo}, tech={args.tech} ---")
        print(display_df)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口函数。"""
    setup_logger()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.action:
        parser.print_help()
        return 0

    if args.action == "sync":
        return _handle_sync(args)
    if args.action == "backfill":
        return _handle_backfill(args)
    if args.action == "inspect":
        return _handle_inspect()
    if args.action == "query":
        return _handle_query(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
