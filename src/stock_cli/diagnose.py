"""个股深度量化诊断 CLI。

为用户与 Agent 提供单标的一键行情、均线、估值分位、财务质量、排雷与市场温度聚合。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from stock_analytics.pipelines.stock_diagnostics import run_stock_diagnostics
from stock_core.utils.logger import logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="单标的量化全景体检与诊断聚合 (CLI / Agent 接口)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-s",
        "--symbol",
        required=True,
        help="股票代码 (如 600519 或 600519.SH / 300750)",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        default=None,
        help="指定诊断基准日期 (YYYY-MM-DD, 默认最新数据日期)",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="output_format",
        choices=["json", "markdown"],
        default="json",
        help="输出格式: json (紧凑型专为 Agent 优化) 或 markdown (人类友好研报)",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Curated 数据根目录覆盖",
    )
    return parser


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    target_date: date | None = None
    if args.as_of:
        try:
            target_date = date.fromisoformat(args.as_of)
        except ValueError:
            logger.error("日期格式错误，请使用 YYYY-MM-DD: {}", args.as_of)
            sys.exit(1)

    try:
        result = run_stock_diagnostics(
            symbol=args.symbol,
            target_date=target_date,
            storage_dir=args.storage_dir,
        )
    except Exception as exc:
        logger.error("个股诊断执行失败: {}", exc)
        sys.exit(1)

    if args.output_format == "json":
        # 紧凑型 JSON 专为 LLM 上下文节省 Token
        sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(result.to_markdown())
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
