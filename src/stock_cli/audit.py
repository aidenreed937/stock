"""数据质量审计 CLI 兼容入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Any

from stock_core.utils.logger import logger
from stock_data.governance.audit.facade import (
    audit_result_failed,
    resolve_audit_target_date,
    run_audit,
)

_resolve_audit_target_date = resolve_audit_target_date


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="金融数据质量、存储对账与指标专项审计 CLI")
    parser.add_argument(
        "-t",
        "--type",
        dest="audit_type",
        default="master",
        choices=[
            "master",
            "reconciliation",
            "recon",
            "index",
            "acceptance",
            "valuation",
            "factor",
            "moneyflow",
            "distribution",
            "all",
        ],
        help="审计套件类型",
    )
    parser.add_argument(
        "-s",
        "--source",
        "--data-source",
        dest="source",
        default="tushare",
        help="待审计数据源标识 (默认 tushare)",
    )
    parser.add_argument("-d", "--date", dest="date", help="指定审计目标日期 (YYYY-MM-DD)")
    parser.add_argument("--start", dest="start", help="指定历史对账起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", dest="end", help="指定历史对账结束日期 (YYYY-MM-DD)")
    parser.add_argument("--max-workers", dest="max_workers", type=int, default=4)
    parser.add_argument("--show-details", dest="show_details", action="store_true")
    parser.add_argument(
        "--domain",
        choices=[
            "equity",
            "industry",
            "index",
            "macro_liquidity",
            "macro_econ",
            "fundamental",
            "metadata",
        ],
        default=None,
        help="按业务领域过滤审计",
    )
    parser.add_argument(
        "--frequency",
        "--freq",
        dest="frequency",
        choices=["daily", "monthly", "quarterly", "static"],
        default=None,
        help="按时态周期过滤审计",
    )
    parser.add_argument("--dataset", default=None, help="指定审计的数据集名称")
    parser.add_argument("--raw-root", default=None, help="回填验收时 RAW 数据根目录")
    parser.add_argument("--min-raw-ratio", type=float, default=None)
    return parser


def main() -> None:
    """解析参数并调用数据审计 Facade。"""
    args = _build_parser().parse_args()
    target_date = date.fromisoformat(args.date) if args.date else None
    start_date = date.fromisoformat(args.start) if args.start else None
    end_date = date.fromisoformat(args.end) if args.end else None
    logger.info(
        f"启动数据审计套件: 类型=[{args.audit_type}], 数据源=[{args.source}], "
        f"目标范围=[{f'{start_date} ~ {end_date}' if start_date and end_date else (target_date or '最新')}]"
    )
    run_kwargs: dict[str, Any] = {
        "audit_type": args.audit_type,
        "data_source": args.source,
        "target_date": target_date,
        "start_date": start_date,
        "end_date": end_date,
        "domain": args.domain,
        "frequency": args.frequency,
        "dataset": args.dataset,
        "max_workers": args.max_workers,
        "show_details": args.show_details,
    }
    if args.raw_root is not None:
        run_kwargs["raw_root"] = args.raw_root
    if args.min_raw_ratio is not None:
        run_kwargs["min_raw_ratio"] = args.min_raw_ratio
    try:
        result = run_audit(**run_kwargs)
    except Exception as error:
        logger.error(f"数据审计执行失败: {error}")
        sys.exit(1)
    if audit_result_failed(result):
        logger.error("数据审计存在失败项")
        sys.exit(1)
    logger.info("数据审计执行完毕！")


if __name__ == "__main__":
    main()
