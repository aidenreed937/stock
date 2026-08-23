"""投资假设跨周期复盘 CLI 入口。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.thesis_review.pipeline import run_thesis_review
from stock_core.utils.logger import logger
from stock_reporting.engine.renderer import ReportRenderer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.thesis_review",
        description="投资假设跨周期复盘 CLI: 自动执行业绩/估值双归因、假设证伪与风控红线核验",
    )
    parser.add_argument(
        "--symbol",
        "-s",
        required=True,
        help="标的代码 (如 600519.SH)",
    )
    parser.add_argument(
        "--thesis-date",
        "-t",
        dest="thesis_date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="投资假设建立基准日 (YYYY-MM-DD，默认使用假设文件或 90 天前)",
    )
    parser.add_argument(
        "--as-of",
        "-d",
        dest="as_of_date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="当前复盘核验基准日 (YYYY-MM-DD，默认为最新已落盘交易日)",
    )
    parser.add_argument(
        "--format",
        "-f",
        dest="output_format",
        choices=["json", "markdown"],
        default="markdown",
        help="输出格式: markdown (标准复盘报告) 或 json",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        default=True,
        help="是否将复盘报告自动保存至 output/reports/thesis_reviews/ (默认开启)",
    )
    parser.add_argument(
        "--theses-dir",
        type=Path,
        default=None,
        help="假设存储目录 (默认 reports/theses/)",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=None,
        help="自定义数据根目录 (默认 data/)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        result = run_thesis_review(
            symbol=args.symbol,
            thesis_date=args.thesis_date,
            target_date=args.as_of_date,
            theses_dir=args.theses_dir,
            storage_dir=args.storage_dir,
        )
    except Exception as exc:
        logger.error(f"执行投资假设复盘失败: {exc}")
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)

    if args.output_format == "json":
        output_text = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        sys.stdout.write(output_text + "\n")
    else:
        renderer = ReportRenderer.get_instance()
        context = result.to_dict()
        output_text = renderer.render("review/thesis_review.md.j2", context)
        sys.stdout.write(output_text + "\n")

    if args.save:
        out_dir = Path("output/reports/thesis_reviews")
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{result.thesis.symbol}_{result.thesis.created_date}_至_{result.as_of_date}_复盘自省报告.md"
        report_file = out_dir / filename
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(output_text)
        logger.info(f"复盘报告已自动落盘至: {report_file}")


if __name__ == "__main__":
    main()
