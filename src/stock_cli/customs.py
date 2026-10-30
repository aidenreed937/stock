"""海关进出口贸易数据 (UN Comtrade / GACC) 命令行管理入口。

提供 Tariffline 原始税则线采集、GACC 人工 CSV 导入/回放与配置字典检查指令。
历史回填（backfill）与增量同步（sync）命令已移除——海关 Curated 统一走 GACC 采集。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger, setup_logger
from stock_data.fetcher.industry.common import save_curated_fact
from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.customs import (
    DEFAULT_TARIFFLINE_RAW_DIR,
    ComtradeCollector,
    GaccCollector,
    records_to_customs_trade_frame,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-cli-customs",
        description="海关贸易数据 (UN Comtrade / GACC) 自动化管理工具",
    )
    subparsers = parser.add_subparsers(dest="action", help="执行操作子命令")

    # 1. Tariffline 原始税则线采集子命令
    p_tariffline = subparsers.add_parser(
        "tariffline", help="采集 UN Comtrade Tariffline 原始八位税则线"
    )
    p_tariffline.add_argument(
        "-p",
        "--period",
        required=True,
        help="指定月份，格式 YYYY-MM；可用逗号指定多个月份",
    )
    p_tariffline.add_argument(
        "--cmd-codes",
        default=None,
        help="父级 HS 码或已确认税则线，逗号分隔；缺省按主表全部六位父码逐个请求",
    )
    p_tariffline.add_argument(
        "--flow",
        choices=("import", "export", "both"),
        default="export",
        help="贸易方向（默认 export）",
    )
    p_tariffline.add_argument(
        "--catalog",
        default="config/data/customs/good_h8_codes.csv",
        help="HS 编码字典表路径",
    )
    p_tariffline.add_argument(
        "--raw-dir",
        default=DEFAULT_TARIFFLINE_RAW_DIR,
        help="Tariffline 原始快照输出目录",
    )
    p_tariffline.add_argument(
        "--max-records",
        type=int,
        default=100000,
        help="单个父码请求的 API 返回上限，达到上限将拒绝写入（默认 100000）",
    )

    # 4. GACC 人工导出 CSV 导入与 RAW 回放子命令
    p_gacc_import = subparsers.add_parser(
        "gacc-import", help="导入人工从中国海关统计平台导出的 CSV"
    )
    _add_gacc_import_arguments(p_gacc_import)

    p_gacc_replay = subparsers.add_parser(
        "gacc-replay", help="从 GACC RAW manifest 快照重建 Curated"
    )
    _add_gacc_replay_arguments(p_gacc_replay)

    # 5. 字典检查子命令: catalog
    p_catalog = subparsers.add_parser("catalog", help="打印当前配置的税号与赛道对照表")
    p_catalog.add_argument(
        "--catalog",
        default="config/data/customs/good_h8_codes.csv",
        help="HS 编码字典表路径",
    )

    return parser


def _add_gacc_paths(parser: argparse.ArgumentParser) -> None:
    """添加 GACC 目录与输出参数。"""
    parser.add_argument(
        "--catalog",
        default="config/data/customs/good_h8_codes.csv",
        help="完整 HS 与申万行业映射表路径",
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw/industry",
        help="产业 RAW 根目录，GACC 最终写入 customs/gacc",
    )
    parser.add_argument(
        "--curated",
        default="data/curated/industry/customs_trade_gacc.parquet",
        help="GACC Curated 输出路径",
    )


def _add_gacc_import_arguments(parser: argparse.ArgumentParser) -> None:
    """添加人工 GACC CSV 导入参数。"""
    parser.add_argument("--file", required=True, help="人工导出的 GACC CSV 路径")
    parser.add_argument(
        "-p",
        "--period",
        "--start-month",
        dest="start_month",
        required=True,
        help="导出数据的起始月份，格式 YYYY-MM",
    )
    parser.add_argument(
        "--end-month",
        default=None,
        help="导出数据的结束月份，格式 YYYY-MM；缺省与起始月份相同",
    )
    parser.add_argument(
        "--flow",
        choices=("import", "export"),
        required=True,
        help="贸易方向；单个 CSV 必须明确为 import 或 export",
    )
    parser.add_argument(
        "--currency",
        choices=("USD",),
        default="USD",
        help="金额币制；当前 Curated 契约固定为 USD",
    )
    parser.add_argument("--force", action="store_true", help="覆盖同口径已有 RAW 快照")
    _add_gacc_paths(parser)


def _add_gacc_replay_arguments(parser: argparse.ArgumentParser) -> None:
    """添加 GACC RAW 回放参数。"""
    parser.add_argument(
        "-p",
        "--period",
        "--start-month",
        dest="start_month",
        default=None,
        help="起始月份，格式 YYYY-MM；缺省回放全部月份",
    )
    parser.add_argument("--end-month", default=None, help="结束月份，格式 YYYY-MM")
    parser.add_argument(
        "--flow",
        choices=("import", "export", "both"),
        default="both",
        help="贸易方向（默认 both）",
    )
    parser.add_argument(
        "--currency",
        choices=("USD",),
        default="USD",
        help="金额币制；当前 Curated 契约固定为 USD",
    )
    _add_gacc_paths(parser)


def handle_tariffline(args: argparse.Namespace) -> int:
    """处理 Tariffline 原始八位税则线采集，不写入现有 HS6 Curated。"""
    flow_code = {"import": "M", "export": "X", "both": "M,X"}[args.flow]
    period = ",".join(
        part.strip().replace("-", "") for part in args.period.split(",") if part.strip()
    )
    if not period:
        logger.error("Tariffline period 不能为空")
        return 1
    cmd_codes = args.cmd_codes.split(",") if args.cmd_codes else None
    collector = ComtradeCollector(
        catalog_path=args.catalog,
        tariffline_raw_dir=args.raw_dir,
    )
    try:
        raw_items = collector.fetch_tariffline_api(
            period=period,
            flow_code=flow_code,
            cmd_codes=cmd_codes,
            max_records=args.max_records,
        )
    except ValueError as exc:
        logger.error("Tariffline 参数错误: %s", exc)
        return 2
    if not raw_items:
        logger.error("Tariffline 未返回有效原始记录")
        return 1
    logger.info(
        "Tariffline 原始快照采集成功: periods=%s, flow=%s, records=%d, raw_dir=%s",
        period,
        flow_code,
        len(raw_items),
        args.raw_dir,
    )
    return 0


def _save_gacc_collection(args: argparse.Namespace, collection: IndustryCollectionResult) -> int:
    """保存 GACC 采集结果到 Curated。"""
    if not collection.records:
        logger.error("GACC 未生成有效记录；请检查导出 CSV、月份和 HS 白名单")
        return 1
    if getattr(collection, "status", "SUCCESS") not in {"SUCCESS", "NO_CHANGE"}:
        logger.error("GACC 回放部分失败: %s", "; ".join(collection.errors))
        return 1
    row_count = save_curated_fact(
        records_to_customs_trade_frame(collection.records),
        Path(args.curated),
        primary_keys=[
            "product_key",
            "hs_code",
            "report_month",
            "trade_direction",
            "trade_value_currency",
        ],
    )
    logger.info("GACC 数据落盘成功 [%s]: 当前总行数 %d", args.curated, row_count)
    return 0


def _build_gacc_collector(args: argparse.Namespace) -> GaccCollector:
    """按 CLI 参数创建 GACC 导入/回放采集器。"""
    collector = GaccCollector(
        raw_dir=args.raw_dir,
        catalog_path=args.catalog,
    )

    return collector


def handle_gacc_import(args: argparse.Namespace) -> int:
    """处理人工导出 GACC CSV 导入。"""
    collector = _build_gacc_collector(args)
    collection = collector.import_csv(
        args.file,
        start_month=args.start_month,
        end_month=args.end_month,
        flow_type=args.flow,
        currency=args.currency,
        force=args.force,
    )
    return _save_gacc_collection(args, collection)


def handle_gacc_replay(args: argparse.Namespace) -> int:
    """处理 GACC RAW manifest 回放。"""
    collector = _build_gacc_collector(args)
    collection = collector.collect(
        start_month=args.start_month,
        end_month=args.end_month,
        flow_type=args.flow,
        currency=args.currency,
    )
    return _save_gacc_collection(args, collection)


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
        "hs_level",
        "hs_parent_code",
        "quantity_unit",
        "target_l1_name",
        "target_l2_names",
        "target_l3_codes",
        "target_l3_names",
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

    if args.action == "tariffline":
        return handle_tariffline(args)
    if args.action == "gacc-import":
        return handle_gacc_import(args)
    if args.action == "gacc-replay":
        return handle_gacc_replay(args)
    if args.action == "catalog":
        return handle_catalog(args)
    logger.error(f"未知子命令: {args.action}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
